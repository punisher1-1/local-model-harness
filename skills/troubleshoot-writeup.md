# Troubleshooting write-up

Use this workflow to turn a finished troubleshooting session into documentation another person could follow.

Build the write-up from the latest case log and the conversation. Include only what happened
in this session: every command, result and conclusion must come from the conversation. Mark
anything not established as "unknown". Never include passwords, keys or tokens; replace them
with [redacted].

Use status "informational" when no fault was reported (a lookup or a procedure check); then
Symptoms, Root cause and Fix say "not applicable".

Refer to the affected person as "User", and to anyone else by a generic role such as
"technician". Leave out names and job titles, even when the conversation gives them.

The date is the one the harness gives as today's date, unless the conversation shows the session
happened on another day. Use the same date in the note path.

Format, in Markdown:

# <Short problem title>
**Date:** <date of the session, if known> · **Status:** resolved / workaround / escalated / open / informational

## Summary
Two or three sentences: the symptom, the root cause, the fix.

## Impact
What or who was affected, and for how long, if known.

## Environment
Systems, versions and network details that bear on the fault. Leave out peripherals, cabling and
other details that played no part in it.

## Symptoms
Exact error messages and observed behavior.

## Steps taken
A numbered list: check or command → result → what it showed. Keep commands in code blocks.

## Root cause
The underlying technical reason the fault exists, then what was missing or wrong because of it;
not only the missing piece. Or "unknown" with the leading hypothesis.

## Fix
The change made, with commands, and how to roll it back. If the fix needed elevated access, say
what kind and where the credential is held (for example "local admin password (LAPS), found in
Intune"), never the credential itself.

When the fix only works if an easy-to-miss step is also done (a permission to grant, a prompt to
accept, a restart, a credential to fetch first), do not leave it as a trailing note. Put it at
the top of this section as a callout, and repeat it in one clause in the Summary:

> **Important:** <the step, where to do it, and what fails without it>.

## Verification
How the fix was confirmed.

## Prevention and follow-ups
Monitoring, documentation updates or changes that would stop a repeat.

## Sources
Knowledge-base documents cited during the session (title and locator), or "none".

Show the write-up in the chat first. Save it only when the user asks: create a new vault note
with vault_create_note at `Troubleshooting/YYYY-MM-DD-<short-slug>.md` (lowercase words joined by
hyphens). The date and slug form one file name in the `Troubleshooting` folder, for example
`Troubleshooting/2026-10-30-dock-second-display-not-detected.md`; never a folder per date. If it
is longer than one note write allows, create the note with the first sections and add the rest
with vault_append. Then tell the user the exact path. If the name is taken, add a short suffix
rather than overwriting. If no note tool is supplied, say so and suggest the same path for the
user to save it themselves.

When the user asks for changes to a write-up, make those changes and no others, then show the
whole write-up again. A correction from the user replaces what the write-up said: state the
technical point the way they stated it, without rewording it into a different claim. When they
ask for a detail to be removed, remove it from every section and do not describe it another way.

In Root cause and Prevention, keep the same rule as the session: a product fact that came from
general knowledge rather than the conversation or a cited document is marked unverified.
