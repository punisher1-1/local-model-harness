# Documentation

Start with the [README](../README.md) for what the harness is and how to run it. The pages
below go deeper. Each folder holds one kind of page, so you can tell a how-it-works page
from a design idea or a decision record.

## Guides

| Page | Read it when |
|---|---|
| [team-deployment.md](team-deployment.md) | You run the harness for a team: sign-in, the team knowledge base, backups, updates |
| [school-and-general-profiles.md](home/school-and-general-profiles.md) | You want the school and general knowledge profiles at home |

## Reference: how each feature works

These describe features that are built and running.

| Page | Covers |
|---|---|
| [identity.md](reference/identity.md) | Sign-in modes, groups, and what each person may use |
| [skills.md](reference/skills.md) | Markdown skills the harness loads, and who may use them |
| [tools-and-models.md](reference/tools-and-models.md) | Client tools, profile IDs and automatic model selection |
| [vault-mcp.md](reference/vault-mcp.md) | The vault tool server and turning tool servers on or off per chat |
| [memory.md](reference/memory.md) | Persistent memory on ParadeDB |
| [decision-gate.md](reference/decision-gate.md) | A small decision model that skips memory or tools a message doesn't need |
| [compaction.md](reference/compaction.md) | Summarizing long chats so they fit the model's context window |
| [research.md](reference/research.md) | The harness's own tool loop and the demo research profile |
| [telemetry.md](reference/telemetry.md) | Token usage, KV cache statistics and metrics |

## Decision records (ADRs)

An architecture decision record explains one decision: the problem, the options, what was
chosen and why. They are kept as written, even after later decisions change them, so the
reasoning stays visible. A newer ADR says which older one it replaces.

| ADR | Decision |
|---|---|
| [ADR-001](adr/ADR-001-identity-boundary.md) | Service-key and verified-JWT identity modes |
| [ADR-002](adr/ADR-002-persistent-memory.md) | Explicit memory stored separately on ParadeDB |
| [ADR-003](adr/ADR-003-code-sandbox.md) | Model-run Python in a separate sandbox VM |
| [ADR-004](adr/ADR-004-oidc-sign-in.md) | People sign in with OIDC; apps keep a scoped service key |
| [ADR-005](adr/ADR-005-web-read-seen-urls.md) | `web_read` fetches only URLs the harness has already seen |
| ADR-006 | Not in this repository. ADR-007 refers to its planned knowledge loop |
| [ADR-007](adr/ADR-007-triage-within-access.md) | The IT troubleshooting agent triages within the technician's access |
| [ADR-008](adr/ADR-008-team-knowledge-base.md) | Team knowledge base inside the harness (SQLite FTS5) |

## Design ideas (not built)

| Page | Covers |
|---|---|
| [role-agents.md](design/role-agents.md) | Future role-scoped agents, such as payroll or help desk |

## Troubleshooting

| Page | Covers |
|---|---|
| [boltai-attachments.md](troubleshooting/boltai-attachments.md) | BoltAI attachments and oversized tool results |

## Elsewhere in the repository

- [frontend/README.md](../frontend/README.md): the `/chat/` app
- [sandbox/README.md](../sandbox/README.md): the Python sandbox and web search servers
- [benchmarks/README.md](../benchmarks/README.md): benchmark prompts and results
