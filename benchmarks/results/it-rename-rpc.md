# IT troubleshooting: Intune rename RPC error

Prompt, setup, answer key and scoring: [it-rename-rpc-prompt.md](../it-rename-rpc-prompt.md).
Tests whether the `it-troubleshoot` agent reasons correctly from a pasted log when no
document covers the case. Same engines as the DisplayLink test.

### Live case and first re-runs, 2026-11-04 to 2026-11-05

Not controlled: one run each, and tool settings differed. Scored against the five checks.

- **Qwen, live case, 2026-11-04** (harness `2b89261`, knowledge base on, no match): the
  multi-turn session that solved the case. First reply only:
  - 1 ✓ (DC over RPC); 3 ✗ (called it "Windows error 5"); 4 ✓ (`nltest /dsgetdc`);
    5 partly (asked about other machines, not about past fixes).
  - 2 ✗ on the second reply: "two attempts ~20 s apart, consistent with an RPC timeout",
    which the log does not show. The claim reached the saved write-up. A later reply listed
    DNS, firewall and DC causes under Ruled out on reasoning ("1 of 10 failed").
- **Ornith, work lab, 2026-11-05** (harness `8a44a5b`, no knowledge base exists yet):
  - 1 ✗: said `Rename-Computer` is local and the failing RPC server was the machine's own,
    stated as fact; the event-log check it chose followed from that.
  - 2 ✓ (only the 50 s window); 3 ✓ (0x800706BA); 4 ✓ (`Get-WinEvent`); 5 ✓.
  - Also: one hypothesis instead of three, "RpcMap" for the endpoint mapper service
    (`RpcEptMapper`), "Intune Managed Installer" for the Intune Management Extension.
- **Qwen, home, 2026-11-05** (harness `576f09c`, knowledge base on, vault off, no match):
  - 1 ✓; 3 ✓ (0x6BA); 5 ✓.
  - 2 ✗: "attempted twice" in a table headed "facts only", used to argue the DC was
    unreachable for the whole window.
  - 4 ✗: `Get-ADDomainController -Identity (Select-Object -Random 1)` is not valid usage and
    needs RSAT, which workstations normally lack.

Changes after these runs (harness after `576f09c`):
- The log rule gets a concrete example: a repeated error is not a second attempt; count the
  line that starts the action; never label an inference as "facts". The two-attempts claim
  appeared in two Qwen runs, so it meets the bar for a rule.
- No rule for built-in commands yet: the RSAT command was seen once. Check 4 keeps watching it.

### After the repeated-line rule, 2026-11-05

- **Ornith, work lab** (public snapshot `9763180`, built from private `2b4d188`; no knowledge
  base exists yet; real log, not the sanitized fixture). One run:
  - 1 ✗: again said the failure was in the local RPC stack, after explaining correctly that
    in AD the endpoint mapper on the DC may be unreachable. Its first check,
    `Get-Service RpcSs`, cannot separate hypotheses: Windows cannot run PowerShell with that
    service stopped.
  - 2 ✓ (no attempt count or per-attempt timing); 4 ✓ (`Get-Service`, `Get-WinEvent`).
  - 3 ✗: 0x800706BA, but glossed as "(53)"; 0x6BA is 1722.
  - 5 partly: asked what changed and whether one machine or several, not what fixed it before.
  - Also: called the endpoint mapper `RpcSs` (that is the RPC service; the mapper is
    `RpcEptMapper`; last run it said "RpcMap"), and gave two checks in one turn. Its event
    query (5719) would, if it hit, point at the DC rather than the local stack.

The local-RPC belief is now 2 of 2 Ornith runs, with the rules in place both times. As in
the DisplayLink test, this is a product belief, not a behavior, so no rule is added: the
lever is the rename runbook in the work lab's team knowledge base, which states that the rename
contacts a domain controller.

- **Qwen, home** (harness `2b4d188`, the same code as `9763180`; knowledge base on, vault
  off; the search returned only unrelated lab docs, which it said did not apply). One run:
  - 1 ✓ (DC over port 135 and a dynamic port).
  - 2 mostly ✓: labeled the repeated error "inference: the script likely retries once", but
    inside a table headed "observed facts".
  - 3 ✗: "`ERROR_RPC_SERVER_UNAVAILABLE`, 1225". The error is 1722
    (`RPC_S_SERVER_UNAVAILABLE`); 1225 is "connection refused".
  - 4 ✓ (`Test-NetConnection -Port 135`), with one wrong switch: `nltest /ds_get_dc:` for
    `/dsgetdc:`.
  - 5 partly: asked about scope and recent changes, not what fixed it before. Asked whether
    the two names in the log were expected instead of assuming, which is the right handling.

Changes after these runs:
- Error numbers: wrong in 3 of 5 runs across both engines, a different number each time
  ("error 5", "(53)", 1225). This is a behavior (stating a number the model does not know),
  not a product belief, so it gets a rule: quote the error text; give a number only if it is
  in the user's output or a cited source.
