"""Personal Home Assistant authorization, identity verification, and refresh."""

import asyncio
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from websockets.asyncio.client import connect


class HomeAssistant:
    def __init__(self, cfg, state, vault, transport=None):
        self.cfg, self.state, self.vault, self.transport = cfg, state, vault, transport
        self.locks = defaultdict(asyncio.Lock)

    async def http(self, method, path, **kwargs):
        if not self.cfg.ha_url:
            raise HTTPException(
                409, "Home Assistant personal authorization is not configured."
            )
        try:
            async with httpx.AsyncClient(
                base_url=self.cfg.ha_url,
                transport=self.transport,
                timeout=20,
                follow_redirects=False,
            ) as client:
                return await client.request(method, path, **kwargs)
        except httpx.HTTPError:
            raise HTTPException(
                502, "Home Assistant is unavailable. Try again shortly."
            ) from None

    def pause(self, owner):
        with self.state.db() as db:
            for row in db.execute(
                "SELECT id,services FROM agents WHERE owner=? AND active=1", (owner,)
            ).fetchall():
                if "homeassistant" in json.loads(row["services"]):
                    db.execute("UPDATE agents SET active=0 WHERE id=?", (row["id"],))

    async def identity(self, access):
        url = (
            self.cfg.ha_url.replace("https://", "wss://", 1).replace(
                "http://", "ws://", 1
            )
            + "/api/websocket"
        )
        try:
            async with asyncio.timeout(20):
                async with connect(
                    url, open_timeout=10, max_size=65536, proxy=None
                ) as ws:
                    if json.loads(await ws.recv()).get("type") != "auth_required":
                        raise ValueError()
                    await ws.send(json.dumps({"type": "auth", "access_token": access}))
                    if json.loads(await ws.recv()).get("type") != "auth_ok":
                        raise ValueError()
                    await ws.send(json.dumps({"id": 1, "type": "auth/current_user"}))
                    reply = json.loads(await ws.recv())
                    result = reply.get("result", {})
                    if not reply.get("success") or not isinstance(
                        result.get("id"), str
                    ):
                        raise ValueError()
                    return {
                        "id": result["id"],
                        "login": str(result.get("name") or "Home Assistant user")[:100],
                    }
        except Exception:
            raise HTTPException(
                502,
                "Home Assistant did not confirm your account. Reconnect and try again.",
            ) from None

    async def token(self, owner, force=False):
        async with self.locks[owner]:
            saved = self.vault.get("ha", owner)
            if not saved or saved["origin"] != self.cfg.ha_url:
                raise HTTPException(
                    409, "Sign in to your Home Assistant account first."
                )
            if not force and saved["expires"] > time.time() + 60:
                return saved["access_token"]
            response = await self.http(
                "POST",
                "/auth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": saved["refresh_token"],
                    "client_id": saved["client_id"],
                },
            )
            if response.status_code in (400, 401, 403):
                self.vault.delete("ha", owner)
                self.state.observation(owner, "homeassistant", "needs_attention")
                raise HTTPException(409, "Home Assistant sign-in is required.")
            if response.status_code != 200:
                raise HTTPException(
                    502,
                    "Home Assistant could not renew the connection. Try again shortly.",
                )
            data = response.json()
            if (
                not isinstance(data.get("access_token"), str)
                or not isinstance(data.get("expires_in"), (int, float))
                or data["expires_in"] <= 0
            ):
                raise HTTPException(
                    502, "Home Assistant returned an invalid token response."
                )
            saved.update(
                access_token=data["access_token"],
                expires=time.time() + data["expires_in"],
            )
            if data.get("refresh_token"):
                saved["refresh_token"] = data["refresh_token"]
            self.vault.put("ha", owner, saved)
            self.state.event(
                owner, "Connection manager", "connection.refreshed", "homeassistant"
            )
            return saved["access_token"]

    async def status(self, owner):
        access = await self.token(owner)
        response = await self.http(
            "GET", "/api/", headers={"Authorization": "Bearer " + access}
        )
        if response.status_code == 401:
            access = await self.token(owner, force=True)
            response = await self.http(
                "GET", "/api/", headers={"Authorization": "Bearer " + access}
            )
        if response.status_code != 200 or response.json() != {
            "message": "API running."
        }:
            self.state.observation(owner, "homeassistant", "needs_attention")
            raise HTTPException(
                409, "Home Assistant needs attention. Check your connection."
            )
        return {
            "content": [
                {"type": "text", "text": json.dumps({"message": "API running."})}
            ],
            "isError": False,
        }

    async def verify(self, owner):
        await self.status(owner)
        identity = await self.identity(await self.token(owner))
        changed = self.state.observation(
            owner, "homeassistant", "connected", json.dumps(identity, sort_keys=True)
        )
        self.state.event(owner, "You", "connection.check", "homeassistant")
        return {
            "ok": True,
            "identity": identity,
            "identity_changed": changed,
            "message": "Personal Home Assistant connection verified.",
        }

    def mount(self, app, user, pending=lambda r: None):
        cfg, state = self.cfg, self.state

        @app.post("/api/connections/homeassistant/connect")
        async def start(request: Request):
            u, _ = await user(request, True)
            if not cfg.ha_url:
                raise HTTPException(
                    409, "An administrator must configure the Home Assistant URL."
                )
            self.pause(u["id"])
            state.observation(u["id"], "homeassistant", "not_checked")
            nonce = secrets.token_urlsafe(40)
            binding = secrets.token_urlsafe(40)
            with state.db() as db:
                db.execute(
                    "DELETE FROM ha_states WHERE owner=? OR expires<?",
                    (u["id"], time.time()),
                )
                db.execute(
                    "INSERT INTO ha_states VALUES (?,?,?,?)",
                    (
                        hashlib.sha256(nonce.encode()).hexdigest(),
                        u["id"],
                        hashlib.sha256(binding.encode()).hexdigest(),
                        time.time() + 600,
                    ),
                )
            query = {
                "client_id": cfg.public_url + "/",
                "redirect_uri": cfg.public_url + "/connections/homeassistant/callback",
                "state": nonce,
            }
            out = JSONResponse(
                {"url": cfg.ha_url + "/auth/authorize?" + urlencode(query)}
            )
            out.set_cookie(
                "hat_ha",
                binding,
                httponly=True,
                secure=cfg.public_url.startswith("https:"),
                samesite="lax",
                max_age=600,
                path="/connections/homeassistant/callback",
            )
            return out

        @app.get("/connections/homeassistant/callback")
        async def callback(request: Request):
            u, _ = await user(request)
            nonce = request.query_params.get("state", "")
            code = request.query_params.get("code", "")
            binding = hashlib.sha256(
                request.cookies.get("hat_ha", "").encode()
            ).hexdigest()
            with state.db() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT * FROM ha_states WHERE hash=? AND owner=? AND expires>?",
                    (hashlib.sha256(nonce.encode()).hexdigest(), u["id"], time.time()),
                ).fetchone()
                if not row or not hmac.compare_digest(binding, row["binding"]):
                    raise HTTPException(
                        400, "Invalid or expired Home Assistant authorization."
                    )
                db.execute("DELETE FROM ha_states WHERE hash=?", (row["hash"],))
            if not code:
                return RedirectResponse("/?connection=failed")
            response = await self.http(
                "POST",
                "/auth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": cfg.public_url + "/",
                },
            )
            if response.status_code != 200:
                return RedirectResponse("/?connection=failed")
            data = response.json()
            if (
                not isinstance(data.get("access_token"), str)
                or not isinstance(data.get("refresh_token"), str)
                or not isinstance(data.get("expires_in"), (int, float))
                or data["expires_in"] <= 0
            ):
                raise HTTPException(
                    502, "Home Assistant returned an invalid token response."
                )
            try:
                identity = await self.identity(data["access_token"])
            except HTTPException:
                await self.http(
                    "POST",
                    "/auth/token",
                    data={"action": "revoke", "token": data["refresh_token"]},
                )
                raise
            old = self.vault.get("ha", u["id"])
            async with self.locks[u["id"]]:
                self.vault.put(
                    "ha",
                    u["id"],
                    {
                        "access_token": data["access_token"],
                        "refresh_token": data["refresh_token"],
                        "expires": time.time() + data["expires_in"],
                        "origin": cfg.ha_url,
                        "client_id": cfg.public_url + "/",
                    },
                )
            state.observation(
                u["id"],
                "homeassistant",
                "connected",
                json.dumps(identity, sort_keys=True),
            )
            state.event(u["id"], "You", "connection.authorized", "homeassistant")
            if old:
                try:
                    await self.http(
                        "POST",
                        "/auth/token",
                        data={"action": "revoke", "token": old["refresh_token"]},
                    )
                except HTTPException:
                    state.event(
                        u["id"],
                        "You",
                        "connection.old_token_cleanup",
                        "homeassistant",
                        "upstream_pending",
                    )
            rid = pending(request)
            out = RedirectResponse(
                "/?connection=verify" + ("&authorize=" + rid if rid else "")
            )
            out.delete_cookie("hat_ha", path="/connections/homeassistant/callback")
            return out

        @app.delete("/api/connections/homeassistant")
        async def disconnect(request: Request):
            u, _ = await user(request, True)
            self.pause(u["id"])
            revoked = True
            async with self.locks[u["id"]]:
                saved = self.vault.get("ha", u["id"])
                self.vault.delete("ha", u["id"])
            state.observation(u["id"], "homeassistant", "needs_attention")
            if saved:
                try:
                    revoked = (
                        await self.http(
                            "POST",
                            "/auth/token",
                            data={"action": "revoke", "token": saved["refresh_token"]},
                        )
                    ).status_code == 200
                except HTTPException:
                    revoked = False
            state.event(
                u["id"],
                "You",
                "connection.disconnected",
                "homeassistant",
                "success" if revoked else "upstream_pending",
            )
            return {"ok": True, "upstream_revoked": revoked}
