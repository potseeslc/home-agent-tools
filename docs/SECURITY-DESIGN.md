# Security design

> Implementation status: a single-operator application preview now exists. See [what is implemented and how to run it](PREVIEW.md). This document also describes future capabilities and is not a release claim.

These are requirements for implementation, not claims about an existing application.

- Start with read-only, individually enrolled clients. Enforce permissions on every call, including direct calls to tools omitted from discovery.
- Restrict both operation and target. Permission to control one light must not imply unrestricted Home Assistant service access.
- Keep credentials out of tools, skill files, logs, Git, and client responses. Encrypt recoverable upstream credentials; hold the key separately from the database and backups.
- Keep agent and upstream credentials separate. Validate issuer, audience, expiration, and scope; reject ID tokens used as API credentials.
- Make revocation local and explicit. Test account/group-change propagation instead of relying solely on token expiry.
- Avoid arbitrary shell and HTTP tools. Administrator-configured destinations must be validated, including redirects and OAuth discovery; allow required private services explicitly without permitting arbitrary internal destinations.
- Treat skills, repository content, and tool outputs as untrusted input. They cannot grant permissions.
- Bind sensitive approvals to exact arguments, target, agent, expiry, and a single execution. Do not blindly retry writes with unknown outcomes.
- Protect the administrative UI separately. Remote MCP access needs protocol-compatible authentication; a browser login wall is insufficient.
- Use bounded requests, timeouts, rate limits, and isolated adapters. Do not require privileged containers, broad filesystem mounts, or the host Docker socket for a deployment without an explicit isolation design.
- Retain redacted audit events and provide per-agent disable and emergency write-disable controls.
- Test dependency updates and encrypted recovery. Read-only household state remains sensitive data and needs access controls.

See [MCP security guidance](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices).
