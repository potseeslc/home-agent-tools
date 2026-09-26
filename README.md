# Home Agent Tools

An open-source, self-hosted connection manager for AI agents.

**Connect your services once. Give each agent the tools and knowledge it needs. Manage access in one place.**

## Project status

**Usable single-operator preview.** The repository now contains the Home Agent Tools web app: Pocket ID sign-in, a personal Gitea connection, an explicitly shared Home Assistant status check, guided connection review, scoped agent enrollment, revocation, a request inbox, and redacted activity.

The app uses ContextForge as an internal credential broker. This is not yet a general-purpose or multi-tenant release. A pre-provisioned broker workspace is required; UniFi, arbitrary service setup, role management, hosted OAuth-client compatibility, and skill distribution remain future work.

See [installation, runtime connection, and limitations](docs/PREVIEW.md), [live verification results](evaluation/RESULTS.md), and the [connection evaluation](evaluation/README.md). Runtime dependencies and container images are pinned. No service credentials belong in this repository.

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
