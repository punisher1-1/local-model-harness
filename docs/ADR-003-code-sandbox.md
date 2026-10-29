# ADR-003: Model-run Python sandbox on the Hermes VM

**Status:** Accepted; implemented in `sandbox/` and `code_mcp.py`, pending deployment on Hermes
**Date:** 2026-10-15
**Deciders:** Project owner

## Context

In the owner's test prompt, models given a code interpreter (as in Open WebUI) answered
correctly. Without one, they produced broken code and wrong math. The harness can call
MCP servers through reviewed adapters (`mcp_registry.py`) and shows them as per-chat
Tools chips in `/chat/`, but it has no way to run code today.

The Hermes VM (the sandbox VM, `<sandbox host>`, 4 vCPU, 4 GB RAM, 64 GB disk,
Proxmox firewall on) is mostly idle. pve1 is at about 95% RAM, so the VM keeps 4 GB.

Decisions already made:
- **The model runs the code**, not the user. There is no terminal pane.
- **Python only:** Python 3.12 with numpy, pandas, sympy and matplotlib.
- **Hermes is repurposed** as a dedicated sandbox host. Whatever runs there now is stopped.
- **No network** from inside the sandbox. Packages are baked into the image.

## Decision

Run a small FastMCP server on Hermes that exposes one tool, `python_run`. Each call
starts a fresh, locked-down Docker container from a prebuilt image, runs the code, returns
the output, and removes the container. The harness adds a `code` adapter to the MCP
registry. It appears as a **Python sandbox** chip next to Local_AI_Vault on local-tools,
local-home and local-work.

```text
/chat/ ──► harness (the harness host) ──MCP + bearer token──► sandbox server (Hermes :8202)
                │                                      │ docker run --rm --network none ...
                └── adapter checks code size, ◄── output ─┘ one container per call
                    caps output, logs metadata
```

Runs are **stateless**: variables do not carry over between calls, the same as one cell
per run. A model that needs earlier results re-runs them in one script. Keeping state
per chat would need long-lived containers, which is deferred.

## Tool contract

`python_run(code: str)`, at most 20,000 characters. The response, after the harness caps it:

```json
{"stdout": "...", "stderr": "...", "exit_code": 0, "timed_out": false,
 "truncated": false, "duration_ms": 412}
```

- stdout and stderr are capped at 16 KB each; `truncated` reports when output was cut.
- Charts: matplotlib uses a non-interactive backend, and images are not returned in v1.
  The model reports numbers and tables instead.
- Model rules: use `python_run` to check arithmetic, statistics and code behavior, rather
  than estimating. Quote real output, never invent results. Say when a run failed or
  timed out. Code is untrusted output from the model, so it never touches the host.

## Sandbox controls (per container)

| Control | Setting |
|---|---|
| Network | `--network none`, so no internet, LAN, or harness access |
| Filesystem | `--read-only` root; `--tmpfs /work:size=64m,noexec,nosuid` as the working dir (Python reads scripts, it does not exec them) |
| User | non-root uid 10001 inside the image; `--user 10001:10001` |
| Privileges | `--cap-drop ALL`, `--security-opt no-new-privileges` |
| Resources | `--cpus 1`, `--memory 512m --memory-swap 512m`, `--pids-limit 64` |
| Time | 30 s wall clock, enforced by the server; the container is killed and removed |
| Lifetime | `--rm`; a sweeper removes any container left by a crash |
| Concurrency | at most 2 runs at a time; extra calls get a "busy, retry" error |
| Image | `harness-sandbox:py312`, built on Hermes, pinned digest recorded |

Future hardening: switch the runtime to gVisor (`--runtime runsc`), so the container also
sits behind a userspace kernel. It's optional for a single-user lab VM but cheap to add later.

## Server and network controls (Hermes)

- The FastMCP server runs as a systemd service under a dedicated `sandbox` user. That user
  is in the `docker` group, so it has root-equivalent access to the VM. This is acceptable
  only because the VM is dedicated to the sandbox.
- It listens on TCP 8202. The Proxmox firewall and host firewall allow it **only from
  the harness host** (`<harness host>`). SSH stays as it is today.
- A bearer token is required: the harness sends `HARNESS_CODE_MCP_TOKEN` from the harness host's
  `.env`. The token adds a check against other LAN devices that can reach the VM, but
  the traffic is plain HTTP on VLAN 10, so the firewall rule is the main boundary.
- Logs record the request ID, code length, exit code, duration and timeout, never the
  code or output.
- Hermes has `onboot: false`; set it to start at boot once it is in use.

## Harness changes

- `code_mcp.py` adapter, registered as `code` in `mcp_registry.py`. It holds the tool
  schema and rules, validates arguments, and caps output again on the harness side.
  The endpoint comes from `HARNESS_CODE_MCP_URL`, never from the model or a request.
- Identity: add the `python_run` tool and a `code_sandbox` collection to the grant
  schema. Service-key mode gets both.
- The tool loop's six-call budget and per-round output limits apply as with the vault.
  A run counts as one call.
- Profiles: `mcp_servers: [vault, code]` on local-tools, local-home and local-work. The
  code server is on by default for local-tools, off for home and work.
- UI: the activity footer lists `python_run` calls. The answer quotes the code and its
  output, as the rules require. Live progress cards remain a later UI improvement.

## Options considered

| Option | Isolation | Effort | Notes |
|---|---|---|---|
| Docker per run on a dedicated VM (chosen) | Container + VM boundary, no network | Moderate | Matches the vault MCP pattern; fresh environment per call |
| Jupyter kernel gateway | Process-level; state kept per session | Moderate | Stateful sessions, but a long-lived kernel needs more cleanup and policy |
| Pyodide in the browser | Browser sandbox | Low server work | The harness can't verify runs, and output depends on the client |
| Run in the harness container | Weak | Low | Rejected: untrusted code next to API keys and chat history |

## Consequences

- Models can check math and code against real output instead of guessing.
- The cost is one more host to maintain: the Docker engine, the image rebuild when
  packages change, and the firewall rule.
- Without network access, code can't fetch data or install packages. That's intended.
- Container start adds about 0.5–1.5 s per run.

## Rollout and verification

1. On Hermes: inventory and stop what runs today, then install Docker. Build the image
   and install the server and systemd unit. Add the firewall rule and token.
2. Escape tests, each expected to fail safely: network access (`urllib` to the
   internet and to `<harness host>`), writes outside `/work`, fork bomb, a 1 GB
   allocation, an infinite loop, reading `/etc/shadow`, and a 1 MB print. Correctness
   tests: arithmetic, numpy, sympy, and an exception traceback.
3. Harness: adapter, tests with a fake MCP server, deploy to the harness host, then enable it
   in `profiles.local.yaml`.
4. Rerun the owner's original test prompt with the sandbox on and off, and compare.

Rollback: turn off the chip or remove `code` from `mcp_servers` (the harness keeps
working), or stop the service on Hermes. Calls then fail with a clear error.
