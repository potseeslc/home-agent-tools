# Existing gateway evaluation

Research snapshot: September 25, 2026. Documentation review only; neither candidate has been installed or tested by this project. Documentation across versions may disagree. Select a release and verify code and behavior before choosing a foundation.

| Requirement | Obot | ContextForge |
|---|---|---|
| Combined MCP endpoint | Composite servers | Virtual servers |
| Upstream authentication | OAuth and refresh | Encrypted token storage and refresh |
| Administration | Server, policy, skills, and activity interfaces | Gateway, tool, resource, and authentication interfaces |
| Agent access | Scoped credentials and access policies | Gateway access controls; exact per-enrollment behavior needs testing |
| Shared skills | Explicit catalog and installation workflow | No equivalent distribution workflow confirmed in this review |
| Pocket ID | Not in the documented provider list; generic OIDC unconfirmed | Generic OIDC documented; complete MCP login untested |
| Private Gitea skill source | Detailed skill guide specifies GitHub; broader docs mention other providers | Requires evaluation of context/resource integration |

## Obot

Obot is the closer documented match to the full connection-management and skills experience. It combines selected upstream tools and keeps upstream authorization separate from client authorization. Agent scopes can restrict server access, and deleting a scope invalidates its keys.

Its skill guide documents indexing `SKILL.md` repositories and downloading supporting files. Removing source access does not erase installed copies. Verify private Gitea support rather than assuming generic Git support from the overview.

Application-level encryption requires configuration and is documented as disabled by default. The Docker quickstart mounts the host Docker socket to launch servers; assess an isolated deployment model before using this in a homelab. Additional platform components are not requirements for Home Agent Tools.

Sources: [servers](https://docs.obot.ai/functionality/mcp-servers/), [skills](https://docs.obot.ai/functionality/skills/), [agent scopes](https://docs.obot.ai/functionality/agent-auth-scopes/), [architecture](https://docs.obot.ai/concepts/architecture/), [authentication](https://docs.obot.ai/configuration/auth-providers/), [installation overview](https://docs.obot.ai/).

## ContextForge

ContextForge is a plausible first Pocket ID evaluation because generic OIDC is documented. Check both dashboard sign-in and inbound MCP authorization. Its gateway aggregation and resource support could host shared homelab context.

The reviewed OAuth design document lists gaps in per-user upstream token administration, enforcement of some UI options, and scheduled cleanup. Verify those notes against the chosen release. Upstream token revocation and client-to-gateway revocation are different tests.

Sources: [project](https://github.com/IBM/mcp-context-forge), [configuration](https://github.com/IBM/mcp-context-forge/blob/main/docs/docs/manage/configuration.md), [OAuth design](https://github.com/IBM/mcp-context-forge/blob/main/docs/docs/architecture/oauth-design.md), [protected-resource support](https://github.com/IBM/mcp-context-forge/blob/main/docs/docs/architecture/rfc9728-compliance.md).

## Evaluation procedure

For each candidate, record release/commit, license, enabled edition/features, deployment requirements, configuration, and reproducible results:

1. Sign in with Pocket ID through the dashboard and a real MCP client.
2. Connect two runtimes to one combined read-only tool set.
3. Authorize an upstream once and confirm reuse across permitted clients.
4. Exercise expiry, refresh rotation, restart recovery, and reconnect-required states.
5. Revoke one enrollment and confirm another remains usable.
6. Deny a direct unauthorized call and a disallowed device/repository target.
7. Load a private Gitea skill, update its revision, and observe client behavior.
8. Inspect encryption, audit redaction, and backup restoration.

Also evaluate the [multi-user account requirements](ACCOUNTS-AND-ACCESS.md): per-user upstream connections, role boundaries, explicit sharing, cache isolation, reconnect identity changes, and initiating-user versus upstream-account attribution. Generic multi-tenancy claims are not sufficient evidence.

Prefer configuration and small adapters over a deep fork. Choose a custom gateway only when measured gaps justify its maintenance cost. No candidate is selected yet.
