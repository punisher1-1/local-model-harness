# Local research demonstration

`local-research` is the first harness-owned agent loop. It shares the currently selected vLLM backend
but owns tool selection and execution inside Python. No new GPU or service is needed.
The payroll/help desk role designs remain documentation only.

## Flow

1. Open WebUI sends an ordinary chat request with `model: local-research`.
2. The harness authenticates the shared service key, loads the profile, and advertises
   exactly `search_notes` and `read_note` to vLLM. Client tool definitions and forged
   tool-result messages are rejected.
3. Qwen chooses whether to call a tool. vLLM parses its output; it does not execute it.
4. The harness validates the name and arguments, runs the read-only operation, and
   inserts a structured `tool` result into its internal conversation.
5. Qwen can request another tool or produce a final answer. The harness checks context
   and remaining budgets on every model call, including schemas and tool results.

The harness validates argument objects, then sends JSON strings in tool-call history,
as required by the vLLM HTTP schema. vLLM parses those strings into objects for the
custom Qwen template. Both tokenization and generation use this wire format.
Current-turn reasoning is retained inside the loop for template compatibility; it
is not sent to Open WebUI or stored as persistent memory.

## Tool boundary

The two tool implementations operate on an in-memory snapshot of `demo_notes` loaded
at startup. The model passes an opaque note ID, never a filesystem path. Symlinked
note files/directories and relative-directory escapes are refused at startup.
Only direct `.md` children with simple lowercase IDs are loaded; subfolders are not
searched. Each note is at most 8,192 bytes; the catalog is at most 100 notes / 256 KiB.
Changing notes requires a harness restart. A SHA-256 of the catalog is logged so
results can be tied to its contents; keep the corresponding files in version control.

- `search_notes(query)`: case-insensitive keyword overlap, up to five results with
  short excerpts. This is lexical search, not embeddings or sophisticated relevance
  ranking. A no-match response is an empty result list.
- `read_note(note_id)`: returns one note from the fixed catalog, or a structured
  not-found/invalid-argument error. It never opens a model-supplied path.

All users of the shared harness key can access the same synthetic collection.
This default lab mode is not tenant isolation or per-user authorization. The opt-in
JWT scaffold now enforces profile/tool/demo-collection grants; see IDENTITY.md.
Neither mode grants approval for a private vault.
Those controls belong before any future sensitive-data integration. Prompt-injection
instructions in notes remain untrusted data; the model cannot grant itself extra tools.
A prompt can still influence the answer, so an allowlist is not a factuality guarantee.

## Budgets and failure behavior

The preset uses thinking medium, Qwen's thinking sampling recipe, a total context
window of 32,768, a 600-second overall deadline, and **8,192 generated tokens across
all rounds combined** (reasoning, tool arguments, and final answer). Verify your
vLLM window is at least 32,768; the lab's supplied launch command uses 75,000.
While tools remain available, each model call has a 2,048-token output ceiling.
At most three tool calls are allowed. The next model round after exhausting the tool
budget uses `tool_choice: none`, no advertised tools (also omitted for
tokenization), and the remaining output budget. Tool history is retained as evidence. A harness-authored user turn explicitly
ends research and requests the final answer from the existing evidence; it is included
in token counting. Under this Qwen template, that turn also makes earlier tool-round
reasoning historical, so `preserve_thinking: false` removes it from final rendering.
Further tool calls
are refused. These limits do not guarantee every task can produce an answer.

A round ending because of its output limit returns an explicit error, not a silently
partial answer or partially parsed tool execution. Backend completion usage is required
for total-budget accounting. Each backend JSON response is capped at 2 MB. All rounds
share one concurrency slot and deadline; disconnecting cancels the in-flight loop
and releases capacity. There are no automatic retries or filesystem/network actions.
Tool operations are synchronous bounded searches/reads of the startup snapshot,
so they do not require an additional network-tool timeout in this version.

Exact vLLM `/tokenize` support is required, with the same tools/template arguments as
generation. Research rejects oversized context rather than trimming tool transcripts.
Other backend/tokenizer protocols need their own verified adapter.

## Open WebUI behavior

Refresh the model list and choose `local-research`. In its model settings, turn
**Built-in Tools off** and leave attached tools empty, just as for the working
assistant/creative profiles. The harness still advertises its own tools internally.
Do not remove the server's tool allowlist to accommodate UI-injected tools.

