"""Decision gate: ask a small decision model whether this turn needs memory or each tool.

One call to a llama.cpp decision model (`/v1/systemone`) scores the latest user message
against a yes/no question per target ("memory" and each gated MCP server). A target
scored below the profile's threshold is skipped for this request:

- memory: recall is not run, so no saved notes are added to the prompt.
- a server: it is removed from this request's tools, so its schemas and rules are not sent.
- skills (optional, Automatic chats only): instead of sending every skill and letting the
  main model choose, the harness sends only the highest-scoring skill, or none.

The gate only narrows what the profile and the chat already allow; it never adds memory
or a server. Any failure (not configured, timeout, bad response) leaves the request
exactly as it would have been without the gate. Logs carry scores, never message text.
"""
import json
import logging
import re
import time

from pydantic import BaseModel, ConfigDict, Field, model_validator

log = logging.getLogger("uvicorn.error")

# Questions are about the user's request, not about the tool, so the score reads as
# "does this turn need it". A profile may replace any of them with `questions`.
QUESTIONS = {
    "memory": "Does answering this need the user's saved personal notes, preferences or past decisions?",
    # Names the home lab: users ask about "my Proxmox node", not "my notes". The earlier
    # notes-only wording dropped the vault for most home-lab questions (10/14 vs 13/14).
    "vault": ("Does answering this need information about the user's own setup, such as their home lab hardware, "
              "configuration, services or past projects, or notes they have saved?"),
    "rag": "Does answering this need a search of reference documents in the knowledge base?",
    "kb": "Does answering this need the team's own runbooks or known fixes?",
    "web": "Does answering this need a live web search for current or external information?",
    "code": "Does answering this need running Python code to calculate, convert or analyze data?",
}
# Hand-written questions for the bundled skills. In testing these picked the right school
# workflow for 10 of 10 messages; questions built from a skill's title and first sentence
# picked 7 of 10. Other skills fall back to that generated question.
SKILL_QUESTIONS = {
    "discussion-draft": "Is the user asking you to draft a discussion board post or a peer response for a class?",
    "apa-review": "Is the user asking you to check APA formatting of citations or references?",
    "review-feedback": "Is the user asking for feedback or a review of their writing, without rewriting it for them?",
    "draft-rewrite": "Has the user pasted their own draft and asked you to correct or rewrite it?",
    "vault-research": ("Is the user asking about their own home lab setup, configuration, services or projects, "
                       "or asking to search or save notes in their Obsidian vault?"),
}
# Servers a skill's workflow depends on. The gate never drops these while that skill applies
# (picked by the user, the profile default, or the gate), so a workflow never loses its tools.
SKILL_SERVERS = {"vault-research": ("vault",)}
SKILL_KEY = re.compile(r"skill:[a-z][a-z0-9-]{0,63}")
MAX_STATE_CHARS = 4000


class DecisionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = False
    # Skip recall when the memory score is below threshold.
    memory: bool = True
    # Servers the gate may drop. Servers not listed always run when the chat selects them.
    servers: list[str] = Field(default_factory=list, max_length=8)
    # On Automatic chats, send only the skill the request matches (or none) instead of all.
    skills: bool = False
    threshold: float = Field(default=0.5, ge=0, le=1)
    timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    questions: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def known_targets(self):
        if len(set(self.servers)) != len(self.servers):
            raise ValueError("decision_gate.servers must be unique")
        unknown = (set(self.servers) | {k for k in self.questions if not SKILL_KEY.fullmatch(k)}) - set(QUESTIONS)
        if unknown:
            raise ValueError(f"decision_gate has no question for: {', '.join(sorted(unknown))}")
        if any(not q.strip() or len(q) > 500 for q in self.questions.values()):
            raise ValueError("decision_gate.questions must be nonblank and at most 500 characters")
        return self


def _latest_user_text(history):
    for message in reversed(history):
        if message["role"] == "user" and isinstance(message.get("content"), str):
            return message["content"][-MAX_STATE_CHARS:]
    return None


