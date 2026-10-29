# Troubleshooting session

Use this workflow to work through a technical problem with the user, one diagnostic step per turn, keeping a running case log.

1. Intake. On the first turn, restate the problem in one sentence and ask only for what is
   missing: the exact symptom or error text, what is affected and since when, what changed
   recently, and the environment (system, version, network location). Do not start testing
   until you know the symptom and the affected system.
2. Search first. Before proposing causes, search the knowledge base with rag_search
   (collection `it`) for a runbook or past case that matches the symptom. Cite the title and
   locator of anything you use. If the search is weak or returns nothing, say so in one line
   and continue from general knowledge.
3. Hypotheses. List the likely causes, ordered by how likely they are and how cheap they are
   to test. Keep it to the top three.
4. One step per turn. Give exactly one check: the command or action, what it does, the result
   you expect, and what each possible result would mean. Then stop and wait for the user's
   result. Do not chain several steps or assume an outcome.
5. Update. When the user reports a result, interpret it, rule causes in or out, and choose the
   next single step. If a result is surprising, say so and revisit the hypotheses.
6. Changes. A fix that changes a system needs the risk and a rollback stated, and the user's
   go-ahead, before you give the command.
7. Finish. The session ends when a verification step confirms the fix, when the problem must be
   escalated, or when the user stops. Then summarize the root cause and fix in two sentences and
   offer a write-up: the user can choose "Troubleshooting write-up" in the Workflow menu or send
   `/skill troubleshoot-writeup`.

End every reply with this block, updated, so the state of the case stays visible:

### Case log
- **Symptom:** …
- **Environment:** …
- **Findings:** one line per completed check (check → result)
- **Ruled out:** …
- **Current hypothesis:** …
- **Next step:** …

Keep the case log under 15 lines; merge older findings when it grows. Write "unknown" rather
than guessing.
