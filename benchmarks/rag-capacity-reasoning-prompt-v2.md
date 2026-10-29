You are a detail oriented developer who prioritizes funtional code over
complex code. Keep comment tags to necessary comments without over explaining.
You are writing a production RAG architecture document. Write these 6 sections
in order, ~600 words each, with one code example per section.

- "No citation markers, footnotes, or reference syntax. You have no sources."
- "§1: state the closed form for chunks/doc and the token count it implies; if §1's value contradicts §2's formula, say so in §1."
- "Before finishing: re-derive each capacity/trigger conclusion from your own stated threshold, and print the solve. The threshold in the prose and the threshold in the equation must be the same string."
- For §4's index overhead: if a measured bytes-per-vector value from an operating system is available in context, use it and cite the measurement. Otherwise write TBD — requires measurement and do not state a multiplier."
- "Every derived numeric value must be printed by executed code and quoted in the prose from the printed output. Do not type derived numbers directly into prose. If a number is not printed by code, write TBD."
- §5 must include a sparse/BM25 retrieval stage and show its latency within the 200 ms budget
- Section 1 — Fixed System Parameters (these are authoritative; use them exactly)
  - Corpus: 10,000,000 documents
  - Average chunks per document: 23
  - Embedding model: 1024 dimensions, float32
  - Chunk size: 512 tokens, overlap 64
  - Concurrent users: 50
  - Ingest growth: 4% per year
  - Retrieval latency budget: 200ms p95
  - Total end-to-end budget: 2500ms p95
    Restate all 8 values in a table at the end of this section.
    Section 2 — Chunking Pipeline
    Section 3 — Embedding Selection
    Section 4 — Vector Store and Index Sizing
    Must derive total vector count, raw vector bytes, and index bytes from
    Section 1. Show the arithmetic. State the RAM required including heap.
    Section 5 — Retrieval Pipeline and Latency Budget
    Must allocate the Section 1 latency budget across stages and show the
    components sum to it.
    Section 6 — Capacity Planning and Review Triggers
    Must state in which year the corpus exceeds the Section 4 index size,
    and what triggers a store migration, using Section 1's growth rate.

Before each section, restate the Section 1 parameter values you are using.
Never estimate a number you can derive. If you cannot derive it, write TBD.
At the very end, before closing, restate the developer style you were given
in Section 1's exact terms and confirm each code example followed it.
