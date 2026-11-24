# Decision gate

A small decision model decides, per message, whether a turn needs saved memory and which
of the chat's tool servers it needs. Memory or a server it scores as not needed is
skipped for that request. The aim is fewer unrelated memories in the prompt, fewer tool
definitions sent to the main model, and fewer tool calls that a question didn't need.

It is off unless a profile turns it on.

## How it works

1. The harness works out what the request would use without the gate: memory recall if the
   profile has it, and the servers the chat selected (`X-Harness-MCP`, or `mcp_default`).
2. If any of those are gated, it sends the latest user message to the decision model's
   `/v1/systemone` endpoint with one yes/no question per gated target (`noul` type), and
   gets back a score from 0 to 1 for each.
3. A target scored below `threshold` is skipped for this request: recall is not run, or the
   server's tools and rules are left out of the prompt.
4. The rest of the request runs as usual.

The gate only narrows. It never turns on memory the profile lacks, or a server the chat
turned off. A memory save command (`Remember: ...`) skips the gate, since the harness
answers it without generation.

If the decision model is not configured, slow (past `timeout_seconds`), down, or returns
something unexpected, the request runs as if the gate were off. A gate failure never
blocks or fails a chat.

## Turning it on

Set the decision model's URL in `.env`:

```bash
HARNESS_DECISION_URL=http://<decision model host>:8090/v1
# Only if the decision server was started with --api-key.
HARNESS_DECISION_API_KEY=
```

The harness uses a separate HTTP client for it, so `GEN_API_KEY` is never sent there.

Then add `decision_gate` to a profile, usually in `profiles.local.yaml`:

```yaml
decision_gate:
  enabled: true
  memory: true            # may skip memory recall (default true)
  servers: [vault, rag]   # servers the gate may drop; others always run when selected
  skills: false           # true: pick the workflow on Automatic chats (see below)
  threshold: 0.5          # skip a target scoring below this
  timeout_seconds: 2.0    # past this, the request runs ungated
  questions:              # optional: replace the built-in question for a target
    vault: "Does answering this need the user's own notes in their Obsidian vault?"
```

`servers` may only name servers listed in the profile's `mcp_servers`. A server left out
of `servers` is never dropped by the gate. Leave out a server whose misses are costly; for
example, leave `web` out if a chat that turned web search on should always keep it.

The built-in questions are in `decision_gate.py` (`QUESTIONS`). Each asks whether
answering the user's request needs the target, not what the tool does.

## Choosing the workflow (skills)

With `skills: true`, the gate also picks the workflow on chats left on **Automatic**.
Without it, the harness sends every skill the profile has and the main model decides which
one, if any, applies. With it, d1 scores one question per skill, and the harness sends:

- only the highest-scoring skill, when it scores at or above `threshold`, with a line saying
  the harness selected it, or
- no skills section at all, when none does.

```yaml
decision_gate:
  enabled: true
  servers: [vault, web]
  skills: true
  questions:
    skill:apa-review: "Is the user asking you to check APA formatting of citations or references?"
```

It applies only when the chat is on Automatic: never with a `/skill` command, a workflow
picked in the chat, a personal skill, or a profile with `default_skill` (a profile with a
default workflow cannot turn it on). If d1 fails, every skill is sent as before.

**A workflow keeps its tools.** Servers a skill depends on (`SKILL_SERVERS` in
`decision_gate.py`; today `vault-research` needs `vault`) are never dropped while that skill
applies: chosen with `/skill` or the picker, set as `default_skill`, or picked by the gate.
Before this rule, the gate could pick Vault Research and drop the vault in the same request,
leaving the model with the workflow's instructions but only RAG and web to search.

The bundled skills have hand-written questions (`SKILL_QUESTIONS` in `decision_gate.py`).
Any other skill gets a question built from its title and first sentence. In testing on the
three school workflows, the hand-written questions picked the right one, or none, for 10 of
10 messages; the generated ones got 7 of 10, mistaking APA checks and a peer response for a
review. Write a `skill:<id>` question for a skill whose first sentence describes its format
rather than when to use it.

The prompt for each choice (no skill, or each single skill) is built at startup, so a
request only switches between them. `X-Harness-Skill-Selection` still reads `auto`.

## Checking what it decided

Each response carries:

| Header | Value |
|---|---|
| `X-Harness-Decision` | `disabled`, `not_needed` (nothing to gate), `not_configured`, `unavailable` (failed open), or `decided` |
| `X-Harness-Decision-Scores` | When decided: `memory=0.79,vault=0.12` |
| `X-Harness-Decision-Skipped` | When decided: the skipped targets, or `none` |
| `X-Harness-Decision-Skill` | With `skills: true`: the skill sent, or `none` |
| `X-Harness-Memory-Status` | `gated` when the gate skipped recall |
| `X-Harness-MCP` | The servers that actually ran, after the gate |

The harness log has one `decision_gate` event per gated request with the scores,
threshold and elapsed time. It never logs message text.

## Limits

- Only the latest user message is scored. A follow-up such as "and the other one?" carries
  little signal by itself, so it may score low for memory a longer conversation would need.
  Lower the threshold, or leave a target ungated, if misses show up.
- The gate adds one decision-model call before generation: about 0.3 s for two questions
  and 0.5 s for five on a 4 GB laptop GPU running a 2B model.
- In testing, memory, vault and web separated cleanly (needed: 0.77 to 0.97; not needed:
  0.00 to 0.24). The knowledge base and Python scored low even on questions that would
  use them: a Windows how-to scored 0.28 for `rag`, and a unit conversion scored 0.12 for
  `code`. Leave `rag`, `kb` and `code` out of `servers` unless your own scores say otherwise.
- The vault is hard to call from one message. On 2026-11-23 the original notes-only question
  dropped the vault on every real home-lab request on `local-general` (scores 0.08 to 0.45).
  The rewritten question, which names the home lab, keeps it for most such requests (13 of 14
  test messages) but still misses ones without "my", such as "Which containers run on node2?".
  The vault is local and free, so dropping it saves only a few tool definitions. Leave `vault`
  out of `servers` on any profile where home-lab or note research is a main use.
- Scores are tuned by the decision model, not the harness. Check the logged scores for a
  week of real use before raising the threshold.
- Recall itself is still lexical (see [memory.md](memory.md)). The gate decides whether to
  look, not what is found.
