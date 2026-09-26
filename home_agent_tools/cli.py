"""Local setup and stdio bridge. No upstream service credentials leave the hub."""

import argparse
import base64
import contextlib
import hashlib
import http.server
import importlib.metadata
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

MAX_MESSAGE = 65536


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ConnectionError(Exception):
    pass


def request(url, body=None, token=None, form=False):
    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        headers["Content-Type"] = (
            "application/x-www-form-urlencoded" if form else "application/json"
        )
        body = (
            urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
        )
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as result:
            raw = result.read(4 * 1024 * 1024)
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403):
            raise ConnectionError(
                "Authorization needs attention. Run home-agent-tools setup with --renew to sign in again."
            ) from None
        raise ConnectionError(
            f"Home Agent Tools returned HTTP {e.code}. Try again shortly."
        ) from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise ConnectionError(
            "Cannot reach Home Agent Tools. Check the server address and any required tunnel."
        ) from None


def server_url(value):
    u = urllib.parse.urlsplit(value)
    if (
        u.username
        or u.password
        or u.query
        or u.fragment
        or u.path not in ("", "/")
        or not u.hostname
        or (
            u.scheme != "https"
            and not (
                u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1", "::1")
            )
        )
    ):
        raise ConnectionError("Use an HTTPS server origin, or a localhost SSH tunnel.")
    return value.rstrip("/")


