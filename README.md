# Home Agent Tools

An open-source, self-hosted connection manager for AI agents.

**Connect your services once. Give each agent the tools and knowledge it needs. Manage access in one place.**

## Project status

Planning and evaluation. There is no installable application or production release yet. Features described below are planned, not implemented. We are evaluating existing MCP gateways before choosing the implementation foundation.

## Vision

Home Agent Tools aims to provide a management website and authenticated MCP interface for:

- Service connections, OAuth refresh, connection health, and reconnect flows.
- Individually enrolled agents with scoped access and revocation.
- Shared skills, operating instructions, and context from Git repositories, including self-hosted Gitea.
- Pocket ID integration, with standards-based identity boundaries.
- Straightforward self-hosting, persistent storage, and documented backups.

Initial integration targets are UniFi, Home Assistant, and Gitea. The architecture should support other services without depending on a particular household, AI provider, or model. Compatibility will be tested per runtime; MCP support alone does not guarantee every authentication or skill-loading feature works.

## Design documents

- [Product plan and roadmap](docs/PLAN.md)
- [Selected UI direction](docs/UI-DESIGN.md)
- [Architecture and Pocket ID](docs/ARCHITECTURE.md)
- [Existing gateway evaluation](docs/GATEWAY-EVALUATION.md)
- [Security design](docs/SECURITY-DESIGN.md)
- [Contributing](CONTRIBUTING.md)

## First success criterion

Two distinct runtimes can access the same permitted live inventory without receiving upstream service credentials. Revoking one enrollment blocks its subsequent calls without disconnecting the other.

GitHub is the primary source, issue tracker, and review location for this project. Deployment credentials and private inventories must remain outside this repository.

## License

[MIT](LICENSE).
