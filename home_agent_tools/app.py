"""User-facing control plane and strictly bounded MCP entry point.

ContextForge remains the private authentication/credential broker. This app
never returns its tool/gateway credential objects to the browser.
"""

import hashlib
import base64
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

from .state import State

TOOLS = {
    "homeassistant": {
        "name": "ha-api-status",
        "title": "Home Assistant",
        "mode": "shared",
        "description": "Check the home API. No device control.",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "gitea": {
        "name": "gitea-personal-evaluation-get-me",
        "title": "Gitea",
        "mode": "personal",
        "description": "Read your account and repositories.",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}
REPOS = "gitea-personal-evaluation-list-my-repos"
REPO_SCHEMA = {
    "type": "object",
    "properties": {
        "page": {"type": "integer", "minimum": 1, "maximum": 1000},
        "per_page": {"type": "integer", "minimum": 1, "maximum": 50},
    },
    "additionalProperties": False,
}
CONTEXT_TOOLS = ("home_agent_connection_status", "home_agent_request_connection")
MAX_BODY = 65536


@dataclass
class Settings:
    gateway: str
    public_url: str
    secret: str
    allowed_users: frozenset
    state_path: str
    provider: str = "pocketid"
    oidc_origin: str = ""

    @classmethod
    def env(cls):
        secret = os.environ.get("HAT_SESSION_SECRET", "")
        users = frozenset(
            filter(None, os.environ.get("HAT_ALLOWED_USER_IDS", "").split(","))
        )
        if len(secret) < 32 or not users:
            raise RuntimeError(
                "Set a strong HAT_SESSION_SECRET and explicit HAT_ALLOWED_USER_IDS."
            )
        public = os.environ.get("HAT_PUBLIC_URL", "http://localhost:4444").rstrip("/")
        u = urlsplit(public)
        if u.scheme != "https" and not (
            u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1")
        ):
            raise RuntimeError(
                "Public URL requires HTTPS except for a localhost tunnel."
            )
        return cls(
            os.environ.get("HAT_GATEWAY_URL", "http://gateway:4444").rstrip("/"),
            public,
            secret,
            users,
            os.environ.get("HAT_STATE_PATH", "/data/hat.sqlite"),
            oidc_origin=os.environ.get("HAT_OIDC_ORIGIN", ""),
        )


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Enrollment(StrictModel):
    name: str = Field(min_length=1, max_length=60, pattern=r"^[\w .()\-]+$")
    services: list[str] = Field(min_length=1, max_length=2)
    days: int = Field(default=7, ge=1, le=30)


def fingerprint(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_app(settings=None, transport=None):
    cfg = settings or Settings.env()
    app = FastAPI(
        title="Home Agent Tools", docs_url=None, redoc_url=None, openapi_url=None
    )
    state = State(cfg.state_path)
    app.state.store = state
    app.state.config = cfg
    static = Path(__file__).parent / "static"

    async def broker(method, path, *, token=None, body=None, cookies=None):
        # One fresh client per request prevents cookie jars crossing users.
        headers = {
            "Accept": "application/json",
            "Host": urlsplit(cfg.public_url).netloc,
        }
        if token:
            headers["Authorization"] = "Bearer " + token
        if cookies:
            headers["Cookie"] = cookies
        async with httpx.AsyncClient(
            base_url=cfg.gateway,
            transport=transport,
            timeout=30,
            follow_redirects=False,
        ) as client:
            try:
                response = await client.request(
                    method, path, headers=headers, json=body
                )
            except httpx.HTTPError:
                raise HTTPException(
                    502, "Connection engine unavailable. Try again shortly."
                ) from None
        return response

    def csrf(request):
        return hmac.new(
            cfg.secret.encode(),
            request.cookies.get("jwt_token", "").encode(),
            hashlib.sha256,
        ).hexdigest()

    async def user(request, write=False):
        token = request.cookies.get("jwt_token")
        if not token:
            raise HTTPException(401, "Sign in with Pocket ID.")
        response = await broker("GET", "/auth/email/me", token=token)
        if response.status_code != 200:
            raise HTTPException(401, "Your session expired. Sign in again.")
        # The broker has verified the signature. Reject runtime credentials at
        # the browser control plane even if someone places one in a cookie.
        try:
            claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "==="))
        except (ValueError, IndexError):
            raise HTTPException(401, "Invalid session.") from None
        if claims.get("token_use") != "session":
            raise HTTPException(401, "A browser session is required.")
        u = response.json()
        # /auth/email/me omits the immutable UUID. Its successful validation
        # authenticates this exact JWT; use its verified subject, never email.
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise HTTPException(401, "The session has no user identity.")
        u["id"] = subject
        if not u.get("is_active", False) or u.get("id") not in cfg.allowed_users:
            raise HTTPException(
                403, "This account has not been enabled for this installation."
            )
        if write:
            if request.headers.get(
                "origin"
            ) != cfg.public_url or not hmac.compare_digest(
                request.headers.get("x-hat-csrf", ""), csrf(request)
            ):
                raise HTTPException(
                    403, "Request verification failed. Reload the page."
                )
        return u, token

    def checked(response):
        if response.status_code >= 400:
            # Never pass backend diagnostics/credentials through to clients.
            raise HTTPException(
                (
                    response.status_code
                    if response.status_code in (401, 403, 404, 409, 429)
                    else 502
                ),
                "The connection engine could not complete this action.",
            )
        return response.json() if response.content else {}

    async def inventory(u, token):
        result = {}
        for kind in ("tools", "gateways", "servers"):
            values = checked(await broker("GET", "/" + kind, token=token))
            result[kind] = [
                v
                for v in values
                if v.get("ownerEmail") == u["email"]
                and v.get("visibility") == "private"
                and v.get("teamId")
            ]
        return result

    async def context(u, token):
        data = await inventory(u, token)
        tool_names = {t["name"] for t in data["tools"]}
        servers = [
            s for s in data["servers"] if s.get("name") == "Home Agent Tools Evaluation"
        ]
        if not servers:
            raise HTTPException(
                409, "An administrator must provision your private workspace first."
            )
        return data, servers[0], tool_names

    async def issue(u, token, name, days):
        _, server, _ = await context(u, token)
        return checked(
            await broker(
                "POST",
                "/tokens",
                token=token,
                body={
                    "name": name,
                    "expires_in_days": days,
                    "team_id": server["teamId"],
                    "scope": {
                        "server_id": server["id"],
                        "permissions": ["tools.read", "tools.execute", "servers.read"],
                    },
                    "tags": ["home-agent-tools"],
                },
            )
        )

    async def rpc(token, method, params):
        return checked(
            await broker(
                "POST",
                "/rpc",
                token=token,
                body={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            )
        )

    def parse_identity(result):
        for item in result.get("content", []):
            if item.get("type") == "text":
                try:
                    value = json.loads(item["text"])
                    if (
                        isinstance(value, dict)
                        and isinstance(value.get("login"), str)
                        and value.get("id") is not None
                    ):
                        return {"id": str(value["id"]), "login": value["login"][:100]}
                except (ValueError, KeyError):
                    pass
        return None

    def valid_home_status(result):
        for item in result.get("content", []):
            if item.get("type") == "text":
                try:
                    if json.loads(item.get("text", "")) == {"message": "API running."}:
                        return True
                except ValueError:
                    pass
        return False

    def auth_response(response, destination=None):
        out = RedirectResponse(
            destination or response.headers.get("location", cfg.public_url),
            status_code=302,
        )
        for cookie in response.headers.get_list("set-cookie"):
            out.headers.append("set-cookie", cookie)
        return out

    @app.middleware("http")
    async def guard(request, call_next):
        expected = urlsplit(cfg.public_url).netloc
        if request.headers.get("host") != expected:
            return JSONResponse({"detail": "Unrecognized host."}, status_code=400)
        origin = request.headers.get("origin")
        if origin and origin != cfg.public_url:
            return JSONResponse({"detail": "Origin not permitted."}, status_code=403)
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > MAX_BODY):
            return JSONResponse({"detail": "Request too large."}, status_code=413)
        # Limit chunked bodies as well; do not trust Content-Length alone.
        if request.method in ("POST", "PUT", "PATCH"):
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > MAX_BODY:
                    return JSONResponse(
                        {"detail": "Request too large."}, status_code=413
                    )
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.get("/health")
    async def health():
        return {"status": "ok", "application": "Home Agent Tools", "version": "0.1.0"}

    @app.get("/login")
    async def login():
        from urllib.parse import urlencode

        path = (
            "/auth/sso/login/"
            + cfg.provider
            + "?"
            + urlencode(
                {"redirect_uri": cfg.public_url + "/auth/sso/callback/" + cfg.provider}
            )
        )
        response = await broker("GET", path)
        data = checked(response)
        location = data.get("authorization_url", "")
        parsed = urlsplit(location)
        if parsed.scheme != "https" or (
            cfg.oidc_origin and f"{parsed.scheme}://{parsed.netloc}" != cfg.oidc_origin
        ):
            raise HTTPException(502, "Identity provider configuration is invalid.")
        return auth_response(response, location)

    @app.get("/auth/sso/callback/{provider}")
    async def sso_callback(provider: str, request: Request):
        if provider != cfg.provider:
            raise HTTPException(404)
        response = await broker(
            "GET",
            request.url.path + "?" + request.url.query,
            cookies=request.headers.get("cookie", ""),
        )
        location = response.headers.get("location", "")
        return auth_response(
            response,
            (
                "/?login=failed"
                if "error=" in location or response.status_code >= 400
                else "/"
            ),
        )

    @app.post("/api/logout")
    async def logout(request: Request):
        _, token = await user(request, True)
        await broker("POST", "/auth/logout", token=token)
        response = JSONResponse({"ok": True})
        response.delete_cookie("jwt_token", path="/")
        response.delete_cookie("session_id", path="/")
        return response

    @app.get("/api/bootstrap")
    async def bootstrap(request: Request):
        u, token = await user(request)
        data = await inventory(u, token)
        with state.db() as db:
            observations = {
                r["service"]: dict(r)
                for r in db.execute(
                    "SELECT * FROM observations WHERE owner=?", (u["id"],)
                )
            }
            agents = [
                {
                    k: r[k]
                    for k in (
                        "id",
                        "name",
                        "services",
                        "expires",
                        "active",
                        "created",
                        "last_used",
                    )
                }
                for r in db.execute(
                    "SELECT * FROM agents WHERE owner=? ORDER BY created DESC",
                    (u["id"],),
                )
            ]
            events = [
                dict(r)
                for r in db.execute(
                    "SELECT actor,action,service,outcome,at FROM events WHERE owner=? ORDER BY at DESC LIMIT 50",
                    (u["id"],),
                )
            ]
            requests = [
                dict(r)
                for r in db.execute(
                    "SELECT id,agent,service,status,created,expires FROM requests WHERE owner=? ORDER BY created DESC LIMIT 30",
                    (u["id"],),
                )
            ]
        names = {t["name"] for t in data["tools"]}
        connections = []
        for key, definition in TOOLS.items():
            observation = observations.get(key, {})
            connections.append(
                {
                    "id": key,
                    "name": definition["title"],
                    "mode": definition["mode"],
                    "description": definition["description"],
                    "configured": definition["name"] in names,
                    "status": observation.get("status", "not_checked"),
                    "identity": observation.get("identity"),
                    "checked": observation.get("checked"),
                    "tools": [definition["name"]] + ([REPOS] if key == "gitea" else []),
                    "upstream_permissions": "Not fully verified",
                    "requested_scopes": (
                        ["read:user", "read:repository"] if key == "gitea" else []
                    ),
                }
            )
        for a in agents:
            a["services"] = json.loads(a["services"])
        return {
            "user": {
                "id": u["id"],
                "name": u.get("full_name") or "Home operator",
                "admin": bool(u.get("is_admin")),
            },
            "csrf": csrf(request),
            "connections": connections,
            "agents": agents,
            "events": events,
            "requests": requests,
            "mcp_url": cfg.public_url + "/mcp",
            "limitations": [
                "Single-operator preview: additional users require explicit provisioning.",
                "Agent authentication uses individually revocable gateway tokens.",
                "Only the listed read tools are available.",
            ],
        }

    @app.post("/api/connections/{service}/test")
    async def test_connection(service: str, request: Request):
        u, token = await user(request, True)
        if service not in TOOLS:
            raise HTTPException(404)
        data, _, names = await context(u, token)
        if service == "gitea" and TOOLS[service]["name"] not in names:
            gateways = [
                g
                for g in data["gateways"]
                if g.get("name") == "gitea-personal-evaluation"
            ]
            if gateways:
                checked(
                    await broker(
                        "POST", "/oauth/fetch-tools/" + gateways[0]["id"], token=token
                    )
                )
        temporary = await issue(u, token, "hat-check-" + uuid.uuid4().hex[:12], 1)
        try:
            response = await rpc(
                temporary["access_token"],
                "tools/call",
                {"name": TOOLS[service]["name"], "arguments": {}},
            )
            result = response.get("result", {})
            if (
                response.get("error")
                or result.get("isError")
                or not result.get("content")
            ):
                state.observation(u["id"], service, "needs_attention")
                state.event(u["id"], "You", "connection.check", service, "failed")
                return {
                    "ok": False,
                    "message": "Connection needs attention. Reconnect and try again.",
                }
            identity = parse_identity(result) if service == "gitea" else None
            if service == "gitea" and not identity:
                raise HTTPException(
                    502, "The service did not return a verifiable account."
                )
            if service == "homeassistant" and not valid_home_status(result):
                state.observation(u["id"], service, "needs_attention")
                raise HTTPException(
                    502,
                    "The service did not return the expected Home Assistant status.",
                )
            label = json.dumps(identity, sort_keys=True) if identity else None
            changed = state.observation(u["id"], service, "connected", label)
            state.event(u["id"], "You", "connection.check", service)
            return {
                "ok": True,
                "identity": identity,
                "identity_changed": changed,
                "message": (
                    "Connected account changed. Existing agents were disabled; enroll them again."
                    if changed
                    else "Connection verified."
                ),
            }
        finally:
            await broker("DELETE", "/tokens/" + temporary["token"]["id"], token=token)

    @app.post("/api/connections/gitea/connect")
    async def connect_gitea(request: Request):
        u, token = await user(request, True)
        data = await inventory(u, token)
        gateways = [
            g for g in data["gateways"] if g.get("name") == "gitea-personal-evaluation"
        ]
        if not gateways:
            raise HTTPException(
                409, "An administrator must provision this service for you."
            )
        response = await broker(
            "GET", "/oauth/authorize/" + gateways[0]["id"], token=token
        )
        if response.status_code not in (302, 303, 307):
            checked(response)
            raise HTTPException(502, "Unable to start authorization.")
        # Pause grants before changing the upstream account, not after a later
        # verification click. A reconnect must never silently inherit grants.
        with state.db() as db:
            for row in db.execute(
                "SELECT id,services FROM agents WHERE owner=? AND active=1", (u["id"],)
            ).fetchall():
                if "gitea" in json.loads(row["services"]):
                    db.execute("UPDATE agents SET active=0 WHERE id=?", (row["id"],))
        state.observation(u["id"], "gitea", "not_checked")
        state.event(u["id"], "You", "connection.reconnecting", "gitea")
        out = JSONResponse({"url": response.headers["location"]})
        for cookie in response.headers.get_list("set-cookie"):
            out.headers.append("set-cookie", cookie)
        return out

    @app.get("/oauth/callback")
    async def oauth_callback(request: Request):
        await user(request)
        response = await broker(
            "GET",
            "/oauth/callback?" + request.url.query,
            cookies=request.headers.get("cookie", ""),
        )
        successful = (
            response.status_code == 200
            and "OAuth Authorization Successful" in response.text
        )
        return RedirectResponse(
            "/?connection=" + ("verify" if successful else "failed")
        )

    @app.post("/api/agents")
    async def enroll(body: Enrollment, request: Request):
        u, token = await user(request, True)
        services = sorted(set(body.services))
        if any(s not in TOOLS for s in services):
            raise HTTPException(422, "Choose supported services.")
        _, _, names = await context(u, token)
        if any(TOOLS[s]["name"] not in names for s in services):
            raise HTTPException(
                409, "Configure and verify each selected connection first."
            )
        with state.db() as db:
            connected = {
                r["service"]
                for r in db.execute(
                    "SELECT service FROM observations WHERE owner=? AND status='connected'",
                    (u["id"],),
                )
            }
        if not set(services) <= connected:
            raise HTTPException(
                409, "Run a connection check before granting agent access."
            )
        issued = await issue(
            u, token, "hat-" + body.name + "-" + uuid.uuid4().hex[:6], body.days
        )
        agent_id = uuid.uuid4().hex
        try:
            with state.db() as db:
                db.execute(
                    "INSERT INTO agents VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        agent_id,
                        u["id"],
                        body.name,
                        fingerprint(issued["access_token"]),
                        issued["token"]["id"],
                        json.dumps(services),
                        time.time() + body.days * 86400,
                        1,
                        time.time(),
                        None,
                    ),
                )
        except Exception:
            await broker("DELETE", "/tokens/" + issued["token"]["id"], token=token)
            raise
        state.event(u["id"], body.name, "agent.enrolled")
        return {
            "id": agent_id,
            "token": issued["access_token"],
            "url": cfg.public_url + "/mcp",
            "message": "Copy this token now. It will not be shown again.",
        }

    @app.delete("/api/agents/{agent_id}")
    async def revoke(agent_id: str, request: Request):
        u, token = await user(request, True)
        with state.db() as db:
            row = db.execute(
                "SELECT * FROM agents WHERE id=? AND owner=?", (agent_id, u["id"])
            ).fetchone()
            if not row:
                raise HTTPException(404)
            db.execute("UPDATE agents SET active=0 WHERE id=?", (agent_id,))
        # Local revocation commits first and remains effective if the broker is down.
        try:
            upstream = await broker("DELETE", "/tokens/" + row["token_id"], token=token)
            revoked = upstream.status_code in (200, 204, 404)
        except HTTPException:
            revoked = False
        state.event(
            u["id"],
            row["name"],
            "agent.revoked",
            outcome="success" if revoked else "upstream_pending",
        )
        return {"ok": True, "upstream_revoked": revoked}

    @app.post("/api/requests/{request_id}/resolve")
    async def resolve(request_id: str, request: Request):
        u, _ = await user(request, True)
        with state.db() as db:
            row = db.execute(
                "SELECT * FROM requests WHERE id=? AND owner=?", (request_id, u["id"])
            ).fetchone()
            if not row:
                raise HTTPException(404)
            if row["expires"] < time.time():
                raise HTTPException(410, "This request expired.")
            obs = db.execute(
                "SELECT checked FROM observations WHERE owner=? AND service=? AND status='connected'",
                (u["id"], row["service"]),
            ).fetchone()
            if not obs or obs["checked"] < row["created"]:
                raise HTTPException(
                    409, "Verify the connection before resolving this request."
                )
            db.execute(
                "UPDATE requests SET status='resolved' WHERE id=?", (request_id,)
            )
        state.event(u["id"], "You", "request.resolved", row["service"])
        return {"ok": True}

    def rpc_error(code, message, request_id=None):
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": message},
            }
        )

    async def agent(request):
        value = request.headers.get("authorization", "")
        if not value.startswith("Bearer ") or len(value) > 16384:
            raise HTTPException(401, "Use an enrolled agent token.")
        token = value[7:]
        with state.db() as db:
            row = db.execute(
                "SELECT * FROM agents WHERE fingerprint=?", (fingerprint(token),)
            ).fetchone()
        if (
            not row
            or not row["active"]
            or row["expires"] <= time.time()
            or row["owner"] not in cfg.allowed_users
        ):
            raise HTTPException(401, "Agent access expired or was revoked.")
        # Check broker revocation/account status on every request, including discovery.
        valid = await rpc(token, "tools/list", {})
        if "error" in valid:
            raise HTTPException(403, "Gateway access denied.")
        return dict(row), token, valid.get("result", {}).get("tools", [])

    @app.api_route("/mcp", methods=["GET", "DELETE"])
    async def mcp_no_stream(request: Request):
        await agent(request)
        return Response(status_code=405, headers={"Allow": "POST"})

    @app.post("/mcp")
    async def mcp(request: Request):
        enrollment, token, available = await agent(request)
        try:
            msg = await request.json()
        except ValueError:
            return rpc_error(-32700, "Invalid JSON.")
        if (
            not isinstance(msg, dict)
            or msg.get("jsonrpc") != "2.0"
            or not isinstance(msg.get("method"), str)
        ):
            return rpc_error(-32600, "A single JSON-RPC message is required.")
        request_id = msg.get("id")
        method = msg["method"]
        params = msg.get("params", {})
        if request_id is not None and (
            isinstance(request_id, bool) or not isinstance(request_id, (str, int))
        ):
            return rpc_error(-32600, "Invalid request identifier.")
        if not isinstance(params, dict):
            return rpc_error(-32602, "Parameters must be an object.", request_id)
        version = request.headers.get("mcp-protocol-version")
        if version and version not in ("2025-03-26", "2025-06-18", "2025-11-25"):
            return JSONResponse(
                {"detail": "Unsupported protocol version."}, status_code=400
            )
        if "id" not in msg:
            return Response(
                status_code=202 if method.startswith("notifications/") else 400
            )
        services = json.loads(enrollment["services"])
        allowed = {TOOLS[s]["name"] for s in services}
        if "gitea" in services:
            allowed.add(REPOS)
        available_names = {t["name"] for t in available}
        if method == "initialize":
            proposed = params.get("protocolVersion", "2025-06-18")
            result = {
                "protocolVersion": (
                    proposed
                    if proposed in ("2025-03-26", "2025-06-18", "2025-11-25")
                    else "2025-06-18"
                ),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "Home Agent Tools", "version": "0.1.0"},
                "instructions": "Use the granted read tools. If a connection needs attention, call home_agent_request_connection and give the signed-in owner its link. Never ask for upstream credentials in chat.",
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            tools = []
            for t in available:
                if t["name"] in allowed:
                    schema = (
                        REPO_SCHEMA
                        if t["name"] == REPOS
                        else {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        }
                    )
                    tools.append(
                        {
                            "name": t["name"],
                            "description": t.get("description", ""),
                            "inputSchema": schema,
                            "annotations": {
                                "readOnlyHint": True,
                                "destructiveHint": False,
                            },
                        }
                    )
            for name in CONTEXT_TOOLS:
                tools.append(
                    {
                        "name": name,
                        "description": (
                            "Read connection status."
                            if name.endswith("status")
                            else "Create a reconnect request for the owner. Returns a sign-in link; never grants access."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "service": {"type": "string", "enum": services}
                            },
                            "required": ["service"],
                            "additionalProperties": False,
                        },
                        "annotations": {
                            "readOnlyHint": name.endswith("status"),
                            "destructiveHint": False,
                        },
                    }
                )
            result = {"tools": tools}
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(name, str):
                return rpc_error(-32602, "A tool name is required.", request_id)
            service = next(
                (
                    s
                    for s in services
                    if name == TOOLS[s]["name"] or (s == "gitea" and name == REPOS)
                ),
                None,
            )
            if name in CONTEXT_TOOLS:
                schema = {
                    "type": "object",
                    "properties": {"service": {"enum": services}},
                    "required": ["service"],
                    "additionalProperties": False,
                }
            elif name in allowed and name in available_names:
                schema = REPO_SCHEMA if name == REPOS else TOOLS[service]["schema"]
            else:
                state.event(
                    enrollment["owner"],
                    enrollment["name"],
                    "tool.denied",
                    outcome="denied",
                )
                return rpc_error(
                    -32601, "Tool is not granted to this agent.", request_id
                )
            if not Draft202012Validator(schema).is_valid(arguments):
                state.event(
                    enrollment["owner"],
                    enrollment["name"],
                    "tool.invalid",
                    service,
                    "denied",
                )
                return rpc_error(
                    -32602,
                    "Arguments do not match the permitted tool schema.",
                    request_id,
                )
            if name in CONTEXT_TOOLS:
                service = arguments["service"]
                if name.endswith("status"):
                    with state.db() as db:
                        observation = db.execute(
                            "SELECT status,checked FROM observations WHERE owner=? AND service=?",
                            (enrollment["owner"], service),
                        ).fetchone()
                    payload = (
                        dict(observation) if observation else {"status": "not_checked"}
                    )
                else:
                    rid = state.request(
                        enrollment["owner"], enrollment["name"], service
                    )
                    payload = {
                        "status": "owner_action_required",
                        "url": cfg.public_url + "/?request=" + rid,
                        "expires_in_seconds": 86400,
                    }
                    state.event(
                        enrollment["owner"],
                        enrollment["name"],
                        "connection.requested",
                        service,
                    )
                result = {"content": [{"type": "text", "text": json.dumps(payload)}]}
            else:
                # Recheck revocation immediately before executing the upstream call.
                with state.db() as db:
                    active = db.execute(
                        "SELECT active FROM agents WHERE id=?", (enrollment["id"],)
                    ).fetchone()["active"]
                if not active:
                    raise HTTPException(401, "Agent access was revoked.")
                upstream = await rpc(
                    token, "tools/call", {"name": name, "arguments": arguments}
                )
                if "error" in upstream:
                    state.event(
                        enrollment["owner"],
                        enrollment["name"],
                        "tool.call",
                        service,
                        "failed",
                    )
                    return rpc_error(
                        -32000,
                        "Connection unavailable. Ask the owner to check or reconnect it.",
                        request_id,
                    )
                result = upstream.get("result", {})
                state.event(
                    enrollment["owner"],
                    enrollment["name"],
                    "tool.call",
                    service,
                    "failed" if result.get("isError") else "success",
                )
                if result.get("isError"):
                    state.observation(enrollment["owner"], service, "needs_attention")
            with state.db() as db:
                db.execute(
                    "UPDATE agents SET last_used=? WHERE id=?",
                    (time.time(), enrollment["id"]),
                )
        else:
            return rpc_error(-32601, "Method not supported.", request_id)
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @app.get("/")
    @app.get("/admin")
    @app.get("/admin/")
    @app.get("/admin/login")
    async def index():
        return FileResponse(static / "index.html")

    app.mount("/static", StaticFiles(directory=static), name="static")
    return app
