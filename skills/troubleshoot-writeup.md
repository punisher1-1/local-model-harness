# Troubleshooting write-up

Use this workflow to turn a finished troubleshooting session into documentation another person could follow.
It also covers the user's reply to the one question this workflow may ask.

Build the write-up from the latest case log and the conversation. Include only what happened
in this session: every command, result and conclusion must come from the conversation. Mark
anything not established as "unknown". Never include passwords, keys or tokens; replace them
with [redacted].

A step you suggested is not a step that happened. Record a download source, a permission
granted, a restart or any other action only when the user said they did it.

Before writing, check one thing. If the fix was an install or a settings change and the
conversation does not say whether it needed admin rights, ask only this and stop: "Did this need
admin credentials, and where are they held? Reply and I'll write it up." When the user answers,
write the write-up. Ask once; if they do not know, write "elevated access: unknown".

Use status "informational" when no fault was reported (a lookup or a procedure check); then
Symptoms, Root cause and Fix say "not applicable".

Refer to the affected person as "User", and to anyone else by a generic role such as
"technician". Leave out names and job titles, even when the conversation or the case log gives
them: "new setup for the CFO" becomes "new setup for a User". Before finishing, reread the
Summary and Impact and remove any name or job title.

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
other details that played no part in it, including anything checked and ruled out.

## Symptoms
Exact error messages and observed behavior.

## Steps taken
A numbered list: check or command → result → what it showed. Keep commands in code blocks.
Something checked and ruled out gets one line here and appears in no other section.

## Root cause
The underlying technical reason the fault exists, then what was missing or wrong because of it;
not only the missing piece. Or "unknown" with the leading hypothesis.

## Fix
> **Important:** <the easy-to-miss step, where to do it, and what fails without it>.

The change made, with commands, and how to roll it back. If the fix needed elevated access, say
what kind and where the credential is held (for example "local admin password (LAPS), found in
Intune"), never the credential itself.

The Important line is the first line under the Fix heading. It is for a step beside the main
fix that the fix depends on: a permission to grant, a prompt to accept, a restart, a credential
to fetch first. Write one Important line for each such step, one under the other, for example
one for the admin password and one for a permission. It is never the main fix itself (not
"install the driver"). Repeat each in one clause in the Summary. A step the cited documentation
requires but the user did not report doing goes here, worded as required, and not in Steps
taken or the Fix text as something done. Leave the line out only when there is no such step.

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
