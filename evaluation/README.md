# Connection evaluation

This is an isolated trial of existing software, not the Home Agent Tools application or a production deployment. It does not yet establish two-user identity isolation, runtime portability, refresh/revocation reliability, or skill distribution.

**Current outcome:** [live evaluation results](RESULTS.md). Personal Gitea and shared Home Assistant calls work. Direct gateway schema validation still fails; the new [application preview](../docs/PREVIEW.md) adds enforcement and keeps the gateway internal-only. Do not expand to untrusted users yet.

## Components

| Component | Pinned version | Purpose |
|---|---|---|
| ContextForge | v1.0.7-20260921 | Dashboard, Pocket ID OIDC, MCP aggregation |
| Official Gitea MCP | v1.7.0 | `get_me` and `list_my_repos`, read-only mode, per-request Gitea credentials |
| Pocket ID | API contract evaluated against v2.14.0 | Hub sign-in; separate from Gitea authorization |
| Gitea | OAuth tested for configuration against v1.27.2 | Personal upstream account authorization |
| Home Assistant | Existing installation | Fixed GET `/api/` availability probe using a shared token |

Images in `compose.yaml` use immutable registry digests. The gateway and adapter run without a Docker socket, with dropped capabilities, resource limits, and no new privileges. Only the gateway publishes a port, bound to loopback. The one-shot volume initializer runs as root solely to set the gateway volume ownership.

## Setup

1. Copy `gateway.env.example` outside Git, set mode 0600, and generate separate random values for all secrets. Keep the encryption key with encrypted backups; losing it prevents reading saved credentials. Do not print `docker compose config` with real credentials.
2. Create a dedicated Pocket ID group containing only the evaluator. Create a confidential client restricted to that group, with PKCE required and consent enabled. Register exactly `http://localhost:4444/auth/sso/callback/pocketid`. Create a client secret, preferably with an evaluation expiry. Copy the actual endpoint values from the issuer's discovery document into the private env file. Never use the Pocket ID administrator API key as a runtime credential.
3. Create a dedicated confidential Gitea OAuth application with `http://localhost:4444/oauth/callback`. Leave consent enabled. Save its `client_id` and `client_secret` outside Git. The requested scopes must explicitly be `read:user` and `read:repository`; do not substitute bare OIDC or unrecognized scopes. See [Gitea's OAuth scope rules](https://docs.gitea.com/development/oauth2-provider/).
4. Choose an unused Docker subnet and add only the adapter IP and Home Assistant host /32 to `SSRF_ALLOWED_NETWORKS`. Private networks remain denied otherwise. This gateway release applies outbound URL rules to browser callbacks too, so this local trial permits localhost. Reassess that exception for deployment.
5. Set `GATEWAY_ENV_FILE` to the private env file and `GITEA_URL` to your HTTPS instance URL. Optional `EVALUATION_SUBNET` and `GITEA_ADAPTER_IP` must match the allowlist. Run `docker compose -f evaluation/compose.yaml up -d` on the evaluation host. Do not run this beside an already provisioned trial on the same port.
6. When using a remote host, forward local port 4444 to its loopback port 4444 over SSH. Open `http://localhost:4444/admin` and sign in with Pocket ID. The browser running the login must have the tunnel. HTTP and non-secure cookies here are limited to the local tunnel; a hosted deployment needs HTTPS and secure cookies.
7. Register the two service entries below. The bootstrap email account requires a password change before API login. Use the dashboard's supported password-change flow; never give its administrator session token to an agent.

Assign an explicit existing evaluator team ID to **every tool, gateway, and virtual server at creation**, in addition to private visibility. In this release, startup migration converts resources with no team to public visibility. Explicit team assignment plus restoring private visibility survived our restart test. Do not rely on private visibility alone.

## Service registration

`services.example.json` describes inputs; it is a reference, not an automatic importer. Keep populated copies private.

**Home Assistant:** register a REST tool named `ha_api_status`, fixed GET URL ending `/api/`, bearer authentication, and private visibility. Set input schema to `{"type":"object","properties":{},"additionalProperties":false}`, `expose_passthrough=false`, and read-only annotations. ContextForge normalizes the exposed name to `ha-api-status`. The `/tools` API expects the body under `{"tool": ...}`. Check the returned and persisted visibility rather than relying on UI defaults.

The trial uses a shared credential. Home Assistant sees that token's owner; hub logs identify the caller. A broad underlying token is still broad if stolen: a fixed read-only tool does not narrow the token itself. Replace borrowed evaluation credentials with a dedicated upstream account/token before expanding access. No native Home Assistant control tools are imported.

**Gitea:** register a private Streamable HTTP gateway at `http://gitea:8080/mcp` with `auth_type=oauth`. Set its `oauth_config` to `grant_type=authorization_code`, the dedicated client credentials, authorization and token URLs, localhost callback, explicit read scopes, and `omit_resource=true`. No static Gitea token is installed in the adapter. Authorize the gateway while signed in as the intended hub user. Tool discovery may remain empty until that user completes consent.

Create a private virtual server containing only the approved tools. The `/servers` API wraps input under `{"server": ...,"visibility":"private"}`. Enroll each runtime separately with a short-lived, server-scoped token and only `tools.read`, `tools.execute`, and `servers.read`. Select the appropriate team; an administrator dashboard session is not equivalent to a scoped runtime token. Save bearer tokens privately, never in committed client configuration.

## Verification and cleanup

Use `probe.py` with a scoped token file. It calls only the Home Assistant availability probe, checks anonymous denial, and verifies that extra arguments cannot override the endpoint. It does not complete Pocket ID login, Gitea consent, or prove multi-user authorization.

Before expanding access, complete the [evaluation gates](../docs/GATEWAY-EVALUATION.md), including two real users, two runtimes, upstream account identity, effective permissions, refresh, per-enrollment revocation, and restart visibility. Record failures as failures; registration alone is not a working connection.

Stop with `docker compose -f evaluation/compose.yaml down`. This preserves the database volume. Remove the dedicated Pocket ID/Gitea applications and revoke evaluation tokens when retiring the trial. Remove the volume only when deliberately discarding its saved connections. Existing household clients and groups are outside this trial's scope.

Source references: [ContextForge pinned source](https://github.com/IBM/mcp-context-forge/tree/v1.0.7-20260921), [official Gitea MCP pinned documentation](https://gitea.com/gitea/gitea-mcp/src/tag/v1.7.0/README.md), [Pocket ID client contract](https://github.com/pocket-id/pocket-id/blob/v2.14.0/backend/internal/dto/oidc_dto.go).
