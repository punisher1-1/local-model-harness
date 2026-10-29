# Troubleshooting write-up

Use this workflow to turn a finished troubleshooting session into documentation another person could follow.

Build the write-up from the latest case log and the conversation. Include only what happened
in this session: every command, result and conclusion must come from the conversation. Mark
anything not established as "unknown". Never include passwords, keys or tokens; replace them
with [redacted].

Use status "informational" when no fault was reported (a lookup or a procedure check); then
Symptoms, Root cause and Fix say "not applicable".

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
Systems, versions and network details involved.

## Symptoms
Exact error messages and observed behavior.

## Steps taken
A numbered list: check or command → result → what it showed. Keep commands in code blocks.

## Root cause
What was wrong and why, or "unknown" with the leading hypothesis.

## Fix
The change made, with commands, and how to roll it back.

## Verification
How the fix was confirmed.

## Prevention and follow-ups
Monitoring, documentation updates or changes that would stop a repeat.

## Sources
Knowledge-base documents cited during the session (title and locator), or "none".

Show the write-up in the chat first. Save it only when the user asks: create a new vault note
with vault_create_note at `Troubleshooting/YYYY-MM-DD-<short-slug>.md` (lowercase words joined by
hyphens). If it is longer than one note write allows, create the note with the first sections
and add the rest with vault_append. Then tell the user the exact path. If the name is taken,
add a short suffix rather than overwriting.
