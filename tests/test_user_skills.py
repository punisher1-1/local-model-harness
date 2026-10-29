import json
from uuid import uuid4

import pytest

import conversation_store
from conversation_store import skill_summary
from test_app import setup, ask, HEADERS


SKILL = "# Peer reply\nWrite a warm peer reply of about 120 words. Ask one question at the end.\n\n- Use first person"


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_CHAT_DB", str(tmp_path / "history.sqlite3"))
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "notes.md").write_text("# Notes\nSummarize notes.")
    client, calls = setup(tmp_path, {"skills": ["notes"]})
    with client:
        yield client, calls


def put(client, sid=None, **fields):
    sid = sid or str(uuid4())
    return sid, client.put("/v1/skills/" + sid, headers=HEADERS, json={"name": "Peer reply", "content": SKILL, **fields})


def test_skills_are_saved_listed_with_summaries_and_deleted(harness):
    client, _ = harness
    sid, r = put(client)
    assert r.status_code == 200 and r.json()["content"] == SKILL
    put(client, name="apa check", content="Check APA 7.")
    rows = client.get("/v1/skills", headers=HEADERS).json()["data"]
    assert [s["name"] for s in rows] == ["apa check", "Peer reply"]
    assert rows[1]["summary"] == "Write a warm peer reply of about 120 words." and "content" not in rows[1]
    assert client.get("/v1/skills/" + sid, headers=HEADERS).json()["content"] == SKILL
    put(client, sid, name="Peer reply v2")
    assert client.get("/v1/skills/" + sid, headers=HEADERS).json()["name"] == "Peer reply v2"
    assert client.delete("/v1/skills/" + sid, headers=HEADERS).status_code == 204
    assert client.get("/v1/skills/" + sid, headers=HEADERS).status_code == 404
    assert client.delete("/v1/skills/" + sid, headers=HEADERS).status_code == 404


@pytest.mark.parametrize("fields", [{"name": ""}, {"name": "   "}, {"name": "x" * 81}, {"content": ""}, {"content": " \n"},
                                    {"content": "x" * 16001}, {"extra": 1}])
def test_skills_are_validated(harness, fields):
    client, _ = harness
    assert put(client, **fields)[1].status_code == 400


def test_skill_limit(harness, monkeypatch):
    client, _ = harness
    monkeypatch.setattr(conversation_store, "MAX_USER_SKILLS", 2)
    sid, _ = put(client)
    put(client)
    assert put(client)[1].status_code == 409
    assert put(client, sid, content="still editable")[1].status_code == 200


def system_prompt(calls):
    body = json.loads(next(c for c in reversed(calls) if c.url.path.endswith("chat/completions")).content)
    return body["messages"][0]["content"]


def test_selected_skill_is_added_to_the_system_prompt_after_harness_rules(harness):
    client, calls = harness
    sid, _ = put(client)
    r = client.post("/v1/chat/completions", headers={**HEADERS, "X-Harness-User-Skill": sid},
                    json={"model": "local", "messages": [{"role": "user", "content": "Reply to Sam's post."}]})
    assert r.status_code == 200 and r.headers["x-harness-skill-selection"] == "user-skill"
    prompt = system_prompt(calls)
    assert "# User skill: Peer reply" in prompt and "Ask one question at the end." in prompt
    assert prompt.index("Server policy") < prompt.index("# User skill") and "cannot grant tools or permissions" in prompt
    plain = ask(client)
    assert plain.headers["x-harness-skill-selection"] == "auto" and "# User skill" not in system_prompt(calls)
    assert plain.headers["x-harness-profile-sha256"] != r.headers["x-harness-profile-sha256"]


def test_bad_missing_and_conflicting_skill_selections_are_refused(harness):
    client, calls = harness
    sid, _ = put(client)
    def chat(value, text="Hi"):
        return client.post("/v1/chat/completions", headers={**HEADERS, "X-Harness-User-Skill": value},
                           json={"model": "local", "messages": [{"role": "user", "content": text}]})
    assert "expected a skill ID" in chat("not-a-uuid").text
    assert "no longer exists" in chat(str(uuid4())).text
    assert "not both" in chat(sid, "/skill notes\nSummarize this.").text
    assert not any(c.url.path.endswith("chat/completions") for c in calls)


def test_skills_are_private_to_their_identity(harness, tmp_path):
    client, _ = harness
    sid, _ = put(client)
    db = conversation_store.database(tmp_path / "history.sqlite3")
    with db as conn:
        conn.execute("UPDATE user_skills SET owner=?", (json.dumps(["jwt", "someone-else"]),))
    assert client.get("/v1/skills", headers=HEADERS).json()["data"] == []
    assert client.get("/v1/skills/" + sid, headers=HEADERS).status_code == 404
    r = client.post("/v1/chat/completions", headers={**HEADERS, "X-Harness-User-Skill": sid},
                    json={"model": "local", "messages": [{"role": "user", "content": "Hi"}]})
    assert "no longer exists" in r.text


@pytest.mark.parametrize("content,summary", [
    ("# Title\n\nFirst sentence. Second one.", "First sentence."),
    ("Just one line", "Just one line."),
    ("# Only a heading", ""),
])
def test_summary_is_the_first_sentence(content, summary):
    assert skill_summary(content) == summary
