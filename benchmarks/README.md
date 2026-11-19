# Harness benchmarks

A benchmark here is a fixed prompt, run the same way several times, so that a change to a
prompt, skill, model or setting can be judged against earlier runs rather than by feel.
Each benchmark has a prompt file (the exact text to paste, plus setup and an answer key)
and a results file (every recorded run, oldest first, with what changed after it).

| Benchmark | Prompt | Results | What it tests |
|---|---|---|---|
| RAG capacity and reasoning | [v1](rag-capacity-reasoning-prompt.md), [v2](rag-capacity-reasoning-prompt-v2.md), [v3](rag-capacity-reasoning-prompt-v3.md), [v4](rag-capacity-reasoning-prompt-v4.md) | [results/rag-capacity.md](results/rag-capacity.md) | Multi-step calculation with real code execution, printed numbers and strict formatting rules |
| DisplayLink dock | [it-dock-displaylink-prompt.md](it-dock-displaylink-prompt.md) | [results/it-dock-displaylink.md](results/it-dock-displaylink.md) | Whether the `it-troubleshoot` agent follows an attached vendor guide over its own product beliefs |
| Intune rename RPC error | [it-rename-rpc-prompt.md](it-rename-rpc-prompt.md) | [results/it-rename-rpc.md](results/it-rename-rpc.md) | Whether the `it-troubleshoot` agent reasons correctly from a pasted log when no document covers the case |

## What the runs have shown so far

**RAG capacity (v4).** Both recorded v4 runs matched every value in the answer key. The
remaining failures are about showing work: numbers computed in prose instead of printed by
the code, and comments dropped from the code shown. The harness's code and number checks
catch most of this, but not small integers or dropped comments.

**DisplayLink dock.** Information beat rules. With the full vendor manual attached, both
engines made the right first check in 7 of 8 runs; with only a short guide, a wrong product
belief survived every added rule. Rules helped where they govern behavior (quote the
document, take reported versions as given, ask about unclear details), not facts. The next
step is vendor manuals in the team knowledge base, not more rules.

**Intune rename RPC error.** Prompt rules fixed behaviors that repeated: inventing an
attempt count (6 of 6 correct after the rule) and stating error numbers without a source.
Product beliefs, such as blaming the local RPC service, were again left to the knowledge
base. Since ADR-007, runs are also scored on triage: the simple fix within a technician's
reach (re-run the Intune script through its done marker, never by hand) should come first.

## Recording a run

So that runs can be compared, record for each one:

- the harness commit (the run line at the end of every answer shows it) and the profile,
- the model, its quantization, and the server and sampling settings,
- whether reasoning was on, and which tools were actually supplied,
- usage and wall time, and the full output and tool records.

At the temperatures these profiles use, single runs vary widely. Decide on 3 or more runs
per configuration, and don't add a prompt rule for a failure seen once. Add the run to the
benchmark's results file under a dated heading, and say what changed after it.

A prompt file is never edited once runs are recorded against it; a revised benchmark gets a
new version file instead.
