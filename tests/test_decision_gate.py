import json

import httpx
import pytest
from pydantic import ValidationError

from app import Profile
from test_app import setup, ask, HEADERS
from test_mcp_selection import vault, recorder, mcp_ask, TOOLS, VAULT_RULE  # noqa: F401 (fixture)

RECALL = {"memory_recall": {"enabled": True, "max_memories": 4, "max_context_bytes": 4096}}
NOTE = "Saved memory: prefer short answers."


@pytest.fixture
def memory_lab(monkeypatch):
    """Stand-in for recall: real recall needs PostgreSQL and has its own tests (test_recall.py).
    These tests only need to see whether the gate let recall run."""
    async def fake_recall(app, profile, principal, messages):
        messages[-1] = {**messages[-1], "content": NOTE + "\n" + messages[-1]["content"]}
        return {"status": "recalled", "count": 1, "bytes": len(NOTE)}
    monkeypatch.setattr("app.apply_recall", fake_recall)


@pytest.fixture
def decision_url(monkeypatch):
    monkeypatch.setenv("HARNESS_DECISION_URL", "http://decision:8090/v1")


def scorer(scores, seen=None, chain=None):
    """Fake /v1/systemone: answer each asked question with the given score."""
    def handler(request):
        if request.url.host == "decision":
            body = json.loads(request.content)
            if seen is not None:
                seen.append({"auth": request.headers.get("authorization"), **body})
            if scores is None:
                return httpx.Response(500)
            return httpx.Response(200, json={"answers": {k: {"type": "noul", "noul": scores[k]} for k in body["questions"]}})
        return chain(request) if chain else None
    return handler


def test_low_memory_score_skips_recall(tmp_path, memory_lab, decision_url):
    seen = []
    client, calls = setup(tmp_path, {**RECALL, "decision_gate": {"enabled": True}}, handler=scorer({"memory": 0.2}, seen))
    with client:
        r = ask(client, messages=[{"role": "user", "content": "What is 2 + 2?"}])
        assert r.status_code == 200
        assert r.headers["x-harness-memory-status"] == "gated"
        assert r.headers["x-harness-decision"] == "decided"
        assert r.headers["x-harness-decision-skipped"] == "memory"
        assert NOTE not in calls[-1].content.decode()
        assert seen[0]["state"] == "What is 2 + 2?" and list(seen[0]["questions"]) == ["memory"]


def test_high_memory_score_keeps_recall(tmp_path, memory_lab, decision_url):
    client, calls = setup(tmp_path, {**RECALL, "decision_gate": {"enabled": True}}, handler=scorer({"memory": 0.79}))
    with client:
        r = ask(client, messages=[{"role": "user", "content": "What did I decide about the reranker?"}])
        assert r.headers["x-harness-memory-status"] == "recalled"
        assert r.headers["x-harness-decision-scores"] == "memory=0.79"
        assert r.headers["x-harness-decision-skipped"] == "none"


def test_unavailable_decision_model_fails_open(tmp_path, memory_lab, decision_url):
    client, calls = setup(tmp_path, {**RECALL, "decision_gate": {"enabled": True}}, handler=scorer(None))
    with client:
        r = ask(client)
        assert r.status_code == 200
        assert r.headers["x-harness-decision"] == "unavailable"
        assert r.headers["x-harness-memory-status"] == "recalled"


def test_missing_url_runs_ungated(tmp_path, memory_lab, monkeypatch):
    monkeypatch.delenv("HARNESS_DECISION_URL", raising=False)
    client, calls = setup(tmp_path, {**RECALL, "decision_gate": {"enabled": True}})
    with client:
        r = ask(client)
        assert r.headers["x-harness-decision"] == "not_configured"
        assert r.headers["x-harness-memory-status"] == "recalled"
        assert not any(c.url.host == "decision" for c in calls)


