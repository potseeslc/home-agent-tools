# Live evaluation — September 25, 2026

The evaluation and first application preview ran on an ARM64 Docker host, reached through a localhost SSH tunnel. Images were pinned by digest. Existing household services were not replaced. Private addresses, identities, and credentials are excluded here.

| Check | Observed result |
|---|---|
| Pocket ID | Dedicated restricted client, PKCE and consent; operator completed login; app sign-in returned successfully to the new switchboard |
| Personal Gitea OAuth | Operator completed consent; `get_me` verified the actual upstream account; `list_my_repos` succeeded through app-enrolled access |
| No personal credential | Gitea call failed without a credential; adapter has no shared-account fallback |
| Home Assistant | Fixed GET `/api/` returned `API running.` through scoped access; app exposes no device-control tool |
| Ownership | All five evaluated resources assigned to operator and explicit team with private visibility; persisted across broker restart |
| Strict app arguments | Unexpected arguments and ungranted service tools rejected before forwarding |
| Independent agent grants | Two HTTP probe enrollments worked; revoking one returned 401 for its subsequent calls while the other remained usable |
| Official protocol client | Python MCP SDK 2.2.0 initialized with 2025-11-25, listed granted tools, and called Home Assistant |
| Live restart | Recreated app preserved revoked and active enrollments; SDK call still succeeded; all temporary test agents subsequently revoked and test request resolved |
| Application tests | 13 tests passed, including ownership, CSRF, origin/host restrictions, secret redaction, argument bounds, reconnect isolation, and revocation across reconstructed app state |
| Browser | Pocket ID return and authenticated switchboard verified; desktop and 390px mobile layouts reviewed; guided setup dialog opened |
| Actual distinct agent products | Not tested; SDK and HTTP probes are not proof of two commercial runtimes |
| Two real upstream users | Not tested; mocked ownership tests do not prove broker multi-user identity isolation |
| Forced provider refresh/expiry | Not tested; delegated to broker |

## Findings and containment

**Broker startup visibility:** resources without a team were made public by the pinned broker's startup assignment logic. All reviewed resources now have explicit owner/team assignments and private visibility, verified after restart. The initial bootstrap-owned resources also had to be reassigned to the intended operator before their personal connection could execute. This is an installation requirement, not proof of general multi-user safety.

**Broker argument validation:** the original REST tool accepted undeclared arguments even with `additionalProperties=false` and experimental validation enabled. The application now uses a fixed tool allowlist and validates arguments before forwarding. The gateway is internal-only behind the app. The old `evaluation/probe.py` failure remains valid for direct access to the evaluated gateway; it is not silently reclassified as passed.

**Broker profile shape:** `/auth/email/me` does not return the user's UUID. The application first requires that endpoint to validate the session, then uses that same verified JWT's `sub` and rejects API-token use at the browser control plane. This was discovered by live testing and reflected in the mock contract.

**Gitea repository schema:** the actual adapter uses `page` and `per_page`. The app further bounds these to integers and limits page size to 50. Unknown arguments are rejected rather than silently passed through.

**Upstream image health check:** the pinned Gitea adapter's health check used `/bin/sh`, absent in its image. An exec-form `/app/gitea-mcp -healthcheck` succeeds; Compose overrides and the minimal derived Dockerfile correct that packaging issue.

**Identity and scopes:** the broker still maps SSO accounts by verified email. The app's UUID allowlist does not solve upstream issuer/subject binding. Gitea requested `read:user read:repository`, but its stored token scopes were empty; successful read calls do not prove the full effective permission set. Home Assistant uses a borrowed shared token whose underlying permissions may exceed the one exposed tool. Keep the preview restricted to its operator.

The implemented UI, runtime endpoint, installation contract, operational limits, and remaining release gates are described in [the preview guide](../docs/PREVIEW.md). No upstream issue or security report has been submitted as part of this work.

## Browser connector increment — 2026-09-26

Version 0.2 adds fixed 30/90-day per-agent browser approvals, S256 PKCE, rotating short-lived access credentials, a macOS/Linux installer and stdio bridge, and personal Home Assistant authorization stored in the encrypted app vault. ContextForge continues to broker Pocket ID and Gitea. See [the connector guide](../docs/CONNECTOR.md) for the exact limits.

Validation: 26 automated tests passed, including a real loopback HTTP callback and subprocess stdio client using simulated upstream identity/consent; refresh replay, fixed expiry, ownership, encrypted storage, configuration preservation, and renewal failure behavior. The preview image was built and the CLI installed locally. Real Home Assistant consent and the first browser-authorized Codex enrollment remain pending the operator's sign-in; automated tests are not evidence that those live steps succeeded.