- The "has this happened before" intake question was asked only partly in 3 of 3 runs since
  it was added. Watching it rather than adding wording.

Next: three runs per engine with no tools, then the same with the rename runbook in the work lab's
team knowledge base.

### Collection fix and earlier runs on `f03b91c`, 2026-11-06

Scored in a separate review session; recorded here. Three configurations, kept apart: no
knowledge base, knowledge base without a matching document, and knowledge base with the
Microsoft Windows client troubleshooting manual (collection `it help` at home).

- **Qwen, home, `f03b91c`, knowledge base on, no match:** 1 ✓; 2 partly (an inference in
  the "observed facts" table, and a claim about the script unregistering its task before
  the rename, with no script seen); 3 ✓ benchmark, ✗ rule (0x6BA, unsourced); 4 ✓
  (`nltest /dsgetdc`, but overclaimed that it verifies the secure channel); 5 ✗ (no intake
  questions).
- **Ornith, work lab, `53dd32f`, no knowledge base:** 1 ✓ (machine account, secure channel);
  2 ✓; 3 ✗ ("0x800706BA / 1006"); 4 ✗ (`Get-NetDNSServer` is not a client cmdlet; two
  commands); 5 ✓.
- **Qwen, home, `f03b91c`, manual in `it help`:** 1 ✓; 2 ✓ (separate Facts and Inferences);
  3 ✓ and rule ✓ (1722 from the p. 72 table); 4 ✓; 5 ✓. But it gave the 0x54b article's
  cause and Step 1 (p. 51) as the causes of 0x6ba, and missed the 0x6ba article's own first
  step (NetSetup.log, p. 73).
- **Runs A and B (Qwen, `f03b91c`):** the prompt and skill said "collection `it`", which at
  home holds homelab notes. Both reported no runbook and answered from general knowledge.
  Run C, after the owner said where the manual was, searched `it help` and led with
  NetSetup.log. Runs B and C both claimed two attempts.