def test_gate_drops_only_listed_low_scoring_servers(tmp_path, vault, decision_url):
    rounds, seen = [], []
    gate = {"enabled": True, "servers": ["vault"]}
    client, _ = setup(tmp_path, {**TOOLS, "mcp_servers": ["vault"], "decision_gate": gate},
                      handler=scorer({"vault": 0.1}, seen, recorder(rounds)))
    with client:
        r = mcp_ask(client, "vault")
        assert r.status_code == 200 and r.headers["x-harness-mcp"] == "none"
        assert vault == [] and "tools" not in rounds[0] and VAULT_RULE not in rounds[0]["messages"][0]["content"]
        assert list(seen[0]["questions"]) == ["vault"]


def test_gate_keeps_high_scoring_servers(tmp_path, vault, decision_url):
    rounds = []
    client, _ = setup(tmp_path, {**TOOLS, "mcp_servers": ["vault"], "decision_gate": {"enabled": True, "servers": ["vault"]}},
                      handler=scorer({"vault": 0.9}, None, recorder(rounds)))
    with client:
        r = mcp_ask(client, "vault")
        assert r.headers["x-harness-mcp"] == "vault" and vault == ["vault_search"]


def test_gate_never_adds_a_server_the_chat_turned_off(tmp_path, vault, decision_url):
    seen = []
    client, _ = setup(tmp_path, {**TOOLS, "mcp_servers": ["vault"], "decision_gate": {"enabled": True, "servers": ["vault"]}},
                      handler=scorer({"vault": 1.0}, seen, recorder([])))
    with client:
        r = mcp_ask(client, "none")
        assert r.headers["x-harness-mcp"] == "none" and r.headers["x-harness-decision"] == "not_needed"
        assert seen == []


def test_disabled_gate_never_calls_the_decision_model(tmp_path, memory_lab, decision_url):
    client, calls = setup(tmp_path, RECALL)
    with client:
        r = ask(client)
        assert r.headers["x-harness-decision"] == "disabled"
        assert not any(c.url.host == "decision" for c in calls)


def test_generation_key_is_not_sent_to_decision_model(tmp_path, memory_lab, decision_url, monkeypatch):
    monkeypatch.setenv("GEN_API_KEY", "generation-secret")
    monkeypatch.setenv("HARNESS_DECISION_API_KEY", "decision-secret")
    seen = []
    client, _ = setup(tmp_path, {**RECALL, "decision_gate": {"enabled": True}}, handler=scorer({"memory": 0.9}, seen))
    with client:
        ask(client)
        assert seen[0]["auth"] == "Bearer decision-secret"


def test_save_command_skips_the_gate(tmp_path, memory_lab, decision_url):
    seen = []
    client, _ = setup(tmp_path, {**RECALL, "chat_memory": True, "decision_gate": {"enabled": True}}, handler=scorer({"memory": 0.0}, seen))
    with client:
        # No memory store in this test, so the save itself fails; the gate must not have run first.
        ask(client, messages=[{"role": "user", "content": "Remember: fact: The reranker stays on the old GPU."}])
        assert seen == []


def test_policy_validation():
    base = {"backend_model": "m", "system_prompt_file": "p.md"}
    with pytest.raises(ValidationError):
        Profile.model_validate({**base, "decision_gate": {"enabled": True, "servers": ["web"]}})  # web not in mcp_servers
    with pytest.raises(ValidationError):
        Profile.model_validate({**base, "decision_gate": {"questions": {"email": "Need email?"}}})
    with pytest.raises(ValidationError):
        Profile.model_validate({**base, "decision_gate": {"threshold": 1.5}})


# Skill selection on Automatic chats.

APA = "# APA 7 review, when requested\nAPA-WORKFLOW-BODY."
REVIEW = "# Review without rewriting\nREVIEW-WORKFLOW-BODY."
SKILLS = {"skills": ["apa-review", "review-feedback"], "decision_gate": {"enabled": True, "memory": False, "skills": True}}


