# Private harness benchmarks

## RAG capacity and reasoning consistency

Prompt: [rag-capacity-reasoning-prompt.md](rag-capacity-reasoning-prompt.md).
Saved 2026-10-09 at the owner's request. Wording retained, including “funtional” and
instruction ambiguities; pasted line-break escapes and whitespace normalized.

The owner reports this prompt passed only with reasoning enabled. This is a user-reported
observation, not a controlled result reproduced here. No response artifact or formal
pass/fail rubric was supplied. Saving this fixture did not run the benchmark.

For comparable reruns record the model/revision, quantization, server and speculative
settings, profile/sampling, reasoning mode, input/output limits, tools actually supplied,
compaction behavior, wall time, usage, and the complete output/tool execution records.
The prompt requires actual code execution; displaying code alone does not satisfy it.
Tool availability must be held constant when comparing thinking on/off.

Interpretation notes, separate from the preserved prompt:
- Measured index overhead and heap requirements are not supplied, so reasoning alone
  cannot determine them. The prompt explicitly permits TBD for unavailable values.
- Corpus size in documents cannot be compared directly to an index size in bytes;
  a capacity threshold in consistent units is needed for a defensible crossing year.
- The no-citation rule conflicts with the conditional instruction to cite a measurement.
- Chunk count implies a token-length range under ordinary overlapping chunking;
  an exact document length depends on assumptions about final chunks and boundaries.
- The opening developer style is outside Section 1 even though the final instruction
  refers to Section 1. Preserve that ambiguity when reproducing this original test.

These notes are not an automatic scoring rubric and are not part of the prompt.
Any revised benchmark should use a separate version rather than changing this fixture.

### Version 2

Prompt: [rag-capacity-reasoning-prompt-v2.md](rag-capacity-reasoning-prompt-v2.md).
Saved 2026-10-23 at the owner's request; this is the version in current use. Wording retained
as pasted; whitespace normalized and bullets rendered as `-`. Differences from v1:
- Adds: "§5 must include a sparse/BM25 retrieval stage and show its latency within
  the 200 ms budget".
- The first three bullets are not bold, and the paragraph breaks after the style line
  and before the closing instruction are absent, as pasted.

v1 and v2 results are not directly comparable. The v1 interpretation notes still apply.

Run notes (dated observations from the owner's Strix Halo vLLM server, not controlled results;
Qwen3.6-35B-A3B-AWQ-4bit, MTP=2, tuned MoE kernels; server counters after restart):
- Onyx, 2026-10-23: 2 requests, avg 1,648 prompt / 4,182 generated tokens; decode
  46.9 tok/s; draft acceptance 74.9%.
- Open WebUI, same day, same prompt: 3 requests, avg 6,282 prompt / 2,779 generated
  tokens; decode 37.3 tok/s; draft acceptance 68.2%. The client adds its own requests
  and context, so client choice changes the measured workload.

### Version 3

Prompt: [rag-capacity-reasoning-prompt-v3.md](rag-capacity-reasoning-prompt-v3.md).
Saved 2026-10-23 from the text the owner ran on `local-bench`; wording kept, including
"funtional", "Restate all 8 values" (11 are listed) and the 600-words-per-section target
that exceeds the 2,500-word cap. A stray trailing backtick from the paste was dropped.
Adds a run manifest, numbered hard rules, a PRINTED block, a fixed 2048 GiB RAM ceiling
and a 0.25 heap factor.

Observed on `local-bench` (2026-10-23, harness 4da7d7f–d17be2a): numbers became reliable
once reasoning was medium, but every run showed tidied code rather than the script that
ran ("Code not run as shown: 6 of 6"), one run reformatted its PRINTED block and another
invented one, three different chunk formulas appeared across five runs, and the migration
trigger was asserted ("roughly two years of lead time") rather than computed.

### Version 4

Prompt: [rag-capacity-reasoning-prompt-v4.md](rag-capacity-reasoning-prompt-v4.md).
Written 2026-10-23 to close the gaps v3 runs exposed. Changes from v3:
- Code examples and PRINTED blocks must be contiguous, unedited excerpts of the executed
  script and its stdout, one pair per section (rule 3). The harness's "Code not run as
  shown" line and Python runs panel check this directly.
- The script's first printed line must be `sys.version`, so the manifest can copy it.
- §2 defines the window rule and requires checking the closed form against a direct
  simulation for T = 1..20,000 (mismatches must be 0) and printing both range ends and
  their neighbours. A wrong closed form can no longer pass by verifying itself.
- §6 requires a chosen trigger percentage with its GiB value, crossing year and lead time
  all printed, plus the RAM for every year from trigger to ceiling.
- Numbers as digits only (rule 7), so the harness number check sees every quantity.
- Years counted as n from today (rule 8), removing the assumed calendar baseline.
- §5 latencies are labelled design allocations and both budgets must sum exactly, with
  any margin as its own line. §3 alternatives need printed storage too.