Change after these runs: the prompt and skill no longer name a collection; a weak scoped
search is retried without one (PR #13, harness `df7dbbc`).

- **Qwen, home, `df7dbbc`, manual found without a hint:** 1 ✓; 2 ✓ (one nit: "Windows 11
  24H2" in a facts table, from build 26100); 3 ✓ and rule ✓; 4 ✗ (`Get-ADDomainController`,
  needs RSAT, not said; the third run with it); 5 ✓. Missed NetSetup.log; cited the
  "Port not reachable" article (p. 628) for causes rather than the 0x6ba article.

### Triage scoring (ADR-007), 2026-11-08

The owner set the agent's purpose as triage within the technician's access
(`docs/adr/ADR-007-triage-within-access.md`). The real fix for this case was within a
technician's reach: delete the script's tag file and reboot, so Intune runs it again. From
here, runs are also scored on the checks added to
[it-rename-rpc-prompt.md](../it-rename-rpc-prompt.md#triage-checks-adr-007). Results before
and after this point are not comparable.

- **Qwen, home, `358d8a0`** (triage skill, PR #15): 1 ✓; 2 ✗ ("twice (two separate calls in
  the script)" in the facts table); 3 ✓; 4 ✓ (`nltest`, `Test-NetConnection`; the first KB
  run to pass); 5 ✓. Triage: retry only as a conditional ("if nltest succeeds, re-run");
  never asked how the script reruns; no hand-off. Called a Microsoft scenario on p. 326 "a
  past case" from the knowledge base.

The two-attempts claim was now in four runs, so the rule moved to its own line in the
prompt (PR #18, harness `7e6232f`).

Three runs on `7e6232f`, manual in `it help`, profile `it-troubleshoot` with no access
description:

| Check | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| 1. DC, not local RPC | ✓ | ✓ (also: the script calls the cmdlet, not ADManager Plus) | ✓ |
| 2. Attempts not stated as fact | ✓ | ✓ ("unknown from this log alone") | ✓ (labeled inference) |
| 2. Nothing labeled fact that is an inference | ✗ ("key fact": the old name means an earlier rename) | ✓ | ✗ ("24H2" and "SYSTEM is a domain account" under Facts) |
| 3. Error code, sourced | ✓ | ✓ | ✓ |
| 4. Built-in commands | no step given (asked for a shell first) | ✓ (Notepad / `Get-Content`) | ✓ (`nltest /dsgetdc`) |
| 5. Scope; Ruled out "none yet" | partly | mostly (not the state after the reboot) | ✓ (also asked what the technician can access) |
| 6. First step from the 0x6ba article (NetSetup.log) | ✗ | ✓ | ✗ |
| Wrong-article citation for causes | ✗ (0x54b, p. 51) | ✓ | ✗ (0x6D9 "§Cause", p. 45) |
| Asks what changed around the start date | ✗ | ✓ | ✓ |
| Retry offered as the first step | ✗ | partly (transient ranked first) | partly (transient ranked third) |
| Steps followable without asking how | n/a | ✓ (clicks, what to search for, what each result means) | ✓ |

What held across the three runs:
- The attempt count: 3 of 3 correct after the prompt line, against 4 of 5 wrong before it.
- Hypotheses marked "within reach" or "hand-off", as the triage skill asks.
- No RSAT or add-on commands.

What did not:
- No run told the technician plainly to re-run the script, the step that fixed the case.
- Inferences under a Facts heading in 2 of 3 runs (different ones each time).
- Wrong-article citations in 2 of 3 runs. Chunks carry only their nearest heading
  ("§Cause" in many articles), so neighbouring articles mix. This is a knowledge base
  problem (article titles in chunk labels), not a prompt problem.

Comparison, same harness and knowledge base, profile `local-tools` (no troubleshoot
skill): one run with the knowledge base and one that chose web search. Both claimed two
attempts. Both suggested re-running the script. The web run read Microsoft's 0x6ba article
whole and led with NetSetup.log, then `nltest` and `Test-NetConnection`. It also gave
engineer-level advice beyond a technician's reach (script hardening, a service-account
credential in the script) and one wrong detail from memory: Kerberos clock skew "~5 hours"
(the default is 5 minutes). The knowledge base run used `portqry` and DC-side checks.

Next: make the first reply offer the retry when a one-off transient failure is the likely
cause, then three more runs; run the same prompt on a help desk tier profile once one is
configured.

### Retry first, harness `793d149`, 2026-11-08

PR #20 opened skill step 6 with a retry exception for one-off failures. Three runs, same
setup as above:

| Check | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| Attempt count "unknown" | ✓ | ✓ | ✓ |
| Gives a step this turn | ✗ (five questions) | ✓ (`Test-NetConnection` to port 135) | ✗ (four questions) |
| Asks or notes how the script re-runs | ✓ ("a one-shot that won't fire again?") | ✓ ("unregistered its own scheduled task… will not auto-re-run") | ✓ ("did the rename succeed after that reboot?") |
| Retry given as the step | ✗ | ✗ (only after the port test succeeds) | ✗ |
| Script calls the cmdlet, not ADManager Plus | ✗ | ✓ | ✓ |
| Specifics from memory marked | n/a | ✗ (a Netlogon registry value `DC` to find the DC, probably not real) | n/a |

All three thought about the retry, against none before, and the attempt count stayed
correct (6 of 6 since PR #18). But two of three gave no step at all, and none made the
retry the step: "confirm it did not already succeed" became a question to the user, and
the exception's "affects several machines" made the model confirm scope first, though the
message says "a computer".

The owner's verdict: start with the simple answer. The error says the machine could not
reach the directory, not access denied or a name conflict, and the other machines imaged
that day renamed fine, so ports and the domain controller are a wild goose chase. Change
after these runs: "Simple answer first" at the top of the skill (meaning in a sentence or
two, the simplest safe fix as the step, how to make an Intune script run again, what to do
if it fails, at most two questions alongside), intake trimmed to the one or two details that
matter, and a vendor guide's diagnostic steps after the simple fix.

### Simple answer first, harness `4e31835`, 2026-11-08

One run so far (PR #21). The first run to lead with the meaning of the error and make the
retry the step: `hostname` first, then re-run. But the re-run was `Rename-Computer -NewName
… -Restart` by hand in an admin PowerShell, and it never mentioned the tag file, although
the skill described Intune's done marker. The owner's manual runs have never worked: the
tag file is a deliberate guard, so the script does not run at all while it exists (or
computers could keep renaming themselves in AD), and a manual command runs under the
technician's account, not SYSTEM. Also: it listed permissions, bad name and script logic
under Ruled out from the error text, the same reasoning the owner used; and `nbtstat -n` in
the fallback, which does not help here.

Changes after this run: re-run the way it ran, never by hand (rename the done marker, then
reboot or sync so Intune runs it under SYSTEM), with the guard's purpose stated; and the
exact error text may rule out causes that have their own errors.

### Re-run through the marker, harness `a34a1f3`, 2026-11-08

Run 1 (PR #22): the reply the owner described, apart from the search. Meaning first, with
what the error rules out ("Access is denied" and "already exists" have their own errors);
attempts unknown; step `hostname`, then "Don't run `Rename-Computer` by hand. Re-run it
through Intune: clear the script's done marker", Sync now or reboot; asked how the script
marks itself done ("often a `.tag` file next to the log"); DC and network only if the retry
fails. One unmarked detail from memory: Intune platform scripts have no detection method
(Win32 apps do).

It called no tools: the "Simple answer first" section, above the numbered steps, was read
as "answer at once" and the knowledge base search (step 2) was skipped. Harmless today, but
once the team's rename runbook is in the knowledge base it would go unread. Change after
this run: search before the first reply, even when the fix looks obvious; a team runbook
that gives the fix is the simple answer.
