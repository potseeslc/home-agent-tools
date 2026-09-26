import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest

from test_app import setup, headers, check, rpc, session
from home_agent_tools.authorization import challenge


async def begin(c, days=90, services="gitea:read"):
    client = (
        await c.post(
            "/oauth/register",
            json={
                "client_name": "Desktop test",
                "redirect_uris": ["http://127.0.0.1/callback"],
            },
        )
    ).json()["client_id"]
    verifier = "a" * 64
    params = {
        "client_id": client,
        "redirect_uri": "http://127.0.0.1:49321/callback",
        "response_type": "code",
        "code_challenge_method": "S256",
        "code_challenge": challenge(verifier),
        "state": "test-state",
        "resource": "http://localhost:4444/mcp",
        "scope": services,
        "days": str(days),
    }
    r = await c.get("/oauth/authorize", params=params)
    assert r.status_code == 302, r.text
    rid = parse_qs(urlsplit(r.headers["location"]).query)["authorize"][0]
    return client, verifier, params, rid


async def approved(c, days=90):
    await check(c, "gitea")
    client, verifier, params, rid = await begin(c, days)
    assert (await c.get("/api/authorizations/" + rid)).status_code == 200
    r = await c.post(
        "/api/authorizations/" + rid,
        headers=await headers(c),
        json={"approve": True, "services": ["gitea"], "days": days},
    )
    assert r.status_code == 200, r.text
    q = parse_qs(urlsplit(r.json()["redirect_url"]).query)
    assert q["state"] == ["test-state"] and q["iss"] == ["http://localhost:4444"]
    form = {
        "grant_type": "authorization_code",
        "client_id": client,
        "code": q["code"][0],
        "redirect_uri": params["redirect_uri"],
        "code_verifier": verifier,
        "resource": params["resource"],
    }
    return client, form, rid


async def tokens(c, days=90):
    client, form, rid = await approved(c, days)
    r = await c.post("/oauth/token", data=form)
    assert r.status_code == 200, r.text
    return client, r.json(), form


async def test_pkce_resource_and_one_time_code(setup):
    c, app, b = setup
    client, form, rid = await approved(c)
    wrong = {**form, "code_verifier": "b" * 64}
    assert (await c.post("/oauth/token", data=wrong)).json()["error"] == "invalid_grant"
    assert (
        await c.post(
            "/oauth/token", data={**form, "resource": "https://other.example/mcp"}
        )
    ).json()["error"] == "invalid_target"
    r = await c.post("/oauth/token", data=form)
    assert r.status_code == 200
    assert (await c.post("/oauth/token", data=form)).json()["error"] == "invalid_grant"
    token = r.json()
    assert token["expires_in"] <= 600
    assert 89 * 86400 < token["authorization_expires_at"] - time.time() <= 90 * 86400
    assert token["scope"] == "gitea:read"
    assert (await rpc(c, token["access_token"], "tools/list", {})).status_code == 200
    assert (
        await rpc(
            c, token["access_token"], params={"name": "ha-api-status", "arguments": {}}
        )
    ).json()["error"]["code"] == -32601
    raw = open(app.state.config.state_path, "rb").read()
    assert (
        token["access_token"].encode() not in raw
        and token["refresh_token"].encode() not in raw
    )
    assert all(t.encode() not in raw for t in b.tokens)


async def test_rotation_replay_revokes_only_its_grant(setup):
    c, app, b = setup
    client, a, _ = await tokens(c)
    other_client, other, _ = await tokens(c)
    form = {
        "grant_type": "refresh_token",
        "client_id": client,
        "refresh_token": a["refresh_token"],
        "resource": "http://localhost:4444/mcp",
    }
    renewed = (await c.post("/oauth/token", data=form)).json()
    assert renewed["refresh_token"] != a["refresh_token"]
    assert renewed["authorization_expires_at"] == a["authorization_expires_at"]
    assert (await c.post("/oauth/token", data=form)).json()["error"] == "invalid_grant"
    assert (await rpc(c, renewed["access_token"], "tools/list", {})).status_code == 401
    assert (await rpc(c, other["access_token"], "tools/list", {})).status_code == 200


async def test_lease_expiry_and_browser_logout(setup):
    c, app, b = setup
    client, a, _ = await tokens(c, 30)
    await c.post("/api/logout", headers=await headers(c))
    c.cookies.clear()
    assert (await rpc(c, a["access_token"], "tools/list", {})).status_code == 200
    with app.state.store.db() as db:
        db.execute(
            "UPDATE agents SET expires=? WHERE id=?", (time.time() - 1, a["agent_id"])
        )
    assert (await rpc(c, a["access_token"], "tools/list", {})).status_code == 401
    r = await c.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client,
            "refresh_token": a["refresh_token"],
            "resource": "http://localhost:4444/mcp",
        },
    )
    assert r.json()["error"] == "invalid_grant"


async def test_review_owner_binding_csrf_and_denial(setup):
    c, app, b = setup
    client, verifier, params, rid = await begin(c, 30)
    assert (await c.get("/api/authorizations/" + rid)).status_code == 200
    assert (
        await c.post(
            "/api/authorizations/" + rid, json={"approve": True, "services": ["gitea"]}
        )
    ).status_code == 403
    assert (
        await c.post(
            "/api/authorizations/" + rid,
            headers=await headers(c),
            json={"approve": True, "services": ["homeassistant"], "days": 30},
        )
    ).status_code == 400
    assert (
        await c.post(
            "/api/authorizations/" + rid,
            headers=await headers(c),
            json={"approve": True, "services": ["gitea"], "days": 90},
        )
    ).status_code == 400
    c.cookies.set("jwt_token", session("bob"))
    assert (await c.get("/api/authorizations/" + rid)).status_code == 403
    c.cookies.set("jwt_token", session("alice"))
    r = await c.post(
        "/api/authorizations/" + rid, headers=await headers(c), json={"approve": False}
    )
    assert parse_qs(urlsplit(r.json()["redirect_url"]).query)["error"] == [
        "access_denied"
    ]
    assert not b.tokens


async def test_discovery_callbacks_and_foreign_client(setup):
    c, app, b = setup
    r = await c.post("/mcp", json={})
    assert r.status_code == 401
    assert "resource_metadata=" in r.headers["www-authenticate"]
    assert (await c.get("/.well-known/oauth-authorization-server")).json()[
        "code_challenge_methods_supported"
    ] == ["S256"]
    for uri in (
        "https://evil.example/callback",
        "http://localhost/callback",
        "http://127.0.0.1/callback#bad",
        "http://user@127.0.0.1/callback",
    ):
        assert (
            await c.post("/oauth/register", json={"redirect_uris": [uri]})
        ).status_code == 400
    client, verifier, params, rid = await begin(c)
    assert (
        await c.get(
            "/oauth/authorize", params={**params, "code_challenge_method": "plain"}
        )
    ).status_code == 400
    c.cookies.delete("hat_authorization", domain="localhost.local", path="/")
    assert (await c.get("/api/authorizations/" + rid)).status_code == 403
    client, a, form = await tokens(c)
    assert (
        await c.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "wrong",
                "refresh_token": a["refresh_token"],
                "resource": "http://localhost:4444/mcp",
            },
        )
    ).json()["error"] == "invalid_grant"
    await c.post(
        "/oauth/revoke", data={"client_id": client, "token": a["refresh_token"]}
    )
    assert (await rpc(c, a["access_token"], "tools/list", {})).status_code == 401
