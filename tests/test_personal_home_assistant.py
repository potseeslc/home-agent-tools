import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from test_app import Broker, session, headers, rpc
from home_agent_tools.app import Settings, create_app


@pytest.fixture
async def personal(tmp_path):
    calls = []

    def provider(request):
        calls.append(request)
        if request.url.path == "/auth/token":
            values = parse_qs(request.content.decode())
            if values.get("refresh_token") == ["revoked"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            if values.get("action") == ["revoke"]:
                return httpx.Response(200, json={})
            return httpx.Response(
                200,
                json={
                    "access_token": "PERSONAL-ACCESS",
                    "refresh_token": "PERSONAL-REFRESH",
                    "expires_in": 1800,
                },
            )
        if request.url.path == "/api/":
            return httpx.Response(200, json={"message": "API running."})
        return httpx.Response(404)

    cfg = Settings(
        "http://broker",
        "http://localhost:4444",
        "s" * 40,
        frozenset({"alice", "bob"}),
        str(tmp_path / "db.sqlite"),
        ha_url="https://ha.example",
    )
    b = Broker()
    app = create_app(cfg, httpx.MockTransport(b), httpx.MockTransport(provider))

    async def identity(access):
        assert access == "PERSONAL-ACCESS"
        return {"id": "ha-alice", "login": "Alice at home"}

    app.state.home_assistant.identity = identity
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=cfg.public_url
    ) as c:
        c.cookies.set("jwt_token", session("alice"))
        yield c, app, b, calls


async def connect(c):
    r = await c.post("/api/connections/homeassistant/connect", headers=await headers(c))
    assert r.status_code == 200
    q = parse_qs(urlsplit(r.json()["url"]).query)
    assert q["client_id"] == ["http://localhost:4444/"]
    assert q["redirect_uri"] == [
        "http://localhost:4444/connections/homeassistant/callback"
    ]
    return q["state"][0]


async def test_personal_identity_refresh_and_no_shared_fallback(personal):
    c, app, b, calls = personal
    assert (
        await c.post("/api/connections/homeassistant/test", headers=await headers(c))
    ).status_code == 409
    nonce = await connect(c)
    assert (
        await c.get(
            "/connections/homeassistant/callback",
            params={"state": nonce, "code": "code"},
        )
    ).status_code == 307
    assert (
        await c.get(
            "/connections/homeassistant/callback",
            params={"state": nonce, "code": "code"},
        )
    ).status_code == 400
    result = (
        await c.post("/api/connections/homeassistant/test", headers=await headers(c))
    ).json()
    assert result["identity"]["id"] == "ha-alice"
    a = (
        await c.post(
            "/api/agents",
            headers=await headers(c),
            json={"name": "HA agent", "services": ["homeassistant"], "days": 90},
        )
    ).json()
    assert "token" in a, a
    assert not (await rpc(c, a["token"])).json()["result"]["isError"]
    assert not b.calls  # No shared HA gateway call, including verification.
    saved = app.state.vault.get("ha", "alice")
    saved["expires"] = 0
    app.state.vault.put("ha", "alice", saved)
    assert not (await rpc(c, a["token"])).json()["result"]["isError"]
    assert any(b"grant_type=refresh_token" in r.content for r in calls)
    raw = open(app.state.config.state_path, "rb").read()
    assert b"PERSONAL-ACCESS" not in raw and b"PERSONAL-REFRESH" not in raw
    c.cookies.set("jwt_token", session("bob"))
    assert (
        await c.post("/api/connections/homeassistant/test", headers=await headers(c))
    ).status_code == 409
    c.cookies.set("jwt_token", session("alice"))
    saved = app.state.vault.get("ha", "alice")
    saved.update(expires=0, refresh_token="revoked")
    app.state.vault.put("ha", "alice", saved)
    assert "error" in (await rpc(c, a["token"])).json()
    assert app.state.vault.get("ha", "alice") is None
    assert not b.calls


async def test_home_assistant_state_is_owner_and_browser_bound(personal):
    c, app, b, calls = personal
    nonce = await connect(c)
    c.cookies.set("jwt_token", session("bob"))
    assert (
        await c.get(
            "/connections/homeassistant/callback",
            params={"state": nonce, "code": "code"},
        )
    ).status_code == 400
    assert not calls
    c.cookies.set("jwt_token", session("alice"))
    assert (
        await c.get(
            "/connections/homeassistant/callback",
            params={"state": "wrong", "code": "code"},
        )
    ).status_code == 400
    assert not calls
    assert (
        await c.get(
            "/connections/homeassistant/callback",
            params={"state": nonce, "code": "code"},
        )
    ).status_code == 307
    a = (
        await c.post(
            "/api/agents",
            headers=await headers(c),
            json={"name": "HA agent", "services": ["homeassistant"]},
        )
    ).json()
    await connect(c)
    assert (await rpc(c, a["token"])).status_code == 401
    await c.delete("/api/connections/homeassistant", headers=await headers(c))
    assert app.state.vault.get("ha", "alice") is None
