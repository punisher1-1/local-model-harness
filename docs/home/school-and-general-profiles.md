# School and general knowledge profiles

Two home profiles that replace the unused demo profiles `local-creative` and
`local-research`:

| Profile | For | Prompt | Memory scope |
|---|---|---|---|
| `local-school` | Coursework: explaining material, assignments, discussion posts, APA checks, math | `prompts/school.md` | `school` (its own) |
| `local-general` | Questions on any topic, with lookups on the web or in your notes | `prompts/general.md` | `home` (shared with `local-home` and `local-tools`) |

The profile entries are in
[examples/school-and-general-profiles.yaml](../../examples/school-and-general-profiles.yaml).

## What each setting does

| Setting | School | General | What it means |
|---|---|---|---|
| `mcp_servers` | all five | all five | Tool servers a chat may turn on: vault (notes), code (Python sandbox), web (search and page reading), rag (curated knowledge base), kb (team runbooks). |
| `mcp_default` | all but kb | all but kb | Tools that are on when a chat starts. Web search costs search credits; it starts on here because looking things up is the point of both profiles. Turn tools off per chat if you want. |
| `client_tools` | true | true | Required for any tool. It also means the demo `research:` block from `local-research` has to go: the harness refuses a profile that has both. |
| `verify_numbers` | annotate | annotate | After an answer, lists any numbers the model stated that no Python run printed, so unchecked math stands out. |
| `skills` | discussion-draft, apa-review, review-feedback | vault-research | Optional workflows you can pick per chat. No `default_skill`, so ordinary questions get ordinary answers. |
| `chat_memory`, `memory_recall` | on | on | `chat_memory` lets a chat save a memory when you write "Remember: ...". `memory_recall` attaches up to 4 matching saved memories (4 KB at most) to each question. |
| `compaction` | on | on | When a chat reaches 85% of the usable context, older turns are summarized so the chat keeps going. The last 4 turns and your current question are never summarized. `summarize_tool_results` also shrinks one oversized tool result, such as a long web page. |
| `context_window` | 131,072 | 131,072 | The most context the profile allows. The harness lowers it to what vLLM actually serves (its `--max-model-len`), so this means "as long as the server allows". The old demo values were 16,384 and 32,768. |
| `max_output_tokens` | 16,384 | 16,384 | The longest single reply, including reasoning. It is reserved out of the context window. |
| `thinking_budget_ratio` | 0.25 | 0.25 | Reasoning may use up to a quarter of the output allowance (4,096 tokens), leaving the rest for the answer. |
| `enable_thinking`, `reasoning_effort` | on, medium | on, medium | The model reasons before answering. Medium thinks longer than low; low suits quick chat, medium suits checking work and weighing sources. |
| `temperature` | 0.5 | 0.7 | How much randomness goes into picking each word. Lower gives steadier, more repeatable answers; higher gives more varied wording. Qwen advises against going much below 0.5 to 0.6 with thinking on, since very low values can make it loop. |
| `top_p` | 0.9 | 0.8 | Only the most likely words that together make up this share of probability are considered. |
| `presence_penalty` | 1.5 | 1.5 | Discourages repeating the same phrases. Qwen recommends 0 to 2. |
| `top_k`, `min_p`, `repetition_penalty` | 20, 0, 1.0 | 20, 0, 1.0 | Qwen's recommended values, unchanged from the other profiles. |
| `request_timeout_seconds` | 600 | 600 | Tool calls and long reasoning take time, so these get 10 minutes instead of the default 3. |

## Install on the harness host

1. Back up the settings: `tar czf ~/harness-before-school-general-$(date +%F).tgz profiles.local.yaml identity-config memory-config`.
2. Pull the merged change so `prompts/school.md` and `prompts/general.md` exist.
3. In `profiles.local.yaml`, delete the `local-creative` and `local-research` entries and
   paste the two entries from the example file under `profiles:`.
4. In the memory config, add the new scope next to the others, with a namespace not used
   by any other scope:

   ```yaml
   scope_namespaces:
     school: harness_school
   ```

5. In the identity config, in your own role grant (and in `service_key` if an app such as
   Open WebUI should see them): replace `local-creative, local-research` with
   `local-school, local-general` under `profiles`, add `school` to `memory_scopes`, and
   add `kb_search, kb_read` to `tools` and `team_kb` to `collections` if kb should work.
6. Check, then restart:

   ```bash
   docker compose exec -T local-model-harness python scripts/check_config.py
   docker compose restart local-model-harness
   ```

7. In `/chat/`, pick each profile in a new chat. Ask a question that needs a lookup in
   `local-general` and a short math problem in `local-school`, and check the tool activity.

Open WebUI or BoltAI model entries named `local-creative` or `local-research` stop working
after the rename; point them at the new IDs.

To roll back, restore the archive from step 1 and restart.
