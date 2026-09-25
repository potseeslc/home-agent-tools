# Accounts, connection ownership, and access levels

Product requirement accepted September 25, 2026. Design only; not yet implemented.

Home Agent Tools supports multiple people connecting their own service accounts. Every request must remain attributable to the authenticated person or explicitly enrolled service identity and the agent acting for them.

## Identity model

- **User:** a local account mapped to a validated identity-provider issuer and subject. Email and display name are mutable labels, not account keys.
- **Workspace membership:** an active user's role in a household or team. Start with one workspace in the UI while keeping ownership and authorization boundaries explicit in storage.
- **Agent enrollment:** a credential-bound relationship between a client, an owning user or service principal, a workspace, and permitted capabilities. Different people using the same runtime do not share an identity merely because its OAuth client ID is the same.
- **Service definition:** an administrator-approved integration type and endpoint configuration. A definition is distinct from a user's connection to an upstream account.
- **Connection:** the credential-bearing link to a service, with an owner, workspace, visibility, and upstream account identity where verifiable.
- **Grant:** permission to use a connection through specified tools and targets. Using, managing, reconnecting, and sharing a connection are distinct capabilities.

The authenticated principal comes from verified credentials, never a tool argument such as user_id, an agent name, or a user-selected workspace alone. Validate workspace membership and enrollment on every request. Keep human-delegated and machine-to-machine identities distinct; scheduled jobs must not be falsely attributed to a currently signed-in human.

## Access levels

These are proposed default roles, supplemented by explicit connection and tool grants.

| Role | Default responsibilities |
|---|---|
| Owner | Workspace ownership, administrator assignment, and security/recovery policy |
| Admin | Approved service definitions, workspace membership, shared connection policy, and operational management |
| Member | Connect personal accounts to approved services, manage owned connections and agent enrollments within policy, and use explicitly granted tools |
| Viewer | View explicitly permitted service status and context; no tool execution or connection management unless separately granted |

A role does not implicitly grant use of every upstream credential. An admin can disable a connection for operational reasons without receiving permission to act as its owner or view its secrets. Define narrow audit visibility, and keep raw credentials unavailable through the UI and tools.

Effective access requires all of: active user/service identity, active workspace membership where applicable, active agent enrollment, token scope, connection grant, and tool/target permission. Approval requirements can further restrict an operation. No granted role or matching skill can override a missing requirement.

## Personal and shared connections

Connections are personal by default. A user may connect a personal account to an already approved service without becoming a platform administrator. Adding a new integration endpoint or executable remains an admin task.

Sharing is an explicit action naming the workspace members/groups, permitted operations and targets, and whether recipients may only use or also manage the connection. Never expose the actual secret. Display when sharing means actions will use the connection owner's upstream account.

Prefer separate per-user upstream connections where the service supports them. Reuse a shared service account only when deliberately configured and appropriately scoped. Never fall back from a missing user connection to an administrator's or another user's credentials. If multiple authorized connections fit a request, require an explicit choice or a previously saved authorized default.

Reconnect updates the existing connection only when the connecting user has authority to do so. If the verified upstream account changes, show the identity change and require review of existing grants instead of silently retaining access under a different account.

## What identity is preserved

Record both sides of each action:

- initiating hub principal and agent enrollment;
- workspace and connection identifier;
- credential owner and verified upstream account identifier, when available;
- tool, bounded target description, authorization outcome, time, and correlation ID.

The hub's audit record can preserve the initiating identity even when a service uses a shared account. The upstream service will ordinarily see the account represented by its credential. End-to-end attribution requires per-user credentials or a supported delegation mechanism; do not claim that a user name in a header creates upstream impersonation or authorization. Label unavailable upstream identity as unknown rather than inventing one.

## Isolation and lifecycle

Scope connection discovery, tool results, resources, skills, caches, request links, OAuth state, refresh locks, and audit reads by their proper user/workspace/connection boundaries. Do not reuse a result cache across callers with different grants or upstream identities. Authorization still runs on cache hits.

Bind OAuth setup state and callbacks to the authenticated initiating account, intended connection, client/request, and expiry. Switching browser accounts during setup must not attach credentials to the wrong person. A forwarded chat link does not transfer ownership or permission.

Revoking a user, enrollment, or connection grant blocks subsequent authorized access locally. Removing a member prevents use of that workspace's shared connections; determine whether owned shared connections are disabled or explicitly transferred through a documented process. Do not silently transfer personal credentials to an administrator. Coordinate deletion of credentials and caches with the audit retention policy; retain only justified redacted records.

## UI implications

- **Account menu:** signed-in identity and active workspace; show “Acting for” on agent-related screens.
- **Switchboard:** separate My connections and Shared with me. Cards show credential owner, upstream account label when verified, access level, and health as distinct facts.
- **Request Inbox:** show requester, agent, connection owner, requested actions, and who can approve. Route personal reconnects to their owner and service-registration requests to an admin.
- **Guided Setup:** administrators register services and shared connections; members link personal accounts to approved services. Show the account being connected and default visibility before finishing.
- **Pocket Remote:** retain identity, ownership, and scope summaries; do not hide them merely to shorten the phone flow.
- **Activity:** distinguish “requested by” from “executed using.” Limit visibility by role and ownership.

## Acceptance tests

1. Two users connect the same service with different accounts; each agent gets only its owner's authorized results.
2. Guessing another user's connection/request ID or changing a workspace parameter cannot bypass access checks.
3. Shared use is explicitly granted; recipients cannot export secrets, reconnect, or reshare without separate permission.
4. An admin cannot execute tools using personal credentials solely because of the admin role.
5. Shared-account actions record the real initiating user and agent, while accurately naming the upstream account.
6. A failed personal connection never triggers a fallback to a more privileged account.
7. Browser-account changes and replayed callbacks cannot attach credentials to another user.
8. Permission revocation also blocks cached results and direct tool calls.
9. A different upstream account at reconnect triggers grant review.
10. Membership removal and machine-to-machine execution follow the documented identity and lifecycle rules.