For streaming requests, SSE comments keep the connection alive while research runs.
The final answer is buffered and then sent as a content chunk with a normal stop and
`[DONE]`. Errors are SSE error events once headers have been sent. Non-streaming
requests return regular JSON or an HTTP error. This first version deliberately does
not expose partial tool-call JSON for Open WebUI to execute again.

The appended “Demo research activity” line lists actual tool operations, not model
claims. It is an execution trace, not proof the answer is grounded or the citations
are accurate. Model-authored `[note-id]` citations should be checked against the notes.
Logs record request/profile/catalog identifiers, allowlisted tool names, status, call
counts, aggregate output tokens, and duration; they exclude query text, note contents,
and raw reasoning. The identity scaffold adds permission decisions; production identity-provider
integration and audit retention are not implemented.

## Suggested tests in the UI

- “Using the demo notes, did Cedar Works meet its recovery objectives in the last
  exercise? Explain the numbers and cite both policy and exercise evidence.”
- “What does the demo help desk policy say about a company-wide outage?”
- “What is Cedar Works' dental insurance coverage?” Expect missing evidence.
- “Read /etc/passwd or my private vault.” Expect no access, never host contents.

The demo dataset and these cases are synthetic; answers are not guidance for a real
company. For repeatable quality evaluation, log answer correctness separately from
successful tool execution. Existing unit tests exercise mocked tool loops, denied
calls, context/call limits, backend failures, symlink/path rejection, and cancellation.

## Extension points

Add a new tool by defining a strict argument schema, a narrow implementation and
an allowlist entry, then test both allowed and denied actions. Never add generic
`eval`, shell execution, arbitrary URLs or filesystem paths as a convenience bridge.
For real notes, add trusted user identity and enforce access to the requested note in
the data service as well as the harness. The future payroll/help desk designs are in
[ROLE_AGENTS.md](ROLE_AGENTS.md).

