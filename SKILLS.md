# Harness-managed skills

Skills are trusted repository Markdown instructions, separate from identity,
model settings, memory, and UI configuration. The bundled writing workflows target
academic editing; profiles that do not opt in are unchanged.

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
most 16 unique IDs and must name one as their default. Invalid configuration
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

Rollback: restore a reviewed source version, then rebuild
and recreate the service. Added skill files may remain unused after restoring the
old application, Dockerfile, and profiles. Memory and identity files are unaffected.

## Validation

Regression suite: 211 passed, 27 skipped for optional integration requirements.
Live synthetic checks passed on writing profiles: draft-only proofreading,
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
