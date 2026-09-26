# Install once, authorize in your browser

Home Agent Tools 0.2 adds browser-based agent authorization and a local connector. Pocket ID authenticates the person; the application records an explicit, separately revocable approval for each agent. Home Assistant and Gitea still authorize their own upstream accounts.

This remains a single-operator preview. The app must already be deployed with its private ContextForge broker and an explicit operator allowlist. It is not a public multi-tenant authorization service.

## One-command installation

From this checked-out repository, run:

```sh
./install.sh --server http://localhost:4444
```

The installer uses `uv` if available, otherwise Python 3.12. It creates a private environment under `~/.local/share/home-agent-tools`, installs a `home-agent-tools` launcher under `~/.local/bin`, and starts setup. Add that bin directory to your PATH if it is not already there. Git is required when installing without a checkout.

For this unmerged preview, a remote installer is available on the feature branch:

```sh
curl -fsSL https://raw.githubusercontent.com/potseeslc/home-agent-tools/codex/browser-agent-setup/install.sh | sh -s -- --server http://localhost:4444 --clients codex
```

Review the script before running it. For reproducible installation, replace the branch in the URL with a reviewed commit SHA and pass the same SHA as `HAT_REF` to `sh`. This repository is the distribution source; no package has been published to PyPI.

Once installed:

```sh
home-agent-tools setup --server http://localhost:4444 --clients codex claude
```

Setup opens a separate authorization for each selected client. Match the verification code shown in your terminal with the browser, sign in through Pocket ID, choose the connected services, and approve 30 or 90 days. A service without personal authorization can be connected from that screen. The connector receives credentials through a one-time local callback; nothing needs to be copied from the browser.

The default is a **fixed 90-day approval**. Select 30 days with `--days 30` or choose a shorter period in the browser. Access tokens last at most ten minutes and renew within that fixed deadline. Activity never extends the deadline. Use `setup --renew` to explicitly authorize a new period; the connector attempts to revoke the previous approval after replacement. If that server is unavailable, the CLI asks you to revoke the old grant in its dashboard.

### Supported client configuration

- **Codex:** uses the documented `codex mcp add` command to register a stdio connector. The Codex CLI must be installed. Existing unrelated servers/settings are preserved, and the prior configuration is backed up.
- **Claude Desktop on macOS:** merges one entry into `claude_desktop_config.json`, preserving unrelated servers/settings and making a private backup.
- **Other stdio clients:** `--clients generic` writes a small MCP configuration file beside the protected profile. Import that configuration into your client.

The CLI runs on macOS and Linux. Claude Desktop's automatic configuration adapter is macOS-specific; Windows setup is not implemented. Configuration adapters and protocol tests are not a claim that every product/version is certified. Clients may require a restart or their own tool approval. This does not change any client's approval policy.

The configuration contains a connector command and private profile path, not bearer credentials. Profiles under `~/.config/home-agent-tools` are mode 0600 in a mode 0700 directory. Each client gets its own profile. Processes running as the same OS user can still read that user's files; per-agent grants do not provide OS process isolation.

### Existing remote MCP clients

OAuth-capable native clients may connect directly to `<server>/mcp`. The app exposes protected-resource metadata, authorization-server metadata, loopback-only dynamic client registration, S256 PKCE authorization codes, token exchange, rotating refresh tokens, issuer-bound responses, and revocation.

Only native loopback callbacks are registered in this release. Hosted clients, browser SPAs, public callback URLs, client metadata document fetching, and arbitrary redirect destinations are not supported. The local connector gives stdio clients the same browser approval flow without requiring built-in OAuth support.

## Personal Home Assistant connection

Configure a fixed `HAT_HOME_ASSISTANT_URL` on the server. Use HTTPS; an existing trusted private HTTP instance requires explicit `HAT_ALLOW_HTTP_HOME_ASSISTANT=true`. This is an administrator setting, never a user-supplied arbitrary outbound URL.

Choose **Sign in with Home Assistant** in the app. You authenticate to Home Assistant using its supported login methods. The callback exchanges the code server-side, verifies the actual account with `auth/current_user`, and stores its access/refresh credentials encrypted and bound to your local operator UUID. The fixed availability tool then uses that personal authorization. There is **no fallback to the old shared Home Assistant token**.

Home Assistant controls the permissions and lifetime of its upstream credentials. Its token can carry more authority than this app's availability tool. The app still exposes only its reviewed read tools. Pocket ID login to the hub does not turn a shared credential into a personal credential, and it does not automatically add Pocket ID as a Home Assistant login provider.

Reconnect pauses existing grants containing that service before replacing its authorization. After reconnect, verify the account and authorize those agents again. Disconnect blocks app access and requests provider revocation. If the provider cannot be reached, remove the application's refresh token from your Home Assistant profile too.

## Three independent lifetimes

| Layer | Behavior |
|---|---|
| Browser dashboard session | Controlled by the existing Pocket ID/broker session policy; may expire sooner |
| Agent approval | Fixed 30 or 90 days; individually revocable; requires new browser approval at expiry |
| Upstream connection | Access tokens refreshed where supported; provider revocation/expiry can require an earlier login |

Closing your browser or signing out of the dashboard does not revoke approved agents. Revoke an agent under **Agents** to stop subsequent calls. Calls already executing may finish.

If refresh fails, the connector reports that sign-in is needed. Run `home-agent-tools setup --renew` for an expired agent approval. For an upstream service failure, use the owner's connection request link and reconnect that service. The bridge does not open a browser unexpectedly during background tool calls.

## Storage and operations

- ContextForge continues to hold Gitea's provider authorization.
- The app encrypts its scoped broker credentials and personal HA credentials using Fernet, with a domain-separated HKDF key derived from `HAT_SESSION_SECRET`. Preserve that secret with encrypted backups. Changing it without migrating/re-authorizing credentials makes the stored connections unreadable.
- OAuth access/refresh tokens and authorization codes are stored as hashes. Refresh tokens rotate atomically; reusing a consumed refresh token disables its agent grant. Local profile locking serializes refresh across connector processes.
- OAuth `/revoke` blocks the local agent grant; dashboard revocation also attempts broker-token revocation. The broker remains internal-only so this cannot be bypassed by calling it directly. Automatic broker-token cleanup after an OAuth-only revoke is not implemented; those encrypted internal tokens expire at their original deadlines.
- Registration and token endpoints have bounded request sizes and basic per-process rate limits. Registrations accept only loopback callbacks and have a bounded registry. This is not a substitute for production authorization-server security review.
- Keep the deployment single-process while using the in-process provider refresh locks and rate limiter. SQLite serializes token/code consumption, but a horizontally scaled deployment requires coordinated provider refresh and rate limiting.
- Back up both databases and the private encryption configuration. Disable restored grants before serving an old snapshot, so a backup cannot resurrect revoked approvals.

## Verification

Run `pytest -q`. Tests cover OAuth audience/PKCE/redirect binding, ownership and browser binding, denial, scope/lifetime limits, code replay, refresh rotation/replay, fixed expiry, dashboard logout independence, personal HA isolation and failed refresh, encrypted storage, client configuration preservation, and a real loopback HTTP → simulated browser approval → stdio connector journey.

The automated provider/identity broker is simulated. Real Pocket ID sign-in, actual provider consent, and each installed client still need live verification. Do not claim a personal HA connection before the user finishes its sign-in and the returned identity is verified.

Protocol references: [MCP authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization), [Home Assistant authentication](https://developers.home-assistant.io/docs/auth_api/), [Codex MCP configuration](https://developers.openai.com/codex/mcp/).
