# ADR-007: The IT troubleshooting agent triages within the technician's access

**Status:** Proposed; sections 1–6 in the troubleshoot skill and prompt (PR #15), section 7 as an example tier profile file
**Date:** 2026-11-08
**Deciders:** Project owner

## Context

The `it-troubleshoot` agent was built to help a technician work a ticket. Two real cases
show it drifting into root-cause diagnosis of systems the technician cannot touch.

**Rename fails with "The RPC server is unavailable."** After the knowledge base fix (PR #13),
the first reply found the right Microsoft article and scored 4 of 5 benchmark checks. It
still sent the technician to diagnose a domain controller's RPC ports, with an RSAT cmdlet
workstations do not have. The actual fix was within the technician's reach and took a
minute: delete the script's tag file and reboot, so the Intune script runs again. One
machine in ten had failed once; a retry was the right first move.

**Scanner fails with a write error after a few pages.** Over a long ticket the agent did
some useful work. It summarized what earlier technicians had ruled out, and it noticed
that a failure after several pages points away from a static permission block. Then it
listed Windows Event IDs from memory, and two were wrong (4698/4699 are scheduled-task
events, not Controlled Folder Access; Defender 5007 is a configuration change). It also
offered "enable object auditing on the folder", a security configuration change, as a
viewing tip. The case was cracked by a different method: the problem started the same
day the security team rolled out a USB write-block policy, and the scanners connect by
USB. The technician took that match to the security team, who own the policy, and they
adjusted it.

Three facts about the work deployment shape the design:

- **The support structure is tiered.** A help desk takes calls, triages and routes tickets
  to desktop support (hardware, simple installs) or application support. Each of those
  towers has specialists, with senior specialists who advise as watchers. Only a senior
  specialist hands a ticket to system administration, networking, cybersecurity or a
  vendor. Escalating up a tower requires "clear and concise documentation of actions
  taken." The written process lists AI among the resources technicians may use.
- **Access does not follow job title.** Some people have more access than their title
  suggests, and some less. The agent cannot infer what a person may do from their tier.
- **There is no change management.** Nobody announces policy or configuration changes, so
  the technician has to find them, and correlating "when did it start" with "what changed"
  is the most productive move available.

A model that diagnoses every problem down to a directory or security setting the
technician cannot change is no help to that technician. It also makes the pilot look
risky to the people deciding whether it continues.

## Decision

### 1. The job is triage

Each session works through four steps:

1. **Route.** Decide whose problem it is: the device, the user's account, the application,
   the management platform (Intune, Group Policy), or infrastructure (directory, network,
   servers, security policy).
2. **Contain.** Offer safe fixes within the technician's access, cheapest first. For a
   one-off failure on one machine, that starts with a retry: re-run the step, reboot,
   reseat.
3. **Collect.** Gather the evidence the next person will need: the error text, the scope
   ("1 of 10 machines"), when it started, what was tried and what it showed.
4. **Hand off.** When containment fails or the evidence points past the technician's
   access, write the escalation note (section 6) and stop diagnosing.

Root-cause analysis of systems outside the technician's access belongs in the escalation
note as a lead for the owner, never as steps for the technician.

### 2. The ceiling: only steps the technician can perform

Every check and fix must be something this technician can do with their access. A
command that needs an add-on (RSAT, an admin console, a vendor tool) is either left out
or named as needing it, with a built-in alternative. When the agent is unsure whether a
step is within reach, it asks ("Do you have access to the Group Policy Management
console, or should this go to …?"). It never assumes.

Read-only checks come first. Any change, including one that looks harmless, such as
enabling auditing, clearing a cache or changing a policy, needs the risk, the rollback
and the technician's go-ahead, as the skill already requires.

### 3. The floor: show where to look, how, and what it means

Technicians often have the access (Intune, Group Policy reports) but do not know what to
look for or how. The agent's minimum job:

- **Where and how, step by step.** Not "check the applied GPOs" but: run
  `gpresult /h C:\Temp\gp.html` as the affected user, open the file, read Applied GPOs,
  note any whose name or change date lines up with when the problem started. The same
  for the Intune device page: which page to open and which column to read.
- **Interpret what comes back.** When the technician pastes a report or output, say what
  matters in it and what to ignore.
- **No shame.** Answer basic "how do I…" questions fully and plainly. When the technician
  is unsure, say where the case stands and what is left to check.

### 4. The method: when did it start, and what changed?

The skill teaches the agent to ask, in this order:

1. When did it first start? Get the date as exactly as possible.
2. Who and what is affected, and what do they have in common (a group, a site, a device
   model, a connection type such as USB)?
3. What changed around that date? Look organization-wide, not only on the machine:
   security policies, Group Policy, Intune configuration, antivirus, Windows updates.
   `gpresult /h` shows applied policies, the Intune device page shows configuration
   status and recent changes, and update history shows patches. A change that lines up
   with the start date *and* with what the affected machines share is the strongest
   lead available.
4. Take that match to whoever owns the change, with the evidence (section 6).

### 5. The agent may reason; specifics from memory are marked

Unlike the document-only knowledge base gateway, this agent reasons from general
knowledge as well as documents. The owner accepts that risk and manages it rather than
avoiding it. The observed failures are confident specifics, not the reasoning itself,
so the controls sit on specifics and actions:

- Event IDs, registry keys, error codes, cmdlet names and file paths recalled from
  memory are marked as needing verification, extending the existing rule for error
  numbers.
- The ceiling (section 2) limits what a wrong theory can cost: a few minutes of
  read-only checks, not a change to a system.
- The escalation note carries the reasoning to the person who owns the system, who
  can check it.

### 6. The escalation note

When the session reaches the edge of the technician's access, the agent writes a note
the technician can paste into the ticket, matching the organization's requirement for
documentation of actions taken:

- symptom and exact error text;
- scope and when it started;
- what was tried, each with its result;
- what the evidence points to and why, labeled as the agent's reasoning;
- the suspected area (for example "the USB write-block policy applied to this group"),
  so the senior specialist knows whom to bring in.

The note goes to the next step in the technician's own tower. The agent does not tell a
technician to contact system administration or cybersecurity directly, because the
process routes that through a senior specialist. It names the area so the senior
specialist can route it.

When the scope and impact suggest a top-priority incident (many users, a business stop,
a possible security incident), the agent says so at once and points to the escalation
path, instead of troubleshooting first.

Ticket printouts show only public notes. When the agent summarizes "ruled out" from a
pasted ticket, it says the list comes from the public notes and asks what else was tried.

### 7. Where the pieces live

| Piece | Location | Why |
|---|---|---|
| Triage steps, ceiling, floor, method, note format | `skills/troubleshoot-session.md`, `prompts/it-troubleshoot.md` | Shared and generic; written as "the technician's access described below" (`CLAUDE.md` rule 2) |
| Each tier's access description and next level | A tier profile per tier in the untracked `profiles.local.yaml`, as extra `rules` | Organization-specific and changes with reorganizations (rule 1); stays out of the public snapshot (rule 5) |
| Which tier profile a person may use | The identity config: each sign-in group is granted only its tier profile (`role_grants` → `profiles`) | Enforced by the harness from the verified groups claim, never chosen by the model or the prompt (rule 4) |

Tier profiles are thin variants of `it-troubleshoot`: a YAML merge (`<<: *it_troubleshoot`)
keeps the same prompt, skills and tools, and only `rules` differs. The harness already adds
a profile's rules to the system prompt ahead of the skills, and already limits which
profiles a person sees by sign-in group, so this needs no harness code.
`examples/it-tier-profiles.example.yaml` shows the pattern, and a test checks that it loads
and keeps the base profile's settings and rules.

Someone in two groups sees both tier profiles, because grants combine; that covers people
whose access spans tiers. A profile with no access description, such as the generic
`it-troubleshoot`, makes the skill ask the technician what they can access.

A harness feature that injects access text per person is needed only if per-person
additions turn out to be necessary beyond what combined group grants give.

### 8. Benchmarks change with it

Each case is scored at the lowest tier that would realistically get the ticket. Cases
can be rerun with a broader description to check that the agent adapts. New checks:

- The first step is within the stated access.
- A one-off failure gets a retry before deeper diagnosis.
- Any step past the access is replaced by an escalation note.
- Every step can be followed without asking someone else how.
- Specifics from memory are marked for verification.

## Consequences

- Answers get shorter and more useful to the person reading them. Deep diagnosis still
  happens, inside the escalation note.
- The agent asks more questions about access. That is cheap; a wrong assumption is the
  costly mistake.
- The pending "prefer built-in commands" rule is folded into the ceiling (section 2).
- Benchmark results before and after this change are not comparable. Record which
  scoring version each run used.
- The tier descriptions need upkeep after each reorganization. They are settings, so no
  code release is needed.

## Alternatives considered

- **Document-only answers,** as in the knowledge base gateway. Rejected: the method in
  section 4 and the scanner insight both came from reasoning that no document held.
- **Tier text in the shared prompt.** Rejected: organization-specific and breaks rules 1
  and 2.
- **Separate assistants per tier,** each with its own prompt and skill. Rejected: the
  triage behavior is the same for every tier, and separate copies would drift. Section 7
  uses one assistant with thin tier profiles instead; group grants decide which tier
  profiles a person can pick, so the choice is tied to who they are.
- **A harness feature that injects access per person.** Deferred: group-granted tier
  profiles give the same result with existing code (section 7).

## Open questions

1. Access per tower: local admin on devices, which Intune roles, Group Policy report or
   console access, directory read access, reimage or wipe rights.
2. Should the escalation note follow a template the ticketing system already uses, and
   is it a private or a public note?
3. Should the agent suggest a ticket priority from impact and urgency, or only flag
   possible top-priority incidents?
4. How does the agent learn the organization's local fixes (such as the rename tag file)?
   ADR-006's knowledge loop is the planned route.
