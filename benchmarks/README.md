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

## IT troubleshooting: DisplayLink dock

Prompt, setup, answer key and scoring: [it-dock-displaylink-prompt.md](it-dock-displaylink-prompt.md).
Tests whether the `it-troubleshoot` agent follows an attached vendor guide over its own
product beliefs. Two engines, same prompt, skills and guide, no tools:

- **Qwen:** `qwen3.8-27b` (dense), home lab.
- **Ornith:** `cyankiwi/Ornith-1.5-35B-A3B-AWQ-INT4` (MoE, about 3B active), vLLM on the
  Strix Halo node, LJA lab, with context window 131072, temperature 0.6, top_p 0.95 and
  top_k 20.

#### Before the source rules, 2026-10-28 to 2026-10-30

Harness `8c11e7c` (LJA) and `98e8efc` (home lab). Not controlled: the first Ornith session
was the live case, with the facts spread over several turns and the guide attached at
turn 4. The other two runs used the fixed first message.

- **Ornith, live case:**
  - It said the UD-ULTC4K was "a Thunderbolt dock doing direct video" and told the user
    not to install DisplayLink Manager, against the attached guide.
  - It called a firmware cap "well-known" and "a documented failure mode", with no source.
  - Its write-up repeated both claims and filed the note under a folder per date.
- **Ornith, fixed message:** fail on 1 and 3. It ruled out "driver not installed" because
  one screen worked, and said the guide listed the input-source check first (it is third).
- **Qwen, fixed message:** pass on 1. It added the Screen Recording permission check from
  its own knowledge (correct but unsourced), and ruled out the cable on reasoning.

#### Run 1: source, quote and ruled-out rules, 2026-10-30

Harness `92acb8f`, which adds:
- documents over general knowledge, with unverified product claims labeled;
- quote what an attached document says;
- rule a cause out only by a check that was run;
- the pasted ticket history rule and the most-telling-check rule.

Three runs per engine.

| Run | 1. DL Manager first | 2. Ruled out = none | 3. Quotes first step | 4. Claims labeled |
|---|---|---|---|---|
| Qwen #1 | ✗ | ✗ (inference with a caveat) | ✗ (quoted the cable/input lines) | partly |
| Qwen #2 | ✓ | ✓ on paper; "not installed" dropped silently | ✓ | ✗ (read the USB-B cables as video) |
| Qwen #3 | ✓ | ✓ | ✓ | partly ("all video is software") |
| Ornith #1 | ✗ (cable swap first) | ✓ | ✗ | partly |
| Ornith #2 | ✓ | ✓ | ✓ | ✗ ("doesn't send a native video signal") |
| Ornith #3 | ✓ | ✓ | ✓ | partly (Extensions, not Screen Recording) |

Findings:
- **Quoting predicted the result exactly.** All four runs that quoted the guide's first
  "no video" step made DisplayLink Manager the first check; both that did not, failed.
  Run 2 therefore adds a documented-order rule.
- **Ornith went from 0 of 2 to 2 of 3 on check 1.** At `92acb8f` the two engines score
  about the same; most of the earlier gap was the missing rules.
- **"One screen works, so the driver is present" appeared in 4 of 6 runs, on both
  engines.** This is wrong product knowledge, not a missed instruction. The full manual
  states the driver requirement, so the next variant attaches it instead of the guide.
- **The best single reply was Ornith #3.** It used terminal checks that prove the driver
  state (`system_profiler SPDisplaysDataType`, `ls /Applications | grep -i displaylink`).
  It also noticed the UD-ULTv4k/UD-ULTC4K mismatch, and said a wake from sleep proves
  link detection, not a picture.

#### Variant: full user manual attached instead of the guide, 2026-10-30

Same message and setup, harness `92acb8f`, one run per engine. The attachment is
Plugable's 7-page UD-ULTC4K user manual. It states the driver requirement and the macOS
Screen Recording step; Docling replaces its pictures with placeholders, so they cost
almost nothing.

| Run | 1. DL Manager first | 2. Ruled out = none | 3. Quotes the document | 4. Claims labeled |
|---|---|---|---|---|
| Qwen | ✓ | ✓ | ✓ (two quotes, with sections) | mostly ("Accessibility" and TCC unsourced) |
| Ornith | ✓ | ✓ | ✓ (three quotes) | mostly (read the USB-B cables as video; "current public macOS is much lower") |

