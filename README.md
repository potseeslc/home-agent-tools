# Home Agent Tools

An open-source, self-hosted connection manager for AI agents.

**Connect your services once. Give each agent the tools and knowledge it needs. Manage access in one place.**

## Project status

**Single-operator preview, v0.2.** Home Agent Tools now includes a one-command local installer, Pocket ID-backed browser approval for agents, a fixed 30/90-day access lifecycle, and personal Home Assistant authorization. The web app provides a switchboard, connection setup, per-agent grants and revocation, request inbox, and activity.

Start with [the installer and browser connection guide](docs/CONNECTOR.md). For server provisioning, see [the deployment guide](docs/PREVIEW.md). The internal ContextForge broker and explicit operator allowlist are still required. This is not a general multi-tenant or hosted-client release.

Codex and macOS Claude Desktop configuration adapters are included. OAuth and stdio behavior are tested; actual provider consent and product-specific compatibility must be verified separately. UniFi, arbitrary service setup, role administration, and skill distribution remain future work. Credentials stay outside Git.

## Vision

Home Agent Tools aims to provide a management website and authenticated MCP interface for:

- Service connections, OAuth refresh, connection health, and reconnect flows.
- Personal upstream accounts and explicitly granted shared service connections, with clear identity and activity attribution.
- Access bounded by service account permissions, connection authorization, and user/agent grants.
- Individually enrolled agents with scoped access and revocation.
- Shared skills, operating instructions, and context from Git repositories, including self-hosted Gitea.
- Pocket ID integration, with standards-based identity boundaries.
- Straightforward self-hosting, persistent storage, and documented backups.

Initial integration targets are UniFi, Home Assistant, and Gitea. The architecture should support other services without depending on a particular household, AI provider, or model. Compatibility will be tested per runtime; MCP support alone does not guarantee every authentication or skill-loading feature works.

## Design documents

- [Product plan and roadmap](docs/PLAN.md)
- [Selected UI direction](docs/UI-DESIGN.md)
- [Accounts, ownership, and access levels](docs/ACCOUNTS-AND-ACCESS.md)
- [Architecture and Pocket ID](docs/ARCHITECTURE.md)
- [Existing gateway evaluation](docs/GATEWAY-EVALUATION.md)
- [Security design](docs/SECURITY-DESIGN.md)
- [Contributing](CONTRIBUTING.md)

## First success criterion

Two distinct runtimes can access the same permitted live inventory without receiving upstream service credentials. Revoking one enrollment blocks its subsequent calls without disconnecting the other.

GitHub is the primary source, issue tracker, and review location for this project. Deployment credentials and private inventories must remain outside this repository.

## License

[MIT](LICENSE).
