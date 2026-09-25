# Selected UI direction

Accepted September 25, 2026. Design decision only; these screens are not implemented.

The interface combines concepts 1 (Switchboard), 3 (Request Inbox), and 8 (Pocket Remote), with concept 7 (Guided Setup) for service administrators.

## Accounts throughout the interface

Show the signed-in account, active workspace, and the identity an agent acts for. Keep connection ownership, access level, and health distinct. The [account and access model](ACCOUNTS-AND-ACCESS.md) governs every screen.

## Switchboard

The default home screen separates My connections from Shared with me, showing connection owner, upstream account label when verified, connection health, and available tools. Service cards lead to connection details and relevant reconnect actions. Keep connection health separate from an agent's permission to use that connection.

Agents, activity, and shared context remain accessible through navigation. Requests have a dedicated inbox rather than being buried in service configuration.

## Request Inbox

Collect agent access requests, reconnect needs, and requests for services that are not configured yet. Each request identifies the requesting user and agent, service, credential owner, requested capabilities, and the action needed from the authorized reviewer.

Distinguish reconnecting an existing service from granting agent access. Neither action should silently expand the other. Show pending, resolved, denied, and expired states. Users may act only on requests they are authorized to manage.

## Pocket Remote

Provide the same request-review experience in a responsive phone layout. Prioritize a readable request summary, requested access, and a clear next action. This is a mobile presentation of the shared application, not a separate app or permission system.

## Guided Setup for administrators and connection owners

Admin flow: choose service → enter connection details → authenticate → verify connected account → test connection → select exposed tools → review ownership/sharing → assign agent access → finish.

Member flow: choose an approved service → connect a personal account → verify identity and test → review personal visibility → assign owned agents access within policy. Members cannot register arbitrary service endpoints.

Adapt authentication steps to the integration's actual mechanism. Pocket ID authenticates the administrator to the hub; service authentication may use OAuth, an API credential, or an existing connection. Do not assume every service has a browser OAuth flow.

Preserve nonsensitive progress when a test fails and make retries understandable. Store any credentials only through the protected server-side credential flow. Review the resulting tool set and grants before finishing. Never grant every agent access merely because a service was added.

## Connection requests from chat

1. An enrolled agent requests an operation or explicitly requests a connection.
2. The hub identifies whether service setup, reauthentication, or an access grant is missing.
3. It returns a structured status and a short-lived request link. The agent presents a link or, where supported, a richer action card.
4. The user opens the request and signs in. A request URL is a reference, not authorization; verify the signed-in user's authority and bind the decision to the request and agent.
5. Existing services open focused reconnect or access-review screens. New-service requests lead authorized administrators into Guided Setup.
6. Once setup and grants are complete, the service appears on the Switchboard and the request is resolved.
7. The agent checks request/connection status and retries only when appropriate. Automatic continuation depends on the runtime; the baseline supports returning to chat and asking it to continue.

Do not put credentials into request URLs or chat. Expired, denied, or unresolved requests must not unlock tools. Avoid replaying an original write after setup without checking its authorization and execution state.

## Prototype acceptance

- The default screen uses service cards and distinguishes login failure from denied agent access.
- One request can be followed from chat through review and back to a successful simulated read.
- A new-service request leads an administrator through all setup stages.
- A non-admin cannot register a new service endpoint through a direct request link, but may connect a personal account to an approved service within policy.
- Request and connection views distinguish the initiating user/agent from the upstream credential account.
- The same request can be reviewed on desktop and phone without changing its scope.
- Denial, expiry, authentication failure, test failure, and return-to-chat states are represented.

The gateway evaluation remains open. Use this experience to assess existing UI coverage before deciding what needs custom implementation.
