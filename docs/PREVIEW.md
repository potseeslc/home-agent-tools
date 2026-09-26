# Running the application preview

See [the v0.2 connector and browser authorization guide](CONNECTOR.md) for the new default agent setup and personal Home Assistant flow.

This is a single-operator preview, not a general multi-tenant release. The web app and bounded MCP endpoint are implemented. ContextForge remains the private identity and Gitea credential broker; the app vault holds personal Home Assistant credentials. A reviewed, pre-provisioned broker workspace is required; arbitrary service onboarding is not implemented yet.

## What works

- Pocket ID browser sign-in and return to the application.
- Gitea personal OAuth connection, actual account verification, and two read tools.
- Personal Home Assistant authorization, identity verification, and availability check. No device control.
- Guided connection review and verification for those two approved definitions.
- Separate expiring agent enrollments, per-service grants, and revocation.
- A chat-callable reconnect-request tool and an owner-only request inbox.
- Redacted activity, with 30-day retention; desktop and phone layouts.

## Install over a provisioned broker

1. Provision the pinned [evaluation stack](../evaluation/README.md), including Pocket ID and Gitea consent. Restrict Pocket ID's client to one intended operator. Every resource must be private, owned by that operator, and assigned to their explicit team. Bootstrap-owned resources are not interchangeable with operator-owned resources.
2. The current adapter expects a private virtual server named `Home Agent Tools Evaluation`, a gateway named `gitea-personal-evaluation`, and tool names `gitea-personal-evaluation-get-me` and `gitea-personal-evaluation-list-my-repos`. Associate only the reviewed tools with the server. The old `ha-api-status` broker tool is no longer used for personal Home Assistant access. These names are a preview implementation contract, not generic service discovery.
3. Obtain the operator's **local broker UUID**, not their Pocket ID subject or email. The broker's `EmailUser.id` is the UUID in a verified session's `sub`. Configure only explicitly provisioned UUIDs. The `/auth/email/me` response in the pinned release does not include this ID.
4. Copy `deploy/app.env.example` to a private location outside the checkout, mode 0600. Set the internal broker URL, operator UUID, exact public origin, exact Pocket ID origin, and a random session secret of at least 32 characters. Use HTTPS except for a localhost SSH tunnel. The broker's `APP_DOMAIN` and both providers' registered callbacks must match that origin. The callbacks are `/auth/sso/callback/pocketid` and `/oauth/callback`.
5. Keep the broker and Gitea adapter on a dedicated Docker network. **Remove the broker's host port publication before exposing this app.** Otherwise clients with enrolled gateway tokens could bypass this app's finer tool grants and argument validation. Do not expose the underlying gateway through another proxy. The deployment compose file assumes the private network already exists.
6. Run:

   ```sh
   export HAT_ENV_FILE=/absolute/private/path/app.env
   export HAT_ENGINE_NETWORK=your-private-broker-network
   docker compose -f deploy/compose.yaml up -d --build
   ```

   The app listens on host loopback port 4444. For a remote host, forward that port over SSH and open `http://localhost:4444`. Do not publish it to the internet by changing the binding alone; HTTPS, secure broker cookies, matching callbacks, trusted network placement, and operational hardening are required first.
7. Sign in through Pocket ID. Verify each connection. Confirm the Gitea username is the intended upstream account. Configure the fixed Home Assistant origin, then sign in with your own Home Assistant account. Use the [local installer](CONNECTOR.md) to enroll each agent through browser approval.

The Compose app layer uses its own persistent volume. Existing manually deployed volumes are not automatically adopted; explicitly map an existing volume before replacing a manual installation. Never run a second installation on the same port unintentionally.

## Runtime connection

The endpoint is `<your-origin>/mcp`, using Streamable HTTP with `Authorization: Bearer <enrollment token>`. Advanced manual tokens are shown once, expire within 1–90 days, and must not be pasted into chat or Git. The app stores token fingerprints and encrypted internal broker credentials. Personal Home Assistant credentials are encrypted in the app vault; ContextForge retains Gitea credentials. Browser setup with rotating tokens is preferred; see CONNECTOR.md.

A compatible runtime can list granted tools and call `home_agent_request_connection` with a granted service (`gitea` or `homeassistant`). It returns a dashboard link. The user signs in, reviews and verifies the connection, resolves the request, and asks the agent to retry. A request link conveys no authority and expires after 24 hours. Reconnecting Gitea disables affected enrollments before authorization starts; after verifying the account, create new enrollments.

The Python MCP SDK 2.2.0 is the automated protocol client used for this preview. Separate HTTP probes test independent grants. These are **not** evidence of two different commercial runtimes working. Hosted OAuth-only clients and cross-runtime skill distribution remain unimplemented/unverified. Local installation and browser-based agent authorization are implemented in v0.2.

## Checks and development

```sh
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.lock
pip install -e '.[test]'
pytest -q
```

The suite tests ownership boundaries, secret redaction, CSRF/origin/host rejection, strict argument validation, revocation, restart persistence, reconnect isolation, and account changes. The broker is mocked; passing these tests alone does not prove upstream identity isolation.

Optional live check, using an enrolled read-only test token file:

```sh
HAT_MCP_URL=http://localhost:4444/mcp \
HAT_TOKEN_FILE=/absolute/private/path/token \
python tests/smoke_mcp.py
```

Revoke the test enrollment afterward. The smoke check prints neither credentials nor service results. Docker builds pin the Python image and runtime dependencies; fonts are bundled with their OFL licenses.

## Operations and limits

- Back up the app SQLite volume and broker database together, using SQLite backup or stopping writers. Keep the broker encryption key and private configuration with encrypted backups. A database backup without the encryption key cannot restore provider credentials.
- Restoring an old app database can restore old enrollment state. Before serving restored data, revoke old broker tokens or start with every restored enrollment disabled. Provider and broker token revocation remains a second gate.
- Revocation blocks new app requests immediately; an already-running upstream call may finish. Broker deletion failure is reported as pending, while local access stays blocked. A server operator must finish upstream revocation; automatic reconciliation is not implemented.
- Connection verification creates and deletes a temporary scoped broker token. Tokens last at most one day if cleanup fails. Review broker token records after outages.
- The broker currently maps SSO accounts by verified email. The app uses the validated local UUID, but that does not solve issuer/subject binding upstream. Do not expand this deployment to untrusted users or treat it as proven multi-tenant isolation.
- Home Assistant now requires personal authorization. Its underlying token can have broader account permissions than the fixed availability tool. There is no shared-token fallback.
- Gitea requests `read:user read:repository`; its token record did not echo scopes in this evaluation. The UI distinguishes requested scopes from fully verified upstream permissions.
- Gitea refresh remains delegated to the pinned broker. The app implements personal Home Assistant refresh. Mocked refresh tests do not replace live provider expiry and revocation checks.
- There are no arbitrary outbound URL tools, write tools, dynamic integration installs, Docker socket mounts, role-management UI, or public user registration in this preview. Native OAuth client registration is supported.
- Deployments use a single app process and SQLite. Production-grade rate limiting, durable revocation reconciliation, full multi-user authorization, dependency security review, and broader client compatibility are release work.

The earlier planning documents describe the longer-term product. This document and the live results describe what this preview actually implements.
