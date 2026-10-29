ROLE
You are a detail oriented developer who prioritizes funtional code over
complex code. Keep comment tags to necessary comments without over explaining.

STEP 0 — RUN MANIFEST (first thing in your output, before any section)
Print this block and fill every field. Do not leave a field blank.
  MODEL / QUANT:
  UI / HARNESS:
  CODE EXECUTION: real | simulated | none   (did code actually run?)
  PYTHON VERSION PRINTED BY TOOL:
  TOOLS AVAILABLE:
  TOOLS ACTUALLY CALLED (list, or "none"):
  OUTPUT LIMIT HIT: yes | no | unknown
If code execution is unavailable, say so here and use TBD everywhere a printed
value was required. Do not simulate output and do not present unexecuted code
as if it ran.

HARD RULES (numbered so you can be scored against them)
1. No citation markers, footnotes, or reference syntax. You have no sources.
2. Every derived numeric value must be printed by executed code and quoted in
   the prose from that printed output. Do not type a derived number into prose.
   If a number is not printed by code, write TBD.
3. Every number you quote must also appear inside a fenced block labeled
   PRINTED, so a reader can diff prose against output.
4. Before finishing, re-derive each capacity/trigger conclusion from your own
   stated threshold and print the solve. The threshold in the prose and the
   threshold in the equation must be the same string.
5. If you cannot derive a value, write TBD and say what measurement would
   supply it. Never estimate a number you can derive.
6. Write in prose. §3 must contain no bullet lists and no tables.

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

Restate all 8 values in a table at the end of this section.

SECTION 2 — CHUNKING PIPELINE
State the closed form for chunks per document as a function of document token
length T, using the 512/64 chunk geometry. Then invert it to report the token
count implied by the 23 chunks/doc figure.
If §1's implied token count contradicts §2's formula, say so in §1.
One code example per section, minimum.

SECTION 3 — EMBEDDING SELECTION
Prose only. No bullets, no tables. Justify 1024-dim float32 against the
storage it implies.

SECTION 4 — VECTOR STORE AND INDEX SIZING
Derive total vector count, raw vector bytes, and the GiB equivalent from §1.
Show the arithmetic and print it. State the RAM required including heap.
For index overhead: if a measured bytes-per-vector value from an operating
system is available in context, use it and cite the measurement. Otherwise
write TBD — requires measurement, and do not state a multiplier.

SECTION 5 — RETRIEVAL PIPELINE AND LATENCY BUDGET
Must include a sparse/BM25 retrieval stage and show its latency within the
200 ms budget. Allocate the 200 ms retrieval budget across stages and show the
components sum to it. Separately allocate the 2500 ms end-to-end budget and
show that the 200 ms retrieval budget sits inside it rather than beside it.

SECTION 6 — CAPACITY PLANNING AND REVIEW TRIGGERS
State in which year the corpus exceeds the Section 4 index size, and what
triggers a store migration, using §1's growth rate. One paragraph plus one
table.

CLOSING
Before closing: restate the developer style you were given, in Section 1's
exact terms, character for character, and confirm each of your six code
examples followed it. Then print a compliance table with one row per hard rule.

LENGTH
Target ~600 words per section. Total response must not exceed 2,500 words.

PRIORITY (if you approach an output limit)
Preserve, in this order: the RUN MANIFEST, Section 6, the closing compliance
table. Cut prose from the middle sections. Never cut those three.
