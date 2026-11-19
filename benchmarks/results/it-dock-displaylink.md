# IT troubleshooting: DisplayLink dock

Prompt, setup, answer key and scoring: [it-dock-displaylink-prompt.md](../it-dock-displaylink-prompt.md).
Tests whether the `it-troubleshoot` agent follows an attached vendor guide over its own
product beliefs. Two engines, same prompt, skills and guide, no tools:

- **Qwen:** `qwen3.8-27b` (dense), home lab.
- **Ornith:** `cyankiwi/Ornith-1.5-35B-A3B-AWQ-INT4` (MoE, about 3B active), vLLM on the
  Strix Halo node, work lab, with context window 131072, temperature 0.6, top_p 0.95 and
  top_k 20.

### Before the source rules, 2026-10-28 to 2026-10-30

Harness `8c11e7c` (work lab) and `98e8efc` (home lab). Not controlled: the first Ornith session
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

### Run 1: source, quote and ruled-out rules, 2026-10-30

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

### Variant: full user manual attached instead of the guide, 2026-10-30

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
  Vendor manuals in the knowledge base (the work lab's team knowledge base, `kb`) are the larger lever;
  rules keep the model to what those documents say.
- **Ornith doubted the macOS version** from its training data, although the harness gives
  today's date. A user-reported version should be taken as given.
- **Speed:** Ornith on the Strix Halo node felt slower than Qwen (reported, not measured).

### Full manual, harness `84badb3`, 2026-10-30

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

### Guide only, harness `84badb3` (Qwen) and `09c02b6` (both), 2026-10-30

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

### Variant: web search instead of an attachment, harness `09c02b6`, 2026-10-30

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
  credits and egress. The work lab had no web tool at the time, so its equivalent is the vendor
  documentation in the knowledge base.

### Web search on both engines, harness `dcad7f6`, 2026-10-30

Same message as the web-search variant (corrected model number, "Please use a websearch to
verify with the product manual", no attachment). Ornith now has web search in the work lab too.
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

## Conclusion of the DisplayLink dock test

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
  rounds). For the work pilot, Ornith is adequate when the knowledge base holds the vendor
  documentation, and weaker when the model must fill gaps itself.
- **Process lessons:**
  - At temperature 0.6, single runs swing widely: Ornith gave four different first answers
    to the same message. Decide on 3 or more runs per configuration, not on one.
  - Do not add a rule for a failure seen once.
  - Record the harness commit of every run.
- **Stopped here on purpose.** More rules for this case would add prompt length that every
  other ticket pays for. The next lever is putting vendor manuals in the work lab's
  team knowledge base (`kb`, [ADR-008](../../docs/adr/ADR-008-team-knowledge-base.md); this note
  first assumed a RAG gateway collection).
