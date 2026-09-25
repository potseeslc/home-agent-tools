# Product plan

Draft, September 25, 2026. This is a public design proposal, not deployed functionality.

## User experience

The selected design combines a **Switchboard**, **Request Inbox**, and **Pocket Remote**, with **Guided Setup** for administrators. See the [UI decision](UI-DESIGN.md) for screens, chat handoff, and prototype acceptance.

The dashboard includes these functional areas:

| Area | Purpose |
|---|---|
| Requests | Review access requests, reconnect needs, and new-service requests |
| Connections | Connect services; show health, login requirements, last successful checks, and reconnect actions |
| Agents | Enroll runtimes, assign access, and disable individual enrollments |
| Activity | Explain which client called which tool and the result, with redacted audit records |
| Context | Manage reviewed skills, topology, inventory, and source revisions |

Logging into an AI runtime does not automatically authorize it to the hub. Each client needs enrollment. Providers may revoke upstream access and require reauthentication. The hub persists connection state; it need not hold network sockets open indefinitely.

## Multi-user accounts

Support individual user accounts, Owner/Admin/Member/Viewer roles, personal upstream connections, and shared integration definitions. Agents act under verified user or service identities. The upstream service must authorize the user's own connected account and apply its access level. Hub grants can narrow access, never expand it. Shared-account execution is outside the first release. See [Accounts and access](ACCOUNTS-AND-ACCESS.md).

## Delivery approach

Evaluate ContextForge and Obot before committing to a custom gateway. Reuse existing components if their behavior and deployment model meet the acceptance criteria. Keep the Home Agent Tools name for the resulting service, preserving upstream licensing and attribution. The language and database are provisional until this decision is made.

Build custom adapters, context features, or UI only where a demonstrated gap warrants them. Do not fork a gateway merely to change branding.

## Milestones

1. **Foundation evaluation:** compare pinned releases against Pocket ID login, one combined endpoint, two runtimes, upstream refresh, revocation, and private Git skill sources. Record a reproducible decision before selecting the stack.
2. **Offline prototype:** define tool schemas and adapter contracts; demonstrate the connection and enrollment flows with fixtures. Mock authentication must remain isolated to development.
3. **Authenticated vertical slice:** implement or configure Pocket ID and one read-only upstream integration. Prove the two-runtime success criterion and restart persistence.
4. **Read-only MVP:** add UniFi, Home Assistant, Gitea, and reviewed context. Verify reconnect behavior, failure isolation, redacted audits, and backup restoration.
5. **Selected writes:** add individually scoped operations, target restrictions, and exact-action approval where needed. Test replay prevention and ambiguous upstream outcomes.
6. **Broader compatibility:** publish tested runtime configurations and expand integrations based on actual use.

## MVP acceptance

- Two users connecting the same service cannot access each other's credentials, private results, or requests.
- Upstream identity checks identify each user's connected account, and account-specific permission denials remain enforced. No shared/admin credential fallback is allowed.

- Direct tool calls cannot bypass authorization or target restrictions.
- Disabling one enrollment blocks subsequent calls independently of token expiry.
- Invalid issuer, audience, expiry, or scope is rejected.
- Concurrent refresh requests cannot corrupt rotating credentials.
- An unavailable upstream affects only its associated tools.
- Cached facts identify source, observation time, and staleness.
- Private Git context can be updated and pinned to a reviewed revision.
- Backup restoration recovers encrypted connection state with a separately protected key.

## Scope boundaries

This project is a connection manager, not an AI runtime or universal memory system. Autonomous scheduling, an LLM gateway, device-management agents, and unrestricted shell/HTTP tools are outside the initial scope. Specific device addresses and service credentials belong to deployments, never to the public source.

## Open decisions

- Which gateway, if any, passes the evaluation?
- Which second runtime joins Codex in the initial interoperability test?
- Which identity capabilities exist in the installed Pocket ID version?
- Can each runtime distinguish separately revocable installations?
- Which private/cloud network access paths are required?
- What are the initial audit retention policy and supported deployment sizes?