- **Both engines pass checks 1 to 3, and both explain the mechanism correctly:** the
  first display uses the native path, and the second is DisplayLink-driven and needs the
  driver and Screen Recording permission. The wrong "one screen works, so the driver is
  present" belief from 4 of 6 guide-only runs did not appear.
- **Conclusion: for product facts, the document fixed what prompt rules could not.**
  Vendor manuals in the knowledge base (the LJA `it` collection) are the larger lever;
  rules keep the model to what those documents say.
- **Ornith doubted the macOS version** from its training data, although the harness gives
  today's date. A user-reported version should be taken as given.
- **Speed:** Ornith on the Strix Halo node felt slower than Qwen (reported, not measured).

#### Full manual, harness `84badb3`, 2026-10-30

`84badb3` adds, on top of `92acb8f`:
- an attached guide's matching first step is the first check (`8a6ea18`);
- no inference under Ruled out and no hypothesis dropped silently (`8a6ea18`);
- take reported versions as given (`84badb3`).

The full manual is attached, with the same message.

| Run | 1. DL Manager first | 2. Ruled out = none | 3. Quotes the document | 4. Claims / misreadings |
|---|---|---|---|---|
| Qwen #1 | ✓ | n/a: **no case log** | ✓ (full Troubleshooting line) | mostly (TCC unsourced) |
| Qwen #2 | ✓ | ✓ | ✓ (three quotes) | ✓ (cable question deferred "for later") |
| Ornith #1 | ✗ (DL ranked #3) | ✓ | ✗ (paraphrase) | ✗ (acted on the USB-A/B misread: cabling ranked #1) |
| Ornith #2 | ✓ ("the manual's first step") | ✓ | ✗ (paraphrase) | ✓ (asked about the cables) |
| Ornith #3 | ✓ | ✓ | ✓ | ✗ (invented an "HDMI-to-USB adapter"; applied the manual's USB-C uplink cable warning to display cables) |

- **The version rule worked in all five runs.** None doubted macOS 27.2, and Ornith #2 wrote
  "taking the version as you reported it".
- **The right first check appeared in 4 of 5 runs.** Ornith #2's hypothesis list still ranked
  cabling first while its check followed the manual.
- **Qwen #1 dropped the case log.** It was the only time across all runs so far, and Qwen #2 restored it.
  If it recurs, a harness check ("Case log missing from this reply") fits better than more
  prompt text.
- **Every remaining error traces to the ambiguous cable sentence**, which Ornith misread in all
  three runs. The next commit adds an intake rule: ask about an unclear detail alongside the
  first check, never rank a cause on it, and never fill it in with hardware the user did not
  mention.

#### Guide only, harness `84badb3` (Qwen) and `09c02b6` (both), 2026-10-30

`09c02b6` adds the intake ambiguity rule. Same guide-only setup as run 1.

| Run | 1. DL Manager first | 2. Inference kept out | 3. Quotes first step | 4. Claims / cable sentence |
|---|---|---|---|---|
| Qwen #1 `84badb3` | ✓ | ✓ | ✓ | ✓ (hedged; flagged the macOS 11–13 vs 27.2 gap) |
| Qwen #2 `84badb3` | ✓ | ✓ | ✓ | ✗ ("does not drive displays natively through the GPU") |
| Qwen #1 `09c02b6` | ✓ | ✗ ("one monitor working proves the app is present") | ✓ | ✗ (acted on the misread: "USB-connected" monitors) |
| Qwen #2 `09c02b6` | ✓ | ✗ ("almost certainly installed") | ✓ | asked about the cables ✓; "cannot drive any display" ✗ |
| Qwen #3 `09c02b6` | ✓ | ✓ | ✓ | ✓ (read the cables correctly) |
| Ornith #1 `09c02b6` | ✗ (monitor input first; DL ranked #3) | ✗ ("driver is probably working") | partly (also said "the guide flags input source first") | labeled its DisplayLink claim as general knowledge ✓; asked about the cables ✓ |
| Ornith #2 `09c02b6` | partly (Displays list first; DL asked) | ✗ ("likely at least partly installed") | ✓ | ✗ (merged "DisplayPort monitors via USB-A-to-USB-B") |
| Ornith #3 `09c02b6` | ✓ (and `launchctl list \| grep -i displaylink`) | ✓ | paraphrase | ✓ (guessed the USB cables are the hub uplinks) |