def private_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".hat-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as out:
            out.write(value)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def profile_lock(path):
    if os.name != "posix":
        raise ConnectionError("The local connector currently supports macOS and Linux.")
    import fcntl

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def profile_read(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ConnectionError(
            "The connection file must be private (mode 0600), not a symlink."
        )
    return json.loads(path.read_text())


def authorize(server, name, services, days, no_browser=False):
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    state = secrets.token_urlsafe(32)
    answer = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            q = urllib.parse.parse_qs(u.query)
            expected_host = f"127.0.0.1:{self.server.server_port}"
            if (
                self.headers.get("Host") != expected_host
                or u.path != "/callback"
                or q.get("state") != [state]
                or q.get("iss") != [server]
            ):
                self.send_error(400, "Invalid authorization callback")
                return
            if answer:
                self.send_error(409, "Callback already received")
                return
            answer.update({k: v[0] for k, v in q.items() if len(v) == 1})
            message = (
                b"Authorization received. Return to your terminal."
                if "code" in answer
                else b"Access was not approved. Return to your terminal."
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)

    with http.server.HTTPServer(("127.0.0.1", 0), Callback) as callback:
        callback.timeout = 1
        redirect = f"http://127.0.0.1:{callback.server_port}/callback"
        registration = request(
            server + "/oauth/register",
            {
                "client_name": name,
                "redirect_uris": [redirect],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        client = registration["client_id"]
        query = {
            "client_id": client,
            "redirect_uri": redirect,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "resource": server + "/mcp",
            "scope": " ".join(s + ":read" for s in services),
            "days": days,
        }
        url = server + "/oauth/authorize?" + urllib.parse.urlencode(query)
        print(
            f"Approve {name} in your browser. Match verification code {hashlib.sha256(challenge.encode()).hexdigest()[:8].upper()}.",
            flush=True,
        )
        print(url, flush=True)
        if not no_browser:
            webbrowser.open(url)
        deadline = time.monotonic() + 600
        while not answer and time.monotonic() < deadline:
            callback.handle_request()
        if "code" not in answer:
            raise ConnectionError(
                "Authorization was denied or timed out. No agent was configured."
            )
    tokens = request(
        server + "/oauth/token",
        {
            "grant_type": "authorization_code",
            "client_id": client,
            "redirect_uri": redirect,
            "code": answer["code"],
            "code_verifier": verifier,
            "resource": server + "/mcp",
        },
        form=True,
    )
    return {
        **tokens,
        "server": server,
        "client_id": client,
        "access_expires_at": time.time() + tokens["expires_in"],
    }


def fresh_profile(path):
    with profile_lock(path):
        profile = profile_read(path)
        if profile["authorization_expires_at"] <= time.time():
            raise ConnectionError(
                "Your fixed approval expired. Run home-agent-tools setup --renew to sign in again."
            )
        if profile["access_expires_at"] <= time.time() + 60:
            tokens = request(
                profile["server"] + "/oauth/token",
                {
                    "grant_type": "refresh_token",
                    "client_id": profile["client_id"],
                    "refresh_token": profile["refresh_token"],
                    "resource": profile["server"] + "/mcp",
                },
                form=True,
            )
            profile.update(tokens)
            profile["access_expires_at"] = time.time() + tokens["expires_in"]
            private_write(path, json.dumps(profile))
        return profile


def bridge(profile_path):
    for_raw = sys.stdin.buffer
    while True:
        line = for_raw.readline(MAX_MESSAGE + 1)
        if not line:
            return
        if len(line) > MAX_MESSAGE:
            print("MCP message exceeds the connector limit.", file=sys.stderr)
            return
        msg = None
        try:
            msg = json.loads(line)
            if not isinstance(msg, dict):
                raise ValueError()
            profile = fresh_profile(profile_path)
            result = request(profile["server"] + "/mcp", msg, profile["access_token"])
        except (ConnectionError, ValueError, OSError, KeyError) as e:
            message = (
                str(e)
                if isinstance(e, ConnectionError)
                else "Invalid message or connection profile. Run home-agent-tools setup."
            )
            print(message, file=sys.stderr)
            result = {
                "jsonrpc": "2.0",
                "id": msg.get("id") if isinstance(msg, dict) else None,
                "error": {"code": -32001, "message": message},
            }
        if isinstance(msg, dict) and "id" not in msg:
            continue
        if result is not None:
            print(json.dumps(result), flush=True)


def detect(home=None):
    home = Path(home or Path.home())
    clients = []
    if shutil.which("codex"):
        clients.append("codex")
    if (home / "Library/Application Support/Claude").is_dir() or Path(
        "/Applications/Claude.app"
    ).exists():
        clients.append("claude")
    return clients


def config_path(client, home):
    if client == "claude":
        return home / "Library/Application Support/Claude/claude_desktop_config.json"
    return Path(os.environ.get("CODEX_HOME", str(home / ".codex"))) / "config.toml"


def managed(entry, profile):
    return (
        isinstance(entry, dict)
        and "home_agent_tools.cli" in entry.get("args", [])
        and str(profile) in entry.get("args", [])
    )


def configure(client, profile, home=None, runner=None):
    home = Path(home or Path.home())
    profile = Path(profile)
    entry = {
        "command": str(Path(sys.executable).absolute()),
        "args": ["-m", "home_agent_tools.cli", "bridge", "--profile", str(profile)],
    }
    if client == "generic":
        output = profile.with_suffix(".mcp.json")
        private_write(
            output, json.dumps({"mcpServers": {"home-agent-tools": entry}}, indent=2)
        )
        return str(output)
    path = config_path(client, home)
    if path.is_symlink():
        raise ConnectionError("Refusing to replace a symlinked client configuration.")
    before = path.read_text() if path.exists() else ""
    if client == "claude":
        config = json.loads(before or "{}")
        existing = config.get("mcpServers", {}).get("home-agent-tools")
    else:
        config = tomllib.loads(before)
        existing = config.get("mcp_servers", {}).get("home-agent-tools")
    if existing and not managed(existing, profile):
        raise ConnectionError(
            "This client already has a different home-agent-tools entry. Rename it before setup."
        )
    if before:
        private_write(
            path.with_name(path.name + ".hat-backup-" + str(time.time_ns())), before
        )
    if client == "claude":
        config.setdefault("mcpServers", {})["home-agent-tools"] = entry
        private_write(path, json.dumps(config, indent=2) + "\n")
    else:
        (runner or subprocess.run)(
            [
                "codex",
                "mcp",
                "add",
                "home-agent-tools",
                "--",
                entry["command"],
                *entry["args"],
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    return str(path)


def check_profile(profile):
    response = request(
        profile["server"] + "/mcp",
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        profile["access_token"],
    )
    if not response or "result" not in response:
        raise ConnectionError("The agent could not discover its tools.")
    return len(response["result"]["tools"])


def setup(args):
    server = server_url(args.server)
    clients = args.clients or []
    if not clients:
        detected = detect()
        print("Detected clients: " + (", ".join(detected) or "none"))
        if not sys.stdin.isatty():
            raise ConnectionError(
                "Choose clients explicitly with --clients codex claude or --clients generic."
            )
        clients = (
            input("Connect which clients? (space-separated; codex, claude, generic): ")
            .strip()
            .split()
        )
    if not clients or set(clients) - {"codex", "claude", "generic"}:
        raise ConnectionError("Choose codex, claude, or generic.")
    directory = Path(args.config_dir or Path.home() / ".config/home-agent-tools")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    for client in dict.fromkeys(clients):
        profile_path = directory / (client + ".json")
        if profile_path.exists() and not args.renew:
            profile = fresh_profile(profile_path)
            if profile["server"] != server:
                raise ConnectionError(
                    "Existing profile uses another server. Use a separate --config-dir."
                )
        else:
            old = profile_read(profile_path) if profile_path.exists() else None
            profile = authorize(
                server,
                "Home Agent Tools " + client,
                args.services,
                args.days,
                args.no_browser,
            )
            try:
                check_profile(profile)
                private_write(profile_path, json.dumps(profile))
            except Exception:
                request(
                    server + "/oauth/revoke",
                    {
                        "client_id": profile["client_id"],
                        "token": profile["refresh_token"],
                    },
                    form=True,
                )
                raise
            if old:
                try:
                    request(
                        old["server"] + "/oauth/revoke",
                        {"client_id": old["client_id"], "token": old["refresh_token"]},
                        form=True,
                    )
                except ConnectionError:
                    print(
                        "New approval saved. The previous approval could not be revoked; "
                        "remove it from the old server's Agents page.",
                        file=sys.stderr,
                    )
        path = configure(client, profile_path)
        print(
            f"{client}: {check_profile(profile)} tools ready. Configuration: {path}. Restart the client if needed."
        )
        print(
            "Approval expires "
            + time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(profile["authorization_expires_at"])
            )
        )


def main():
    parser = argparse.ArgumentParser(
        prog="home-agent-tools",
        description="Sign in once and connect your local agents to your tools.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("setup")
    install.add_argument("--server", default="http://localhost:4444")
    install.add_argument("--clients", nargs="+", choices=["codex", "claude", "generic"])
    install.add_argument(
        "--services",
        nargs="+",
        choices=["gitea", "homeassistant"],
        default=["gitea", "homeassistant"],
    )
    install.add_argument("--days", type=int, choices=[30, 90], default=90)
    install.add_argument("--config-dir")
    install.add_argument("--no-browser", action="store_true")
    install.add_argument("--renew", action="store_true")
    connect = commands.add_parser("bridge")
    connect.add_argument("--profile", required=True)
    status = commands.add_parser("status")
    status.add_argument("--profile", required=True)
    args = parser.parse_args()
    try:
        if args.command == "setup":
            setup(args)
        elif args.command == "bridge":
            bridge(args.profile)
        else:
            print(str(check_profile(fresh_profile(args.profile))) + " tools available.")
    except (
        ConnectionError,
        OSError,
        ValueError,
        KeyError,
        subprocess.CalledProcessError,
    ) as e:
        print(
            (
                str(e)
                if isinstance(e, ConnectionError)
                else "Setup could not finish. Check the local configuration and try again."
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
