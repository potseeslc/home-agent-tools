import json
from pathlib import Path
import time

import pytest

from home_agent_tools import cli


def test_config_preserves_other_servers_and_protects_existing(tmp_path):
    path = tmp_path / "Library/Application Support/Claude/claude_desktop_config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {"theme": "dark", "mcpServers": {"existing": {"command": "existing"}}}
        )
    )
    profile = tmp_path / "private/claude.json"
    cli.configure("claude", profile, home=tmp_path)
    config = json.loads(path.read_text())
    assert (
        config["theme"] == "dark"
        and config["mcpServers"]["existing"]["command"] == "existing"
    )
    assert str(profile) in config["mcpServers"]["home-agent-tools"]["args"]
    assert len(list(path.parent.glob("*.hat-backup-*"))) == 1
    assert path.stat().st_mode & 0o077 == 0
    config["mcpServers"]["home-agent-tools"] = {"command": "unrelated"}
    path.write_text(json.dumps(config))
    with pytest.raises(cli.ConnectionError):
        cli.configure("claude", profile, home=tmp_path)


def test_codex_uses_supported_cli_without_a_secret_in_config(tmp_path, monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    interpreter = tmp_path / "venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to("/usr/bin/python3")
    monkeypatch.setattr(cli.sys, "executable", str(interpreter))
    calls = []
    cli.configure(
        "codex",
        tmp_path / "codex.json",
        home=tmp_path,
        runner=lambda argv, **kwargs: calls.append(argv),
    )
    assert calls[0][:5] == ["codex", "mcp", "add", "home-agent-tools", "--"]
    assert "bridge" in calls[0]
    assert calls[0][5] == str(interpreter)


def test_client_refresh_keeps_fixed_deadline(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    deadline = time.time() + 100000
    profile = {
        "server": "https://hub.example",
        "client_id": "client",
        "access_token": "old",
        "refresh_token": "refresh",
        "access_expires_at": 0,
        "authorization_expires_at": deadline,
    }
    cli.private_write(path, json.dumps(profile))

    def request(url, body, form):
        assert (
            body["resource"] == "https://hub.example/mcp"
            and body["grant_type"] == "refresh_token"
        )
        return {
            "access_token": "new",
            "refresh_token": "rotated",
            "expires_in": 600,
            "authorization_expires_at": deadline,
        }

    monkeypatch.setattr(cli, "request", request)
    assert cli.fresh_profile(path)["access_token"] == "new"
    assert cli.profile_read(path)["authorization_expires_at"] == deadline
    profile["authorization_expires_at"] = 0
    cli.private_write(path, json.dumps(profile))
    with pytest.raises(cli.ConnectionError):
        cli.fresh_profile(path)
    path.chmod(0o644)
    with pytest.raises(cli.ConnectionError):
        cli.profile_read(path)


def test_server_url_rejects_credential_redirect_targets():
    for value in [
        "http://public.example",
        "https://user:pass@hub.example",
        "https://hub.example/path",
        "https://hub.example?token=bad",
    ]:
        with pytest.raises(cli.ConnectionError):
            cli.server_url(value)
    assert cli.server_url("https://hub.example/") == "https://hub.example"


def test_full_cli_browser_authorization_and_stdio_bridge(tmp_path, monkeypatch):
    """A real loopback HTTP/stdio journey with a simulated identity broker."""
    import socket
    import subprocess
    import sys
    import threading
    import httpx
    import uvicorn
    from urllib.parse import parse_qs, urlsplit
    from home_agent_tools.app import create_app, Settings
    from test_app import Broker, session

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    origin = "http://127.0.0.1:" + str(listener.getsockname()[1])
    cfg = Settings(
        "http://broker",
        origin,
        "x" * 40,
        frozenset({"alice"}),
        str(tmp_path / "server.sqlite"),
    )
    app = create_app(cfg, httpx.MockTransport(Broker()))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(
        target=lambda: server.run(sockets=[listener]), daemon=True
    )
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    failures = []

    def browser(url):
        def owner():
            try:
                with httpx.Client(
                    cookies={"jwt_token": session("alice")}, timeout=10
                ) as c:
                    r = c.get(url)
                    rid = parse_qs(urlsplit(r.headers["location"]).query)["authorize"][
                        0
                    ]
                    bootstrap = c.get(origin + "/api/bootstrap").json()
                    headers = {"Origin": origin, "X-HAT-CSRF": bootstrap["csrf"]}
                    assert c.post(
                        origin + "/api/connections/gitea/test", headers=headers
                    ).json()["ok"]
                    assert (
                        c.get(origin + "/api/authorizations/" + rid).status_code == 200
                    )
                    approved = c.post(
                        origin + "/api/authorizations/" + rid,
                        headers=headers,
                        json={"approve": True, "services": ["gitea"], "days": 90},
                    )
                    assert approved.status_code == 200, approved.text
                    assert c.get(approved.json()["redirect_url"]).status_code == 200
            except Exception as e:
                failures.append(e)

        threading.Thread(target=owner, daemon=True).start()
        return True

    monkeypatch.setattr(cli.webbrowser, "open", browser)
    try:
        profile = cli.authorize(origin, "Test connector", ["gitea"], 90)
        assert not failures
        assert cli.check_profile(profile) == 4
        path = tmp_path / "connection.json"
        cli.private_write(path, json.dumps(profile))
        messages = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ]
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "home_agent_tools.cli",
                "bridge",
                "--profile",
                str(path),
            ],
            input="\n".join(json.dumps(m) for m in messages) + "\n",
            text=True,
            capture_output=True,
            timeout=20,
            check=True,
        )
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        assert (
            len(responses) == 2
            and responses[0]["result"]["serverInfo"]["name"] == "Home Agent Tools"
        )
        assert len(responses[1]["result"]["tools"]) == 4
        assert profile["access_token"] not in result.stdout + result.stderr
        profile["access_expires_at"] = 0
        cli.private_write(path, json.dumps(profile))
        renewed = cli.fresh_profile(path)
        assert renewed["refresh_token"] != profile["refresh_token"]
        cli.request(
            origin + "/oauth/revoke",
            {"client_id": renewed["client_id"], "token": renewed["refresh_token"]},
            form=True,
        )
        with pytest.raises(cli.ConnectionError):
            cli.check_profile(renewed)
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()


def test_renew_keeps_new_profile_when_old_revocation_is_unavailable(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    path = tmp_path / "codex.json"
    old = {
        "server": "https://hub.example",
        "client_id": "old",
        "refresh_token": "old-refresh",
    }
    new = {
        "server": "https://hub.example",
        "client_id": "new",
        "refresh_token": "new-refresh",
        "authorization_expires_at": time.time() + 86400,
    }
    cli.private_write(path, json.dumps(old))
    monkeypatch.setattr(cli, "authorize", lambda *args: new)
    monkeypatch.setattr(cli, "check_profile", lambda p: 4)
    monkeypatch.setattr(cli, "configure", lambda *args: "config")
    attempts = []

    def unavailable(url, body, **kwargs):
        attempts.append(body["token"])
        raise cli.ConnectionError("Unavailable")

    monkeypatch.setattr(cli, "request", unavailable)
    cli.setup(
        SimpleNamespace(
            server="https://hub.example",
            clients=["codex"],
            config_dir=str(tmp_path),
            renew=True,
            services=["gitea"],
            days=90,
            no_browser=True,
        )
    )
    assert cli.profile_read(path)["refresh_token"] == "new-refresh"
    assert attempts == ["old-refresh"]
