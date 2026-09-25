# Live evaluation — September 25, 2026

The trial ran on an ARM64 Docker host using the image digests in `compose.yaml`, provisioned with isolated Docker commands and accessed through a loopback SSH tunnel. The Compose template passed configuration validation; it has not been separately deployed. No production household container was replaced. Private host addresses, identities, and credentials are excluded from this record.

| Check | Observed result |
|---|---|
| Gateway startup and health | HTTP 200; database persisted across restart |
| Pocket ID registration | Dedicated confidential client; dedicated group with one evaluator; PKCE and consent enabled; readback verified |
| Pocket ID authorization initiation | Correct issuer redirect, exact registered callback, S256 PKCE |
| Pocket ID completed browser login | Pending evaluator interaction; not verified |
| Home Assistant through MCP | Scoped token discovered the single availability tool and received `API running.` from fixed GET `/api/` |
| Anonymous gateway tool execution | HTTP 401 |
| Gitea adapter | Exactly `get_me` and `list_my_repos` exposed; read-only flag enabled; no stored upstream token |
| Gitea without a credential | `get_me` returned an MCP error result; no shared-account fallback |
| Gitea OAuth initiation | Dedicated application; redirect requests `read:user read:repository` with S256 PKCE |
| Gitea consent, identity and repository access | Pending evaluator consent; gateway tool discovery remains empty |
| Untyped/extra tool arguments | **Failed:** `additionalProperties=false` did not reject an extra argument, including with `EXPERIMENTAL_VALIDATE_IO=true` |
| Private resources without a team after restart | **Failed:** tool, gateway, and virtual server became public |
| Explicit team assignment and private visibility after restart | Passed for all three resources; HA call remained available through its scoped token |
| Two actual agent runtimes | Not tested; an HTTP MCP probe is not two runtimes |
| Refresh, revocation, two-user upstream permissions | Not tested |

## Findings that affect the design

ContextForge's startup assignment logic sets visibility to public for resources without teams. The pinned [bootstrap implementation](https://github.com/IBM/mcp-context-forge/blob/v1.0.7-20260921/mcpgateway/bootstrap_db.py) contains that assignment. The evaluation repaired its three resources with explicit team ownership and private visibility and verified those values after restart. A future setup wizard must require team ownership and verify persisted access; this is not evidence that all multi-user behavior is safe.

The REST schema rejection gate remains open. The probe supplies a harmless extra argument; it does not demonstrate arbitrary URL access or a write. Nevertheless, schema declaration and read-only annotations cannot substitute for execution enforcement. The availability probe's URL and HTTP method are fixed and direct passthrough is disabled. Keep this trial limited until input handling is understood and tested.

The Home Assistant credential is a borrowed existing token, explicitly treated as a shared connection. Its upstream permissions were not narrowed by the gateway. A dedicated least-privilege credential is required before expansion. Gitea is configured for personal OAuth with no static fallback, but personal identity has not been verified until the user authorizes and `get_me` succeeds under that user's connection.

No gateway foundation has been selected. No upstream issue or security report has been submitted by this evaluation. Next: finish user login and Gitea consent, resolve the schema gate, and run the two-user/two-runtime checks in the main evaluation plan.
