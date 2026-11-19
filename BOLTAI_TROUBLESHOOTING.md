# BoltAI attachments and large tool results

## 2026-09-11 findings

Two screenshots represented different failures. The model itself was able to request
a tool. Harness logs show the initial request completing with 784 input tokens and
177 output tokens; the subsequent request contained **153,027 input tokens** and was
rejected before generation. Request ID: `fcb4b0d9-88e2-4eda-88cb-cf97087351fc`.
The preceding tool preset allowed 32,768 total tokens, reserving 4,096 output and 256
margin (28,416 usable input). The current user turn included its returned tool result;
history compaction deliberately protected that whole exchange and therefore could not
help. The payload was not retained, so the exact fetched page contents cannot be
reconstructed from those logs. The screenshot shows a web-fetch action.

The backend advertised **75,000** on the investigation check. Even simply raising the
profile limit to the backend capacity could not fit that 153,027-token input. vLLM's
attached logs show successful HTTP requests/tokenization and engine metrics, not an
OOM or parser exception explaining this rejection. A successful direct connection
is not proof of an identical submitted prompt: client tool output/conversion and
harness policy can differ. The logs do not contain both raw requests for comparison.

## Fix: bounded tool-evidence summaries

`local-tools` now uses a 131,072 context ceiling for Qwen too, dynamically capped to
vLLM's advertised capacity (currently 75,000). Other Qwen profiles retain their
previous windows and sampling. vLLM launch flags, database and credentials are unchanged.

`compaction.summarize_tool_results: true` is enabled only on `local-tools`. If the
current tool exchange exceeds usable input, the harness summarizes its largest tool
results as evidence. It preserves the current user text, assistant call IDs/arguments,
and result links. Small results stay verbatim. Older history continues through the
existing compaction path when needed.

The existing rolling summarizer is shared: every source chunk must be processed,
using exact input counts, no executable tools, thinking disabled for the Qwen recipe,
complete bounded summaries, up to eight total summary calls and a shared 180-second deadline on `local-tools`.
Evidence chunks have at most 32,768 input tokens (also capped by the model window),
avoiding repeated near-75k-context inference. Evidence and history consume the same
work budget. Other profiles retain their four-call/90-second limits. Sources larger than one model
window are chunked; there is no silent head/tail clipping. This bounds work rather
than promising every possible result can be handled.

Evidence summaries include a clear lossy-source notice in the replacement tool text.
The final answer's visible notice identifies summarized tool evidence; omitted exact
details remain unverified. Summary instructions preserve relevant source URLs, dates,
version strings and qualifications, but model summaries are not lossless evidence or
proof of factual accuracy. For exact quotations or exhaustive source review, fetch a
smaller relevant excerpt. A tool schema/user question that itself exhausts the window,
failed summary, or exceeded work budget still yields an explicit error.

Headers add `X-Harness-Summarized-Tool-Results`. Logs now include input budget, total
window, message count and aggregate tool-result bytes, without source text. All summary
token usage continues through `harness_usage` and structured compaction diagnostics.
Repeated client requests can summarize the same content again; no cache or persistence
was added. Prefer targeted API records or smaller pages to avoid this work entirely.

## Markdown reported as application/octet-stream

The owner identified the attachment as Markdown from the vault stored in BoltAI's file
system. Inspection of the installed application's bundled provider-conversion code
found the exact exception text: its OpenAI-compatible conversion rejects non-image
file parts before constructing/sending the HTTP request. This is a client-side file
conversion limitation; making the harness accept arbitrary binary input cannot fix
an exception raised before transmission. The actual file's contents were not inspected.
Upstream context: [AI SDK compatible-message converter](https://github.com/vercel/ai/blob/main/packages/openai-compatible/src/chat/convert-to-openai-compatible-chat-messages.ts).
The installed bundled version may differ from the latest upstream code.

Workarounds:

1. Start a fresh chat with the stored binary attachment excluded from project/chat
   context, and paste the Markdown **contents as text**.
2. Or use a file-read/MCP tool that returns the Markdown as text rather than as a file
   attachment. The new tool-result handling can summarize an oversized text response.

Renaming `.md` to `.txt` or changing only its MIME label is not a reliable remedy for
an adapter that rejects non-image file parts. The harness now also accepts OpenAI
content arrays containing only `{type: text, text: ...}` blocks and concatenates them
in order. This supports client-side text extraction; it does not claim binary upload,
PDF parsing or vision support. Mixed file/image/audio blocks are rejected, never dropped.
The installed BoltAI application and its private project data were not modified.

## Operator rollback

Harness host archive: `/root/harness-before-evidence-fix-20260911.tar`. Restore into
`/root/local-ai-harness` and rebuild/restart for the prior runtime. To disable only
evidence summaries, set `local-tools.compaction.summarize_tool_results: false` and
restart; large current results can then be rejected again. The larger profile ceiling
can independently be reverted in its Qwen preset. No database rollback is required.

The first live 153k-token fixture timed out at the earlier 90-second budget after one
near-74k-token summary call. Smaller evidence chunks and the explicit eight-call/180s
profile allowance address that observed workload. The whole request remains bounded
by the existing 300-second deadline; align the client's timeout with long operations.

## Final validation

179 tests passed, including disposable PostgreSQL and the existing identity/memory/
research/streaming checks. New cases cover complete large evidence processing, source
chunk ceilings, tool-call/result link preservation, explicit failure on incomplete
summaries, work limits, protected user questions, multiple results, text blocks, and
rejection of mixed binary/multimodal blocks.

The live fixture contained 153,882 prompt tokens before reduction, including a
306,225-byte tool result. With 32,768-token evidence chunks it completed five summary
calls in 59.88 seconds before response headers; total reply time was 61.42 seconds.
It preserved synthetic stable version v1.2.3, its source URL, home RTX 5090 / work
RTX A4000, and an end-of-source validation marker. Final generation used 990 prompt
and 97 output tokens; summaries used 154,883 prompt and 565 output tokens. Combined
work: 156,535 tokens. This is a synthetic, filler-heavy test, not a general latency or
summary-accuracy guarantee. Initial summary work is still performed before normal
chat response headers: UI/proxy timeouts must allow it; use focused results for speed.

Live plain-text Markdown blocks also passed. No private vault file was submitted as
a test, no real search provider was called, and no persistent memory was saved. The
binary attachment path itself remains a BoltAI-side limitation, with the workarounds
above; it was not represented as fixed by the server change.
