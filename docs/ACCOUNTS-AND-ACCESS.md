# Accounts, connection ownership, and access levels

Product requirement accepted September 25, 2026. Design only; not yet implemented.

Home Agent Tools supports multiple people connecting their own service accounts. For user-delegated actions, the upstream service must receive authorization representing that user's own connected account and enforce that account's access. Hub audit attribution alone does not meet this requirement. Share integration setup, not personal credentials. Shared-account execution is outside the first release.

## Identity model

- **User:** a local account mapped to a validated identity-provider issuer and subject. Email and display name are mutable labels, not account keys.
- **Workspace membership:** an active user's role in a household or team. Start with one workspace in the UI while keeping ownership and authorization boundaries explicit in storage.
- **Agent enrollment:** a credential-bound relationship between a client, an owning user or service principal, a workspace, and permitted capabilities. Different people using the same runtime do not share an identity merely because its OAuth client ID is the same.
- **Service definition:** an administrator-approved integration type and endpoint configuration. A definition is distinct from a user's connection to an upstream account.
- **Connection:** the credential-bearing link to a service, with an owner, workspace, visibility, and upstream account identity where verifiable.
- **Grant:** permission to use a connection through specified tools and targets. Using and managing an owned connection are separate from administering the shared service definition. Grants cannot authorize another user to execute through personal credentials in the first release.

The authenticated principal comes from verified credentials, never a tool argument such as user_id, an agent name, or a user-selected workspace alone. Validate workspace membership and enrollment on every request. Keep human-delegated and machine-to-machine identities distinct; scheduled jobs must not be falsely attributed to a currently signed-in human.

## Access levels

These are proposed default roles, supplemented by explicit connection and tool grants.

| Role | Default responsibilities |
|---|---|
| Owner | Workspace ownership, administrator assignment, and security/recovery policy |
| Admin | Approved service definitions, workspace membership, service availability policy, and operational management |
| Member | Connect personal accounts to approved services, manage owned connections and agent enrollments within policy, and use explicitly granted tools |
| Viewer | View explicitly permitted service status and context; no tool execution or connection management unless separately granted |

A role does not implicitly grant use of every upstream credential. An admin can disable a connection for operational reasons without receiving permission to act as its owner or view its secrets. Define narrow audit visibility, and keep raw credentials unavailable through the UI and tools.

Effective access requires all of: active user/service identity, active workspace membership where applicable, active agent enrollment, token scope, connection grant, and tool/target permission. Approval requirements can further restrict an operation. No granted role or matching skill can override a missing requirement.

## Personal upstream connections

Administrators make service integrations available to eligible workspace members. Each member separately connects their own upstream account through that provider's supported authorization mechanism. Administrators do not log into a service on behalf of all users. Registering an integration and linking a personal account are separate flows.

Route a user-delegated tool call only to the authenticated user's authorized connection. The upstream sees the user's account through per-user authorization or a provider-supported delegated mechanism. Pocket ID identifies the user to the hub; it does not automatically identify them to every upstream provider.

The upstream account's permissions and granted API scopes bound what can succeed; hub grants may narrow this access but cannot expand it. A personal API token may be valid where OAuth is unavailable, but a shared administrator token does not satisfy the requirement. Providers offering only shared service credentials do not qualify for the personal-identity MVP.

Never fall back to another user's, an administrator's, or a shared account when a connection is missing or fails. If several connections owned by the same user fit, require an explicit selection or a saved authorized default.

Reconnect requires the connection owner's authentication. If the verified upstream identity changes, show the change and review existing agent grants. Do not match upstream identity by email alone, invent identity headers, or claim that logging a user name makes a shared token personal.

Separate machine-to-machine identities may be evaluated later, clearly labeled as service identities rather than the current user. Shared-credential execution is not part of the first release.

## What identity is preserved

Record both sides of each action:

- initiating hub principal and agent enrollment;
- workspace and connection identifier;
- credential owner and verified upstream account identifier, when available;
- tool, bounded target description, authorization outcome, time, and correlation ID.

The audit record must agree with the credential identity used upstream. Verify upstream identity through an authoritative provider response where supported and test account-specific results and permission denials. Do not mark an integration as supporting personal identity merely because requests are attributed locally. Where upstream identity cannot be confirmed, label the limitation and leave the personal-identity acceptance check unresolved.

## Isolation and lifecycle

Scope connection discovery, tool results, resources, skills, caches, request links, OAuth state, refresh locks, and audit reads by their proper user/workspace/connection boundaries. Do not reuse a result cache across callers with different grants or upstream identities. Authorization still runs on cache hits.

Bind OAuth setup state and callbacks to the authenticated initiating account, intended connection, client/request, and expiry. Switching browser accounts during setup must not attach credentials to the wrong person. A forwarded chat link does not transfer ownership or permission.

Revoking a user, enrollment, or connection grant blocks subsequent authorized access locally. Removing a member blocks their workspace enrollments and associated connection use. Personal credentials must not be transferred to an administrator or another member. Coordinate deletion of credentials and caches with the audit retention policy; retain only justified redacted records.

## UI implications

- **Account menu:** signed-in identity and active workspace; show “Acting for” on agent-related screens.
- **Switchboard:** separate My connections and Available services. Available services are approved integrations each user can connect, not other people's credentials. Cards show credential owner, upstream account label when verified, access level, and health as distinct facts.
- **Request Inbox:** show requester, agent, connection owner, requested actions, and who can approve. Route personal reconnects to their owner and service-registration requests to an admin.
- **Guided Setup:** administrators register service definitions; each user, including administrators, links their own upstream account. Show the account being connected and default visibility before finishing.
- **Pocket Remote:** retain identity, ownership, and scope summaries; do not hide them merely to shorten the phone flow.
- **Activity:** distinguish “requested by” from “executed using.” Limit visibility by role and ownership.

## Acceptance tests

1. Two users connect the same service with different accounts; each agent gets only its owner's authorized results.
2. Guessing another user's connection/request ID or changing a workspace parameter cannot bypass access checks.
3. Sharing a service definition never makes another user's connection usable; each user must connect their own account.
4. An admin cannot execute tools using personal credentials solely because of the admin role.
5. An authoritative upstream identity check identifies the expected account for each user; different upstream access levels produce the expected permitted results and denials.
6. A failed personal connection never triggers a fallback to a more privileged account.
7. Browser-account changes and replayed callbacks cannot attach credentials to another user.
8. Permission revocation also blocks cached results and direct tool calls.
9. A different upstream account at reconnect triggers grant review.
10. Membership removal and machine-to-machine execution follow the documented identity and lifecycle rules.
