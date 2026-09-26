"""PKCE authorization for native clients; Pocket ID authenticates the owner.

No provider tokens or dashboard sessions are issued to clients. Refresh tokens
rotate and can never extend the user's fixed approval deadline.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from collections import defaultdict, deque
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

SCOPES = {"gitea:read": "gitea", "homeassistant:read": "homeassistant"}
ACCESS_SECONDS = 600


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def challenge(verifier):
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )


def loopback(uri):
    try:
        u = urlsplit(uri)
        return (
            u.scheme == "http"
            and u.hostname in ("127.0.0.1", "[::1]", "::1")
            and not u.username
            and not u.password
            and not u.fragment
            and not u.query
            and (u.path == "/callback" or u.path.startswith("/callback/"))
            and u.port != 0
        )
    except ValueError:
        return False


def redirect_matches(uri, registered):
    if not loopback(uri):
        return False
    a, b = urlsplit(uri), urlsplit(registered)
    return (
        a.scheme == b.scheme
        and a.hostname == b.hostname
        and a.path == b.path
        and (b.port is None or a.port == b.port)
    )


class Registration(BaseModel):
    model_config = ConfigDict(extra="ignore")
    client_name: str = Field(
        default="MCP client", min_length=1, max_length=80, pattern=r"^[\w .()\-]+$"
    )
    redirect_uris: list[str] = Field(min_length=1, max_length=3)
    token_endpoint_auth_method: str = "none"
    grant_types: list[str] = ["authorization_code", "refresh_token"]
    response_types: list[str] = ["code"]


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve: bool
    services: list[str] = Field(default_factory=list, max_length=2)
    days: int = 90


class Authorization:
    def __init__(self, app, cfg, state, vault, user, enroll):
        self.cfg, self.state, self.vault = cfg, state, vault
        self.buckets = defaultdict(deque)
        self.mount(app, user, enroll)

    def limit(self, request):
        key = request.client.host if request.client else "unknown"
        now = time.time()
        bucket = self.buckets[key]
        while bucket and bucket[0] < now - 60:
            bucket.popleft()
        if len(bucket) >= 120:
            raise HTTPException(
                429, "Too many authorization requests. Try again shortly."
            )
        bucket.append(now)
        if len(self.buckets) > 1024:
            self.buckets = defaultdict(
                deque, {k: v for k, v in self.buckets.items() if v and v[-1] > now - 60}
            )

    def binding(self, rid):
        return (
            rid
            + "."
            + hmac.new(
                self.cfg.secret.encode(),
                ("authorization:" + rid).encode(),
                hashlib.sha256,
            ).hexdigest()
        )

    def pending(self, request):
        value = request.cookies.get("hat_authorization", "")
        rid = value.split(".")[0]
        if re.fullmatch(r"[a-f0-9]{48}", rid) and hmac.compare_digest(
            value, self.binding(rid)
        ):
            with self.state.db() as db:
                row = db.execute(
                    "SELECT * FROM authorizations WHERE id=? AND expires>? AND status='pending'",
                    (rid, time.time()),
                ).fetchone()
            if row:
                return rid
        return None

    def require_binding(self, request, rid):
        if not hmac.compare_digest(
            request.cookies.get("hat_authorization", ""), self.binding(rid)
        ):
            raise HTTPException(
                403, "Open the authorization link in this browser again."
            )

    def token_response(self, db, agent, client):
        access, refresh = secrets.token_urlsafe(40), secrets.token_urlsafe(48)
        now = time.time()
        seconds = min(ACCESS_SECONDS, max(0, int(agent["expires"] - now)))
        if not seconds:
            raise HTTPException(400, "Authorization expired.")
        db.execute(
            "INSERT INTO access_tokens VALUES (?,?,?)",
            (digest(access), agent["id"], now + seconds),
        )
        db.execute(
            "INSERT INTO refresh_tokens VALUES (?,?,?,0)",
            (digest(refresh), agent["id"], client),
        )
        scope = " ".join(
            s for s, v in SCOPES.items() if v in json.loads(agent["services"])
        )
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "Bearer",
            "expires_in": seconds,
            "scope": scope,
            "authorization_expires_at": agent["expires"],
            "agent_id": agent["id"],
        }

    def mount(self, app, user, enroll):
        cfg, state = self.cfg, self.state

        @app.get("/.well-known/oauth-protected-resource")
        @app.get("/.well-known/oauth-protected-resource/mcp")
        async def resource_metadata():
            return {
                "resource": cfg.public_url + "/mcp",
                "authorization_servers": [cfg.public_url],
                "scopes_supported": list(SCOPES),
                "bearer_methods_supported": ["header"],
            }

        @app.get("/.well-known/oauth-authorization-server")
        async def metadata():
            return {
                "issuer": cfg.public_url,
                "authorization_endpoint": cfg.public_url + "/oauth/authorize",
                "token_endpoint": cfg.public_url + "/oauth/token",
                "registration_endpoint": cfg.public_url + "/oauth/register",
                "revocation_endpoint": cfg.public_url + "/oauth/revoke",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "scopes_supported": list(SCOPES),
                "token_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
                "authorization_response_iss_parameter_supported": True,
            }

        @app.post("/oauth/register", status_code=201)
        async def register(body: Registration, request: Request):
            self.limit(request)
            if (
                body.token_endpoint_auth_method != "none"
                or body.response_types != ["code"]
                or set(body.grant_types) - {"authorization_code", "refresh_token"}
                or not all(loopback(u) for u in body.redirect_uris)
            ):
                raise HTTPException(
                    400,
                    "This release registers native clients with loopback callbacks only.",
                )
            client_id = secrets.token_urlsafe(32)
            with state.db() as db:
                # Bounded registry; registered native clients expire after 120 days.
                db.execute(
                    "DELETE FROM oauth_clients WHERE created<?",
                    (time.time() - 120 * 86400,),
                )
                if (
                    db.execute("SELECT COUNT(*) FROM oauth_clients").fetchone()[0]
                    >= 1000
                ):
                    raise HTTPException(429, "Client registry is full.")
                db.execute(
                    "INSERT INTO oauth_clients VALUES (?,?,?,?)",
                    (
                        client_id,
                        body.client_name,
                        json.dumps(body.redirect_uris),
                        time.time(),
                    ),
                )
            return {
                "client_id": client_id,
                "client_name": body.client_name,
                "redirect_uris": body.redirect_uris,
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            }

        @app.get("/oauth/authorize")
        async def authorize(request: Request):
            self.limit(request)
            q = dict(request.query_params)
            if len(q) != len(request.query_params.multi_items()):
                raise HTTPException(400, "Duplicate authorization parameter.")
            client = q.get("client_id", "")
            uri = q.get("redirect_uri", "")
            pkce = q.get("code_challenge", "")
            with state.db() as db:
                row = db.execute(
                    "SELECT * FROM oauth_clients WHERE id=?", (client,)
                ).fetchone()
            if not row or not any(
                redirect_matches(uri, r) for r in json.loads(row["redirects"])
            ):
                raise HTTPException(400, "Unregistered client or callback.")
            scopes = q.get("scope", "").split() or list(SCOPES)
            if (
                q.get("response_type") != "code"
                or q.get("code_challenge_method") != "S256"
                or not re.fullmatch(r"[A-Za-z0-9_-]{43}", pkce)
                or set(scopes) - SCOPES.keys()
                or q.get("resource") != cfg.public_url + "/mcp"
                or not 1 <= len(q.get("state", "")) <= 512
            ):
                raise HTTPException(
                    400,
                    "Use authorization code, S256 PKCE, state, valid scopes and the exact MCP resource.",
                )
            days = q.get("days", "90")
            if days not in ("30", "90"):
                raise HTTPException(400, "Choose 30 or 90 days.")
            rid = secrets.token_hex(24)
            with state.db() as db:
                db.execute("DELETE FROM authorizations WHERE expires<?", (time.time(),))
                if (
                    db.execute("SELECT COUNT(*) FROM authorizations").fetchone()[0]
                    >= 1000
                ):
                    raise HTTPException(429, "Too many pending authorizations.")
                db.execute(
                    "INSERT INTO authorizations VALUES (?,?,?,?,?,?,?,NULL,?,?,NULL,NULL)",
                    (
                        rid,
                        client,
                        uri,
                        q["state"],
                        pkce,
                        json.dumps(sorted({SCOPES[s] for s in scopes})),
                        int(days),
                        "pending",
                        time.time() + 600,
                    ),
                )
            out = RedirectResponse("/?authorize=" + rid, status_code=302)
            out.set_cookie(
                "hat_authorization",
                self.binding(rid),
                httponly=True,
                secure=cfg.public_url.startswith("https:"),
                samesite="lax",
                max_age=600,
                path="/",
            )
            return out

        @app.get("/api/authorizations/{rid}")
        async def review(rid: str, request: Request):
            u, _ = await user(request)
            self.require_binding(request, rid)
            with state.db() as db:
                row = db.execute(
                    "SELECT a.*,c.name AS client_name FROM authorizations a JOIN oauth_clients c ON c.id=a.client WHERE a.id=? AND a.status='pending' AND a.expires>?",
                    (rid, time.time()),
                ).fetchone()
                if not row:
                    raise HTTPException(
                        410, "This authorization request expired or was already used."
                    )
                if row["owner"] and row["owner"] != u["id"]:
                    raise HTTPException(403, "This request belongs to another account.")
                db.execute(
                    "UPDATE authorizations SET owner=? WHERE id=?", (u["id"], rid)
                )
            return {
                "id": rid,
                "client_name": row["client_name"],
                "redirect_uri": row["redirect"],
                "services": json.loads(row["services"]),
                "days": row["days"],
                "verification_code": digest(row["challenge"])[:8].upper(),
                "expires": row["expires"],
            }

        @app.post("/api/authorizations/{rid}")
        async def approve(rid: str, body: Approval, request: Request):
            u, session = await user(request, True)
            self.require_binding(request, rid)
            with state.db() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT a.*,c.name AS client_name FROM authorizations a JOIN oauth_clients c ON c.id=a.client WHERE a.id=? AND a.status='pending' AND a.expires>?",
                    (rid, time.time()),
                ).fetchone()
                if not row:
                    raise HTTPException(
                        410, "This request expired or was already used."
                    )
                if row["owner"] != u["id"]:
                    raise HTTPException(
                        403, "Review this request using the same account first."
                    )
                if body.approve and (
                    not body.services
                    or not set(body.services) <= set(json.loads(row["services"]))
                    or body.days not in (30, 90)
                    or body.days > row["days"]
                ):
                    raise HTTPException(
                        400, "Approval cannot expand the requested access or lifetime."
                    )
                db.execute(
                    "UPDATE authorizations SET status='approving' WHERE id=?", (rid,)
                )
            callback = {"state": row["state"], "iss": cfg.public_url}
            if body.approve:
                try:
                    grant = await enroll(
                        u, session, row["client_name"][:60], body.services, body.days
                    )
                except Exception:
                    with state.db() as db:
                        db.execute(
                            "UPDATE authorizations SET status='pending' WHERE id=?",
                            (rid,),
                        )
                    raise
                code = secrets.token_urlsafe(40)
                with state.db() as db:
                    db.execute(
                        "UPDATE authorizations SET status='approved',code_hash=?,agent=?,expires=? WHERE id=?",
                        (digest(code), grant["id"], time.time() + 120, rid),
                    )
                callback["code"] = code
            else:
                with state.db() as db:
                    db.execute(
                        "UPDATE authorizations SET status='denied' WHERE id=?", (rid,)
                    )
                callback["error"] = "access_denied"
            response = JSONResponse(
                {"redirect_url": row["redirect"] + "?" + urlencode(callback)}
            )
            response.delete_cookie("hat_authorization", path="/")
            return response

        async def form(request):
            self.limit(request)
            if (
                request.headers.get("content-type", "").split(";")[0]
                != "application/x-www-form-urlencoded"
            ):
                raise HTTPException(400, "Use form-encoded OAuth requests.")
            try:
                fields = parse_qsl(
                    (await request.body()).decode(),
                    keep_blank_values=True,
                    max_num_fields=20,
                )
            except (ValueError, UnicodeError):
                raise HTTPException(400, "Invalid form.") from None
            values = dict(fields)
            if len(values) != len(fields):
                raise HTTPException(400, "Duplicate form parameter.")
            return values

        @app.post("/oauth/token")
        async def exchange(request: Request):
            q = await form(request)
            if q.get("resource") != cfg.public_url + "/mcp":
                return JSONResponse({"error": "invalid_target"}, status_code=400)
            now = time.time()
            client = q.get("client_id", "")
            result = None
            replay = None
            with state.db() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM access_tokens WHERE expires<?", (now,))
                db.execute(
                    "DELETE FROM refresh_tokens WHERE agent IN (SELECT id FROM agents WHERE expires<? OR active=0)",
                    (now,),
                )
                if q.get("grant_type") == "authorization_code":
                    row = db.execute(
                        "SELECT * FROM authorizations WHERE code_hash=? AND client=? AND status='approved' AND expires>?",
                        (digest(q.get("code", "")), client, now),
                    ).fetchone()
                    verifier = q.get("code_verifier", "")
                    if (
                        row
                        and row["redirect"] == q.get("redirect_uri")
                        and re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)
                        and hmac.compare_digest(challenge(verifier), row["challenge"])
                    ):
                        db.execute(
                            "UPDATE authorizations SET status='used' WHERE id=?",
                            (row["id"],),
                        )
                    else:
                        row = None
                elif q.get("grant_type") == "refresh_token":
                    row = db.execute(
                        "SELECT * FROM refresh_tokens WHERE hash=? AND client=?",
                        (digest(q.get("refresh_token", "")), client),
                    ).fetchone()
                    if row and row["consumed"]:
                        replay = db.execute(
                            "SELECT owner,name FROM agents WHERE id=?", (row["agent"],)
                        ).fetchone()
                        db.execute(
                            "UPDATE agents SET active=0 WHERE id=?", (row["agent"],)
                        )
                        row = None
                    elif row:
                        db.execute(
                            "UPDATE refresh_tokens SET consumed=1 WHERE hash=?",
                            (row["hash"],),
                        )
                else:
                    return JSONResponse(
                        {"error": "unsupported_grant_type"}, status_code=400
                    )
                if row:
                    agent = db.execute(
                        "SELECT * FROM agents WHERE id=?", (row["agent"],)
                    ).fetchone()
                    if (
                        agent
                        and agent["active"]
                        and agent["expires"] > now
                        and agent["owner"] in cfg.allowed_users
                    ):
                        result = self.token_response(db, agent, client)
            if replay:
                state.event(
                    replay["owner"],
                    replay["name"],
                    "agent.refresh_replay",
                    outcome="revoked",
                )
            if not result:
                return JSONResponse(
                    {
                        "error": "invalid_grant",
                        "error_description": "Sign in again to authorize this agent.",
                    },
                    status_code=400,
                )
            return JSONResponse(result, headers={"Pragma": "no-cache"})

        @app.post("/oauth/revoke")
        async def revoke(request: Request):
            q = await form(request)
            token_hash = digest(q.get("token", ""))
            with state.db() as db:
                row = db.execute(
                    "SELECT agent FROM refresh_tokens WHERE hash=? AND client=?",
                    (token_hash, q.get("client_id", "")),
                ).fetchone()
                if not row:
                    row = db.execute(
                        "SELECT a.agent FROM access_tokens a JOIN refresh_tokens r ON r.agent=a.agent WHERE a.hash=? AND r.client=? LIMIT 1",
                        (token_hash, q.get("client_id", "")),
                    ).fetchone()
                actor = None
                if row:
                    actor = db.execute(
                        "SELECT owner,name FROM agents WHERE id=?", (row["agent"],)
                    ).fetchone()
                    db.execute("UPDATE agents SET active=0 WHERE id=?", (row["agent"],))
            if actor:
                state.event(
                    actor["owner"], actor["name"], "agent.revoked", outcome="local"
                )
            return {}