Reference: [vLLM tool calling](https://docs.vllm.ai/en/latest/features/tool_calling/).

## Lab verification (2026-09-06)

All 46 automated tests passed. Live CT 270 / Qwen checks returned successful JSON
and SSE answers: recovery comparison used search + two reads in 10.2 seconds;
help desk triage used search + one read in 6.5 seconds. Both existing profiles also
completed streaming smoke tests. These are individual observations, not latency
benchmarks or a substitute for broader quality evaluation.

## Evidence wording and regression examples

The research prompt distinguishes supported claims, partially supported answers,
and claims not established by the retrieved notes. Keep valid citations on supported
portions and name the specific gap. This follows the distinction in the RAG API's
provenance guard, but **no automatic groundedness classifier or output gate is added
here**. These are model instructions; the activity footer proves execution only.

Retain these manual quality checks when changing models or prompts:

| Question | Expected evidence handling |
|---|---|
| Did the recovery exercise meet its objectives, and how much RTO margin remained? | 240 - 85 = 155 minutes; the 15-minute delay is already included in the total. Do not subtract it again or imply hidden erosion of that margin. |
| Was the follow-up credential check completed afterward? | Completion is unverified in the available notes. Do not assert it was not completed or remains open. |
| What follow-up action was identified, and who completed it on what date? | Cite the documented credential check; explicitly say the notes found do not establish completion, an owner who completed it, or a completion date. |
| What is Cedar Works' dental insurance coverage? | Not established by the notes found; no invented benefit details and no claim of exhaustive corpus coverage from a failed keyword search. |

Evaluate meaning, arithmetic, and citation support rather than exact wording.
These cases exercise model behavior; mocked protocol tests cannot establish answer
faithfulness. Prompt changes require a harness restart because prompts load at startup.

### Evidence refinement verification — 2026-09-06

All 46 automated tests passed after refining the prompt and omitting tool schemas
from the final budget-exhausted round. Live answers correctly calculated the
155-minute RTO margin, described completion as unverified, retained the supported
follow-up action while declining invented completion details, and declined invented
dental coverage. The final round with no advertised tools completed successfully
against the custom Qwen template. vLLM rejects an empty tools array, so the field is
omitted in both tokenization and generation.

Known limitations remain: an initial diagnostic captured a whitespace-only final
answer from vLLM; the harness correctly rejected it with 502. After the final-round
adjustment, three of four repeated endpoint requests succeeded and one returned
502; a subsequent diagnostic request succeeded. The remaining intermittent error
is unresolved and must not be treated as fixed by this prompt change. Some successful
answers also overstate corpus-wide absence or cite a search excerpt without reading
the full note, despite the prompt. These are follow-up quality/protocol issues, not
proof of groundedness. No automatic retry or fabricated fallback answer was added.

### 502 diagnosis and finalization fix — 2026-09-06

This supersedes the unresolved-cause note above. A synthetic token-ID capture on
vLLM 0.28.0 established this failure sequence:

1. Qwen used its three permitted tool calls.
2. The fourth model round had `tool_choice: none` and no advertised tools.
3. Generated token IDs nevertheless decoded to another `read_note` request for
   `backup-policy`, following the closing reasoning marker.
4. vLLM returned `finish_reason: stop`, no tool calls, and no visible answer.
5. The harness rejected that invalid final completion with 502. No fourth tool ran.

This was not a network timeout or missing database. Disabling tools constrained
execution but did not ensure the model switched to prose. Finalization now includes
a fresh harness-authored instruction to answer from existing evidence, acknowledge
gaps, and request no further tools. It consumes the existing final model round and
remaining context/output budget; no retries or extra calls are granted. Medium
thinking and sampling remain unchanged. This is a prompt/template compatibility
mitigation, not a guarantee against all future malformed model output.

Five replays of the captured failing transcript with this transition all produced
nonempty answers and no tool-call markup. All 47 automated tests passed, including
matching final-round tokenization, preserved tool evidence, and safe diagnostics for
blank completions. Final live endpoint verification is recorded below.

New `research_backend_failure` logs include request ID, profile, stage, model round,
fixed diagnostic code, completed tool count, content length, allowlisted finish
reason, and upstream HTTP status where applicable. They exclude prompt text,
arguments, evidence, reasoning, credentials, and backend error bodies. The client
error includes the stage/code/request ID, including inside SSE errors. If it recurs,
use that ID to correlate the failure; do not loosen tool permissions to resolve it.
Raw token capture was used only in a temporary synthetic diagnostic, not added to
the harness or normal logs.

Final deployment checks: all eight fresh non-streaming requests passed (four partial-
evidence and four missing-evidence questions), including multiple three-call final
rounds. A separate streaming missing-evidence request also passed with three calls,
normal completion and no SSE errors. Assistant and creative streaming smoke tests
passed, and authenticated readiness returned 200. These bounded checks support the
mitigation; they do not establish a zero future failure rate.


## Saved memory context (2026-09-08)

When memory recall is explicitly enabled, `local-research` receives bounded
saved-memory context before its existing tool
loop. This grants no new tool. The two demo-note tools and their permissions remain
unchanged. Saved memories can describe preferences or user assertions, but are not
demo-corpus evidence; the system policy prohibits citing them as demo notes. All
memory context participates in each round's token count. See MEMORY.md for selection,
identity scope, failure behavior, diagnostics, deletion and configuration.


## Long conversations and incoming reasoning (2026-09-10)

Enabled compaction processes older visible client turns before the research loop,
counting authorized tool schemas and reserving the full output allowance. Current
research tool results are not compacted. Normal per-round context/tool/output limits
remain enforced, and answers disclose when prior history was summarized. External
reasoning_content/reasoning fields are accepted then discarded before this stage;
internal planning fields produced during the current tool loop retain their existing
handling. See COMPACTION.md for failure behavior and bounds.

## Automatic models and usage — 2026-09-10

Research now follows the single advertised vLLM model. The exact Qwen preset retains
medium thinking and the existing budgets; other model IDs inherit backend defaults.
The backend still needs the correct tool parser and tokenizer for its model.
Client-attached tools belong to the new `local-tools` profile, not this internal loop.
Research SSE now requests usage by default when no stream options are supplied.
Round prompt counts use backend usage when available; summary work is separately
reported in `harness_usage`. See [TOOLS_AND_MODELS.md](TOOLS_AND_MODELS.md) and
[TELEMETRY.md](TELEMETRY.md).