def skill_setup(tmp_path, scores, seen=None, profile=None):
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "apa-review.md").write_text(APA)
    (tmp_path / "skills" / "review-feedback.md").write_text(REVIEW)
    return setup(tmp_path, {**SKILLS, **(profile or {})}, handler=scorer(scores, seen))


def system_prompt(calls):
    return json.loads(next(c for c in reversed(calls) if c.url.path.endswith("/chat/completions")).content)["messages"][0]["content"]


def test_high_scoring_skill_is_the_only_one_sent(tmp_path, decision_url):
    seen = []
    client, calls = skill_setup(tmp_path, {"skill:apa-review": 0.98, "skill:review-feedback": 0.6}, seen)
    with client:
        r = ask(client, messages=[{"role": "user", "content": "Check the APA formatting of my references."}])
        assert r.headers["x-harness-decision-skill"] == "apa-review"
        prompt = system_prompt(calls)
        assert "APA-WORKFLOW-BODY" in prompt and "REVIEW-WORKFLOW-BODY" not in prompt
        assert "selected the apa-review workflow" in prompt
        from decision_gate import SKILL_QUESTIONS
        assert seen[0]["questions"]["skill:apa-review"]["instructions"] == SKILL_QUESTIONS["apa-review"]


def test_no_skill_sent_when_none_matches(tmp_path, decision_url):
    client, calls = skill_setup(tmp_path, {"skill:apa-review": 0.1, "skill:review-feedback": 0.3})
    with client:
        r = ask(client, messages=[{"role": "user", "content": "What is 2 + 2?"}])
        assert r.headers["x-harness-decision-skill"] == "none"
        prompt = system_prompt(calls)
        assert "WORKFLOW-BODY" not in prompt and "# Available skills" not in prompt


def test_explicit_skill_is_never_overridden(tmp_path, decision_url):
    seen = []
    client, calls = skill_setup(tmp_path, {"skill:apa-review": 0.99, "skill:review-feedback": 0.0}, seen)
    with client:
        r = ask(client, messages=[{"role": "user", "content": "/skill review-feedback Look at my draft."}])
        assert r.status_code == 200 and "x-harness-decision-skill" not in r.headers
        assert "REVIEW-WORKFLOW-BODY" in system_prompt(calls)
        assert seen == []  # nothing else to decide, so d1 was not called


def test_unavailable_decision_model_keeps_every_skill(tmp_path, decision_url):
    client, calls = skill_setup(tmp_path, None)
    with client:
        r = ask(client)
        assert r.headers["x-harness-decision"] == "unavailable"
        prompt = system_prompt(calls)
        assert "APA-WORKFLOW-BODY" in prompt and "REVIEW-WORKFLOW-BODY" in prompt


def test_skill_selection_off_keeps_every_skill(tmp_path, decision_url):
    client, calls = skill_setup(tmp_path, {}, profile={"decision_gate": {"enabled": True, "memory": False}})
    with client:
        r = ask(client)
        assert r.headers["x-harness-decision"] == "not_needed"
        assert "APA-WORKFLOW-BODY" in system_prompt(calls) and "REVIEW-WORKFLOW-BODY" in system_prompt(calls)


def test_custom_skill_question(tmp_path, decision_url):
    seen = []
    gate = {**SKILLS["decision_gate"], "questions": {"skill:apa-review": "Is this about citations?"}}
    client, _ = skill_setup(tmp_path, {"skill:apa-review": 0.9, "skill:review-feedback": 0.1}, seen, {"decision_gate": gate})
    with client:
        ask(client)
        assert seen[0]["questions"]["skill:apa-review"]["instructions"] == "Is this about citations?"


def test_full_prompt_is_unchanged_by_the_refactor(tmp_path):
    from types import SimpleNamespace
    from skill_loader import load_skills
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "apa-review.md").write_text(APA)
    profile = SimpleNamespace(skills=["apa-review"], default_skill=None)
    text = load_skills(tmp_path, profile)
    assert text.startswith("\n\n# Available skills\n") and text.endswith("## Skill: apa-review\n" + APA)
    assert load_skills(tmp_path, profile, "") == ""