def skill_question(policy, skill, info):
    custom = policy.questions.get("skill:" + skill)
    if custom:
        return custom
    if skill in SKILL_QUESTIONS:
        return SKILL_QUESTIONS[skill]
    return f"Is the user asking for this workflow: {info['title']}? {info['description']}"[:500]


async def decide(app, profile, history, servers, memory_on, skills=(), pinned_skill=None):
    """Return (servers to run, whether to recall memory, skill, state for headers and logs).

    skill is None when the gate leaves the skills prompt alone, "" for no skill, or one
    skill id from `skills` (the candidates; empty unless this chat is on Automatic).
    pinned_skill is a skill that applies regardless of the gate (chosen by the user or the
    profile's default); servers it depends on are never put to the gate.
    """
    policy = profile.decision_gate
    state = {"status": "disabled", "scores": {}, "skipped": []}
    if not policy.enabled:
        return servers, memory_on, None, state
    protected = set(SKILL_SERVERS.get(pinned_skill, ()))
    targets = (["memory"] if policy.memory and memory_on else []) + [s for s in servers if s in policy.servers and s not in protected]
    skill_targets = ["skill:" + s for s in skills] if policy.skills else []
    text = _latest_user_text(history)
    if not (targets or skill_targets) or not text:
        state["status"] = "not_needed"
        return servers, memory_on, None, state
    if app.state.decision_url is None:
        state["status"] = "not_configured"
        return servers, memory_on, None, state
    questions = {t: {"type": "noul", "instructions": policy.questions.get(t, QUESTIONS[t])} for t in targets}
    questions.update({t: {"type": "noul", "instructions": skill_question(policy, t[6:], app.state.skill_info[t[6:]])} for t in skill_targets})
    targets = targets + skill_targets
    started = time.monotonic()
    try:
        response = await app.state.decision_client.post(
            app.state.decision_url + "/systemone", json={"state": text, "questions": questions},
            timeout=policy.timeout_seconds)
        response.raise_for_status()
        answers = response.json()["answers"]
        scores = {t: float(answers[t]["noul"]) for t in targets}
        if any(not 0 <= s <= 1 for s in scores.values()):
            raise ValueError("score out of range")
    except Exception as exc:  # Fail open: the request runs as if the gate were off.
        state["status"] = "unavailable"
        log.warning(json.dumps({"event": "decision_gate", "status": "unavailable", "error": type(exc).__name__,
                                "elapsed_ms": round((time.monotonic() - started) * 1000)}))
        return servers, memory_on, None, state
    skipped = {t for t, s in scores.items() if s < policy.threshold and not t.startswith("skill:")}
    skill = None
    if skill_targets:
        best = max(skill_targets, key=lambda t: scores[t])
        skill = best[6:] if scores[best] >= policy.threshold else ""
        state["skill"] = skill or "none"
        # A workflow the gate picked keeps the servers it needs, whatever they scored.
        skipped -= set(SKILL_SERVERS.get(skill, ()))
    state.update(status="decided", scores={t: round(s, 3) for t, s in scores.items()},
                 skipped=[t for t in targets if t in skipped])
    log.info(json.dumps({"event": "decision_gate", **state, "threshold": policy.threshold,
                         "elapsed_ms": round((time.monotonic() - started) * 1000)}))
    return tuple(s for s in servers if s not in skipped), memory_on and "memory" not in skipped, skill, state


def decision_headers(state):
    headers = {"X-Harness-Decision": state["status"]}
    if state["scores"]:
        headers["X-Harness-Decision-Scores"] = ",".join(f"{t}={s}" for t, s in state["scores"].items())
        headers["X-Harness-Decision-Skipped"] = ",".join(state["skipped"]) or "none"
    if "skill" in state:
        headers["X-Harness-Decision-Skill"] = state["skill"]
    return headers
