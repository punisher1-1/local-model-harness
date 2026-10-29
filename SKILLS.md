# Harness-managed skills

Skills are trusted repository Markdown instructions, separate from identity,
model settings, memory, and UI configuration. This first stage migrates two
course-writing profiles; the other profiles are unchanged.

## Available writing workflows

| ID | Behavior |
|---|---|
| draft-rewrite | Return only the corrected draft, preserving the author's voice |
| apa-review | Three-section APA review, without rewriting the paper |
| discussion-draft | Draft an initial discussion post or peer reply when requested |
| review-feedback | Give corrections and suggestions without a full rewrite |

A profile opts in with:

```yaml
skills: [draft-rewrite, apa-review, discussion-draft, review-feedback]
default_skill: draft-rewrite
```

Each ID loads `skills/<id>.md` relative to the profiles configuration directory.
Files must exist, be nonempty, fit within 64 KiB, and resolve inside that skills
directory. IDs are bounded lowercase letters/digits/hyphens; profiles allow at
most 16 unique IDs. `default_skill` is optional: when set it must name a listed skill;
when left out (or `""`), the UI shows Automatic and the model uses a workflow only when
the user selects it or the request clearly matches it. Invalid configuration
fails startup. Only trusted administrators should edit these files.

## Selecting a workflow

Pasting a draft still returns the corrected draft automatically. Natural-language
requests such as "APA review only" or "give me feedback, do not rewrite" select
the corresponding instructions through the model. This selection is probabilistic,
not a deterministic intent classifier.

For explicit selection, begin the final user message with:

```text
/skill apa-review
Review this draft and its references: ...
```

Other commands use the IDs above. The command must start the message. Put the task after the skill ID on the
same line or on subsequent lines. Unknown/disallowed IDs or a
missing task return 400 before inference. The command is removed from the task
and an explicit selection instruction is added to the system prompt. It does
not grant access to another profile or persist as server-side conversation state.
Repeat the command when an exact selection is needed on another turn. Prior user
messages, quoted embedded commands, and tool messages do not trigger the parser.
Clients that prepend text to the user message may prevent command recognition.

All enabled skill instructions are composed at startup in this initial version.
There is no dynamic skill execution or lazy loading. This preserves natural-language
workflow selection, but all enabled instructions consume prompt tokens. Exact
vLLM tokenization and compaction budgeting include them. Profile fingerprints
include loaded content; explicit selections derive a distinct request fingerprint.
`X-Harness-Skill-Selection` and generation logs report `auto`, a selected ID, or
`none`. `auto` does not claim which workflow the model ultimately followed.
Research-loop and direct memory-save responses do not currently expose this header.

## Capabilities and deployment

Skills cannot grant tools, credentials, memory namespaces, shell access, or network
access. Tools still depend on the profile, identity policy, and tools supplied by
the client. The shared routing instructions require honest capability reporting;
they do not install Python execution or web search. Missing source access must
remain an evidence gap. Prompt instructions are not a security boundary.

School base prompts retain their role and writing preferences; reusable procedures
live in skills. No private biography or memory records were moved into skill files.
Incoming UI system/developer prompts remain subject to the existing profile policy.

Docker copies the skills into the image. After changing skill files, rebuild and
recreate the service; restarting alone does not update image-owned files. Native
runs load them at process startup. There is no hot reload or public skill upload.

Rollback for the first the harness host deployment: restore files from
`/root/harness-before-skills-20261011.tar` into `/root/local-ai-harness`, then rebuild
and recreate the service. Added skill files may remain unused after restoring the
old application, Dockerfile, and profiles. Memory and identity files are unaffected.

## Validation

Regression suite: 211 passed, 27 skipped for optional integration requirements.
Live synthetic checks passed on both school profiles: draft-only proofreading,
explicit three-section APA review, and HTTP 400 for an unavailable skill. This
verifies the harness endpoint; client-specific behavior still needs user testing.


APA review quality rules: identify only actual correction needs, never fill missing
reference metadata by guessing (even conditionally), distinguish formatting checks
from source verification, and state unresolved checks without blanket submission
approval. Ask for the actual source details within the APA section when needed.


## Built-in UI selection (2026-10-14)

The `/chat/` Workflow picker lists each enabled skill by its first heading, and shows the first
sentence of the selected (or default) skill under the header. `/v1/profiles` exposes only that
title and sentence (`skill_info`), never the full instructions. A chosen workflow sticks to the
chat: the UI sends `/skill <id>` on every turn and saves the choice with the conversation.


## Skills from the chat UI

Besides these repository skills, each identity can keep its own Markdown skills in
`/chat/` (Settings → Skills; see [frontend/README.md](frontend/README.md#my-skills)).
They are stored in the chat database, not in `skills/`, need no profile change or restart,
and apply only when selected for a chat or project. The harness adds a selected one to
that request's system prompt after its own rules, as user-authored instructions that
cannot grant tools or override policy. Choosing a user skill and a `/skill` built-in on
the same turn is refused.

### Sharing a skill with a group

A signed-in account can share one of its skills with identity groups (the `role_grants`
names in the identity config, such as `harness_family`): open the skill and tick the group
under **Share with**. Members of that group see it under **Shared with me** in Settings →
Skills and in their Workflow menus, labelled with the owner's name. For them it is
read-only; **Duplicate** makes an editable copy of their own.

- Edits apply to members on their next message; there is no copy to keep in sync.
- The harness checks group membership each time the skill is used, not only when it is
  listed. Unticking a group, or deleting the skill, stops its use at once; members then see
  "That skill no longer exists or is no longer shared with you."
- Membership comes from the signed-in session, so a Pocket ID group change applies at the
  member's next sign-in.
- A shared skill is added to the system prompt as "Shared skill", naming its author, with
  the same limits as a user's own: it cannot grant tools or override harness rules.
- Sharing needs an OIDC (or JWT) account; the service key cannot share.
