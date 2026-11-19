# Token usage and vLLM cache statistics

Implemented 2026-09-10. There are two different scopes of statistics.

## Per-response usage

Non-streaming responses retain vLLM's `usage` object. Streaming requests default to
`stream_options: {include_usage: true}` when the client supplies no stream options.
An explicit `include_usage: false` is respected. The final usage chunk appears after
content/finish chunks and before `[DONE]`; clients must continue reading through it.

`prompt_tokens`, `completion_tokens`, `total_tokens`, and optional details such as
cached prompt tokens pass through unchanged. Backend timing `metrics` also pass through
when the installed vLLM version supplies them. UI support determines whether BoltAI
shows these fields. Transporting usage does not guarantee a particular UI display.
There is no invented cost estimate or billing rate for the local GPU.

Prompt usage includes the system policy, retained conversation, retrieved memory,
and tool schemas/results. Reasoning consumes generation capacity; whether it has a
separate breakdown depends on the backend. Repeated prompt processing across calls is
counted again; these are inference-work totals, not the number of unique chat tokens.

For normal chat/UI tools, standard usage describes the current generation request.
For harness-owned research, it aggregates prompt/completion usage across its internal
rounds, using backend prompt counts when available (tokenizer count as fallback).
Client-executed tool loops contain multiple separate requests; the UI must add their
usage if it wants a whole-task total. Cancelled streams may not deliver final usage.

Compaction adds separate model calls. Standard `usage` remains unchanged, while
`harness_usage` on JSON responses or final SSE usage events identifies generation
and summary prompt/completion counts plus `total_tokens_including_compaction`.
Summary prompt counts use vLLM usage when available, otherwise its exact tokenizer.
Compaction's counters also appear in structured logs; failed or unhelpful summary
work may consume tokens even when no compacted answer is returned.

Structured `generation_usage` logs contain only IDs and nonnegative integer counts,
not prompts, answers, tool arguments or results. `context_compaction` records summary
work. These are logs, not a durable per-user usage database. Keep log retention and
aggregation outside the inference gateway for an enterprise deployment.

Recent vLLM documentation describes optional `--enable-per-request-metrics` for
TTFT, queue time and token throughput. That flag was **not** added to your running
server; check support in the installed version before using it. Your existing
`--kv-cache-metrics` controls cache residency observations, not per-reply usage.
Sources: [vLLM per-request metrics](https://docs.vllm.ai/en/latest/features/per_request_metrics/),
[vLLM engine metrics](https://docs.vllm.ai/en/latest/design/metrics/).

## Server-wide metrics

`GET /v1/backend/metrics` is an authenticated, bounded proxy of the configured vLLM
server's `/metrics`. It returns only `vllm:` Prometheus families, with no-store caching.
There is no client-supplied destination, redirect following or environment proxy use.
The request has a 10-second deadline and 2 MB response limit; backend failure returns
503 without leaking the backend error body.

The lab service key is permitted. JWT callers additionally need `backend_metrics: true`
in a configured role grant. This is a separate operator privilege: the statistics are
**backend-wide**, potentially including other applications/users, not filtered by the
caller's memory scope or profile. They are not appropriate for private per-user billing.

On the lab server we verified:

- `vllm:prompt_tokens_total` and `vllm:generation_tokens_total`.
- `vllm:kv_cache_usage_perc` (a fraction: 0.25 means 25%, despite its name).
- Running/waiting request gauges.
- `kv_block_lifetime_seconds`, `kv_block_idle_before_evict_seconds`, and
  `kv_block_reuse_gap_seconds` histogram families from cache residency tracking.

Counters reset on server restart. Histograms describe cache blocks and reuse patterns,
not tokens attributable to one chat. Preserve labels when graphing multiple workers.

Inside the harness host, from `/root/local-ai-harness`, display a compact snapshot without putting
credentials on the command line:

```bash
docker compose exec -T local-model-harness python scripts/backend_stats.py
```

Add `--raw` for all exposed vLLM metrics. The helper reads the existing container key.
It is an on-demand snapshot, not a scheduled job. For trends, point Prometheus at
`http://<harness host>:8200/v1/backend/metrics` using a securely configured bearer token
and graph the counters/gauges/histograms in Grafana. No collector or dashboard was
installed by this update.

## Verified example

The live compaction/tool follow-up returned generation usage of 888 prompt + 53
completion tokens. The summary used 25,241 prompt + 87 completion tokens, yielding
`harness_usage.total_tokens_including_compaction: 26269`. This illustrates why final
reply usage alone undercounts summary work. The backend supplied reasoning-token
breakdowns on ordinary assistant/creative replies. The snapshot helper and token/cache/
residency metrics proxy also passed live checks on the harness host.