def test_skill_selection_validation():
    base = {"backend_model": "m", "system_prompt_file": "p.md"}
    with pytest.raises(ValidationError):  # no skills
        Profile.model_validate({**base, "decision_gate": {"enabled": True, "skills": True}})
    with pytest.raises(ValidationError):  # a default workflow is not Automatic
        Profile.model_validate({**base, "skills": ["apa-review"], "default_skill": "apa-review", "decision_gate": {"skills": True}})
    with pytest.raises(ValidationError):  # question for a skill the profile lacks
        Profile.model_validate({**base, "skills": ["apa-review"], "decision_gate": {"questions": {"skill:other": "Q?"}}})
    Profile.model_validate({**base, "skills": ["apa-review"], "decision_gate": {"skills": True, "questions": {"skill:apa-review": "Q?"}}})


# A workflow keeps the servers it depends on (vault-research needs the vault).

VAULT_SKILL = "# Vault research\nVAULT-WORKFLOW-BODY."


def vault_skill_setup(tmp_path, scores, seen, rounds, profile=None):
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "vault-research.md").write_text(VAULT_SKILL)
    gate = {"enabled": True, "memory": False, "servers": ["vault"], "skills": True}
    base = {**TOOLS, "mcp_servers": ["vault"], "skills": ["vault-research"], "decision_gate": gate}
    return setup(tmp_path, {**base, **(profile or {})}, handler=scorer(scores, seen, recorder(rounds)))


def vault_chat(client, text):
    return client.post("/v1/chat/completions", headers={**HEADERS, "X-Harness-MCP": "vault"},
                       json={"model": "local", "messages": [{"role": "user", "content": text}]})


def test_explicit_vault_research_keeps_the_vault(tmp_path, vault, decision_url):
    seen, rounds = [], []
    client, _ = vault_skill_setup(tmp_path, {"vault": 0.05}, seen, rounds)
    with client:
        r = vault_chat(client, "/skill vault-research Which containers run on node2?")
        assert r.status_code == 200 and r.headers["x-harness-mcp"] == "vault"
        assert vault == ["vault_search"]
        assert seen == []  # the vault was never put to the gate, and nothing else needed deciding


def test_gate_picked_vault_research_keeps_the_vault(tmp_path, vault, decision_url):
    seen, rounds = [], []
    client, _ = vault_skill_setup(tmp_path, {"vault": 0.2, "skill:vault-research": 0.9}, seen, rounds)
    with client:
        r = vault_chat(client, "Which containers run on node2?")
        assert r.headers["x-harness-decision-skill"] == "vault-research"
        assert r.headers["x-harness-mcp"] == "vault" and r.headers["x-harness-decision-skipped"] == "none"
        assert vault == ["vault_search"]


def test_default_vault_research_keeps_the_vault(tmp_path, vault, decision_url):
    seen, rounds = [], []
    gate = {"enabled": True, "memory": False, "servers": ["vault"]}
    client, _ = vault_skill_setup(tmp_path, {"vault": 0.05}, seen, rounds,
                                  {"default_skill": "vault-research", "decision_gate": gate})
    with client:
        r = vault_chat(client, "Which containers run on node2?")
        assert r.headers["x-harness-mcp"] == "vault" and seen == []


def test_vault_still_dropped_when_no_vault_workflow_applies(tmp_path, vault, decision_url):
    seen, rounds = [], []
    client, _ = vault_skill_setup(tmp_path, {"vault": 0.05, "skill:vault-research": 0.1}, seen, rounds)
    with client:
        r = vault_chat(client, "Write a haiku about autumn.")
        assert r.headers["x-harness-decision-skill"] == "none" and r.headers["x-harness-mcp"] == "none"
        assert vault == []