#### Variant: web search instead of an attachment, harness `09c02b6`, 2026-10-30

Qwen, one run. The model number in the message was corrected to `UD-ULTc4k`, with the
added line "Please use a websearch to verify with the product manual" and no attachment.
Tools: knowledge base and web.

- **Trace `rag_search → web_search → web_read`:** searched the knowledge base first, as the
  skill says, and reported no matching runbook; then searched and read the vendor
  product page.
- **Checks:**
  1. ✓ DisplayLink Manager plus Screen Recording first.
  2. ✓ Ruled out "none yet".
  3. ✓ Quoted the product page ("DisplayLink software is required… Manual installation is
     required for macOS"; "Screen Recording permission is required by the driver").
  4. ✓ Labeled its explanation of the native-plus-DisplayLink split as "my
     interpretation"; asked about the cables ("don't guess").
- **One unquoted detail:** the chip model in the case log (`DL-6950`).
- **The best reply of the test, and it confirms the conclusion below.** Given the
  vendor's own page, the model got the product facts right. The cost is paid web-search
  credits and egress. The LJA lab has no web tool, so its equivalent is the vendor
  documentation in the knowledge base.

#### Web search on both engines, harness `dcad7f6`, 2026-10-30

Same message as the web-search variant (corrected model number, "Please use a websearch to
verify with the product manual", no attachment). Ornith now has web search at LJA too.
`dcad7f6` makes bad tool calls report which fields to remove, add or fix.

| | Tool calls | 1–3 | Notes |
|---|---|---|---|
| Ornith, `09c02b6` | `web_context → web_read ✗ → web_read ✗ → web_search` | ✓ | Gave up on `web_read` after two bare `invalid_arguments` errors |
| Ornith, `dcad7f6` | `web_search → web_read ✗ (invalid_arguments) → web_read ✗ (http_status) ×2 → web_read` | ✓ | Corrected its arguments after the new error detail; the `http_status` errors were pages refusing the request |
| Qwen, `dcad7f6` | `web_search → web_read` | ✓ | Two calls; quoted the product page, the FAQ entry for this symptom and DisplayLink Manager 17.0 support for macOS 27 |

- **Both engines found the exact mechanism from the vendor's pages:** Display 1 native
  (Alt Mode), Displays 2–3 through DisplayLink, and Screen Recording permission required.
  Without retrieval, neither engine got this reliably.
- **Qwen needed 2 web calls, Ornith 5,** which matters for credits and speed.
- The cable sentence was asked about in both, and the driver stayed the top hypothesis.

### Conclusion of the DisplayLink dock test

- **Information beat rules.** With the full manual, both engines made the right first check
  in 7 of 8 runs and explained the dock correctly. With the short guide, the belief "one
  screen works, so the driver is present" survived every rule. It moved from Ruled out into
  the reasoning ("proves", "almost certainly", "probably working") and showed up in 5 of 8
  final-round runs. Rules can move a wrong product belief around, but only a document
  removes it.
- **Rules earned their place where they govern behavior, not facts:**
  - quote and follow the attached document (the first check followed the quote in every
    Qwen run since `8a6ea18`);
  - take reported versions as given (fixed in every run after `84badb3`);
  - Ruled out only by a check;
  - ask about unclear details (helped in about 2 of 3 runs).
- **Model difference, once the rules were equal:** on the short guide, Qwen 3.8 27B (dense)
  made DisplayLink Manager the first check in 5 of 5 runs and Ornith 35B-A3B (MoE) in about
  1.5 of 3. With the full manual they were close (Qwen 3 of 3, Ornith 3 of 4 over both
  rounds). For the LJA pilot, Ornith is adequate when the knowledge base holds the vendor
  documentation, and weaker when the model must fill gaps itself.
- **Process lessons:**
  - At temperature 0.6, single runs swing widely: Ornith gave four different first answers
    to the same message. Decide on 3 or more runs per configuration, not on one.
  - Do not add a rule for a failure seen once.
  - Record the harness commit of every run.
- **Stopped here on purpose.** More rules for this case would add prompt length that every
  other ticket pays for. The next lever is putting vendor manuals in the LJA `it`
  collection, which needs the planned RAG gateway.
