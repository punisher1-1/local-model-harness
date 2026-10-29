ROLE
You are a detail oriented developer who prioritizes funtional code over
complex code. Keep comment tags to necessary comments without over explaining.

STEP 0 — RUN MANIFEST (first thing in your output, before any section)
Print this block and fill every field. Do not leave a field blank.
  MODEL / QUANT:
  UI / HARNESS:
  CODE EXECUTION: real | simulated | none   (did code actually run?)
  PYTHON VERSION PRINTED BY TOOL: (copy the line your script printed)
  TOOLS AVAILABLE:
  TOOLS ACTUALLY CALLED (each call, in order, or "none"):
  OUTPUT LIMIT HIT: yes | no | unknown
If code execution is unavailable, say so here and use TBD everywhere a printed
value was required. Do not simulate output and do not present unexecuted code
as if it ran.

HOW TO RUN THE CODE
Write the six code examples (one per section) first. Then run them, together in
one script or in several runs, and quote them afterwards exactly as they ran.
The first line your script prints must be sys.version.

HARD RULES (numbered so you can be scored against them)
1. No citation markers, footnotes, or reference syntax. You have no sources.
2. Every derived numeric value must be printed by executed code and quoted in
   the prose from that printed output. Do not type a derived number into prose.
   If a number is not printed by code, write TBD.
3. Each section ends with its code example, then a fenced block labeled PRINTED
   holding that example's output. Both are copied character for character from
   what ran: the code as contiguous lines of the executed script (comments
   included), the PRINTED block as contiguous lines of the tool's stdout. Do not
   rename, reformat, shorten or reword either. Every number you quote in a
   section must appear in that section's PRINTED block.
4. Before finishing, re-derive each capacity/trigger conclusion from your own
   stated threshold and print the solve. The threshold in the prose and the
   threshold in the equation must be the same string.
5. If you cannot derive a value, write TBD and say what measurement would
   supply it. Never estimate a number you can derive, and do not state typical
   or ballpark figures for values you were told are TBD.
6. Write in prose. §3 must contain no bullet lists and no tables.
7. Write every number as digits, never as words ("2 years", not "two years").
8. Count time as year n from today (n = 0). Do not assign calendar years.

SECTION 1 — FIXED SYSTEM PARAMETERS (authoritative; use exactly)
Corpus: 10,000,000 documents
Average chunks per document: 23
Embedding dimensions: 1024
Embedding dtype: float32 (4 bytes per component)
Chunk size: 512 tokens, overlap 64
Concurrent users: 50
Ingest growth: 4% per year
Retrieval latency budget: 200 ms p95
Total end-to-end budget: 2500 ms p95
Index node RAM ceiling: 2048 GiB (fixed; does not grow with the corpus)
Heap factor: 0.25 of raw vector bytes

Restate all 11 values in a table at the end of this section.

SECTION 2 — CHUNKING PIPELINE
Windows start at token 0 and advance by 512 − 64 tokens; a document gets one
more window only while the previous window ends before the document does.
State the closed form for chunks per document as a function of document token
length T. Before using it, check it in code against a direct simulation of
those windows for every T from 1 to 20,000 and print the number of mismatches,
which must be 0. Then invert it to report the token range implied by the
23 chunks/doc figure, and print the chunk count at both ends of the range and
just outside it.
If §1's implied token count contradicts §2's formula, say so in §1.

SECTION 3 — EMBEDDING SELECTION
Prose only. No bullets, no tables. Justify 1024-dim float32 against the
storage it implies. Any alternative you compare against (another dimension or
dtype) needs its storage printed by code too.

SECTION 4 — VECTOR STORE AND INDEX SIZING
Derive total vector count, raw vector bytes, and the GiB equivalent from §1.
Show the arithmetic and print it. State the RAM required including heap.
For index overhead: if a measured bytes-per-vector value from an operating
system is available in context, use it and cite the measurement. Otherwise
write TBD — requires measurement, and do not state a multiplier.

SECTION 5 — RETRIEVAL PIPELINE AND LATENCY BUDGET
Stage latencies are design allocations, not derived values: define them in
code, call them allocations in the prose, and print them with their sums.
Include a sparse/BM25 retrieval stage. Allocate the 200 ms retrieval budget
across stages and show the components sum to exactly 200 ms. Separately
allocate the 2500 ms end-to-end budget so its components (including any
margin, as its own line) sum to exactly 2500 ms, and show that the 200 ms
retrieval budget is one of those components rather than an addition to them.

SECTION 6 — CAPACITY PLANNING AND REVIEW TRIGGERS
State the first year n in which the RAM required (Section 4, including heap)
exceeds the 2048 GiB ceiling at §1's growth rate. Then define the store
migration trigger as a percentage of the ceiling that you choose and state,
compute and print: the trigger in GiB, the first year n it is crossed, and the
lead time in years from that year to the ceiling year. Print the RAM in each
year from the trigger year to the ceiling year. One paragraph plus one table.

CLOSING
Before closing: quote the ROLE text character for character and confirm each
of your 6 code examples followed it. Then print a compliance table with one row
per hard rule and a column naming the evidence (a PRINTED line or the section).
Mark a rule FAIL if any part of it fails; do not mark PASS by assumption.

LENGTH
Target ~350 words per section. Total response must not exceed 2,500 words.

PRIORITY (if you approach an output limit)
Preserve, in this order: the RUN MANIFEST, Section 6, the closing compliance
table. Cut prose from the middle sections. Never cut those three.