- No typical or ballpark figures for TBD values (rule 5). The closing quotes the ROLE
  text (v3 pointed at Section 1, which does not contain it) and the compliance table
  needs evidence and FAIL for any partial failure.
- "Restate all 11 values"; ~350 words per section to fit the 2,500-word cap.

Answer key (computed independently; any correct run must print these):
| Item | Value |
|---|---|
| Closed form | chunks(T) = 1 if T ≤ 512, else ⌈(T − 512) / 448⌉ + 1 |
| Simulation mismatches, T = 1..20,000 | 0 |
| T range for 23 chunks | (9920, 10368], i.e. 9921–10368 |
| Vectors | 230,000,000 |
| Raw vector bytes | 942,080,000,000 (877.3804 GiB) |
| RAM including heap | 1096.7255 GiB; headroom 951.2745 GiB |
| Ceiling crossing | n = 15.9236, first year 16 |
| Trigger (depends on chosen %) | 80 %: 1638.4 GiB, n = 10.23, year 11, lead 5 years; 90 %: 1843.2 GiB, year 14, lead 2 years |
| Alternatives, if used | float16 438.6902 GiB raw; 384-dim 329.0176 GiB raw |

v3 and v4 results are not directly comparable.

#### v4 baseline: `local-bench`, 2026-10-23

Harness `4c4e299` (sandbox unit `ee83978` on Hermes); `local-bench` with medium reasoning
effort and a fixed 4,096-token thinking budget; model as served by vLLM that day (not
recorded by the run). Usage from `/chat/`: input 49,638 · output 12,024 · total 61,662.
Wall time not recorded.

Shape: 6 `python_run` calls, one per section, all exit 0, no stderr. The script's first
line printed `3.12.15 (main, Oct  6 2026, 02:02:22) [GCC 14.2.0]`.

Against the answer key: all match. Simulation mismatches 0; range 9921–10368 with
22/23/23/24 at the boundaries; RAM 1096.7255 GiB; ceiling year 16 (n > 15.9236); trigger
80 % = year 11 (n > 10.2342), lead 5 years; RAM printed for years 11–16.

Harness checks: no "Code not run as shown" line; PRINTED blocks match stdout line for
line. Unverified: `119.34 · 256 · 53.6% · 80% · 1638.4 · 16384,10`. Inputs: `448 · 21 · 768`.

Failures to compare future runs against:
- Rule 2: 3 derived numbers never printed (119.34 GiB saved, 256 dims, 53.6 % of the
  ceiling). 119.34 was also wrong: 877.38 − 658.04 = 219.34 (corrected 2026-10-23 when the
  next run gave 219.3451; the original review missed the subtraction). The trigger was typed as `Rational(16384, 10)` and printed as `8192/5`, so
  1638.4 GiB was never printed either. (`16384,10` on the Unverified line is the model
  quoting its own code in the compliance table, not a claim.)
- Rule 3: comments in the executed scripts were dropped from the shown code. The code
  check ignores comments by design; only the Python runs panel shows this.
- Rule 5: int8 "adds 2–3 ms of decode latency to every ANN probe" is a ballpark figure.
  The number check skips integers up to 10, so it is not flagged.
- Closing: the compliance table renumbered the hard rules and marked all 9 PASS,
  including rule 2.

#### v4 run 2: after the sandbox number rules, 2026-10-23

Harness `5d03566` (adds: print numbers in the form quoted, test formulas against a direct
count, label chosen values, no ballpark figures). Same profile and server as the baseline.
Usage: input 22,320 · output 11,849 · total 34,169 (baseline 61,662).

Shape: 2 `python_run` calls, both exit 0: sections 2–6 in one script, then section 1.
Python version printed by the tool.

Against the answer key: all match. Mismatches 0; range 9921–10368 with 22/23/23/24;
RAM 1096.7255 GiB; ceiling year 16. Trigger chosen at 75 % = 1536 GiB, first crossed in
year 9, lead 7 years; RAM printed for years 9–16. The trigger was labelled as chosen in
prose and code, and latencies as design allocations.

Harness checks: no "Code not run as shown" line. Unverified: `4096 · 47% · 219.3451 ·
1,073,741,824 · 15.9`. Inputs: `448`.

Compared with the baseline:
- Better: no ballpark figures; chosen values labelled; trigger and lead time computed and
  printed; 219.3451 is correct where the baseline's 119.34 was not.
- Still failing rule 2: 4096 (1024 × 4), 47 % headroom and the 219.3451 GiB saving were
  computed in prose. The prose solves "n > … ≈ 15.9" and "≈ 8.5" were never printed: the
  code found the years with loops, so rule 4's "print the solve" is also unmet (8.5 is not
  flagged because the number check skips values up to 10).
- Rule 3: comments in the executed script were again dropped from the shown code.
- §1: the table has 11 rows but splits chunk size and overlap and omits the heap factor.
- Closing: the compliance table renumbered the rules and marked all 9 PASS.
