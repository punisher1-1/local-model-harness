"""Skills shared with an identity group: live, read-only for members, checked on every use."""
from fastapi.testclient import TestClient

from test_oidc import KEY, UI, lab, sign_in  # noqa: F401  (fixture)

SID = "22222222-2222-4222-8222-222222222222"
SKILL = {"name": "Total Rewards reply", "content": "# Reply\nAnswer in 3 short paragraphs. End with a question."}


def two_people(lab):  # noqa: F811
    """Alice (harness-admin) and Beth (harness-family), each with their own session cookie."""
    alice, provider = lab()
    wife = TestClient(alice.app, base_url="http://harness.test")
    return alice, wife, provider


def sign_in_as(client, provider, sub, name, group):
    provider.claims = {"sub": sub, "name": name, "email": sub + "@example.test", "groups": [group]}
    sign_in(client, provider)


def ask_with(client, sid, model="family"):
    return client.post("/v1/chat/completions", headers={**UI, "X-Harness-User-Skill": sid},
                       json={"model": model, "messages": [{"role": "user", "content": "Draft my reply"}]})


def test_shared_skill_is_listed_read_only_and_used_with_live_edits(lab):  # noqa: F811
    alice, wife, provider = two_people(lab)
    with alice, wife:
        sign_in_as(alice, provider, "user-alice", "Alice", "harness-admin")
        listing = alice.get("/v1/skills", headers=UI).json()
        assert listing["share_groups"] == ["harness-admin", "harness-family"]
        saved = alice.put("/v1/skills/" + SID, headers=UI, json={**SKILL, "shared_groups": ["harness-family"]}).json()
        assert saved["shared_groups"] == ["harness-family"] and "shared" not in saved

        sign_in_as(wife, provider, "user-wife", "Beth", "harness-family")
        [item] = wife.get("/v1/skills", headers=UI).json()["data"]
        assert item == {"id": SID, "name": SKILL["name"], "summary": "Answer in 3 short paragraphs.",
                        "updated_at": item["updated_at"], "shared": True, "shared_by": "Alice"}
        assert wife.get("/v1/skills/" + SID, headers=UI).json()["content"] == SKILL["content"]

        assert ask_with(wife, SID).status_code == 200
        system = provider.backend_calls[-1]["messages"][0]["content"]
        assert "# Shared skill: Total Rewards reply" in system and "which Alice wrote and shared with them" in system
        assert "Answer in 3 short paragraphs." in system and system.index("Server policy") < system.index("# Shared skill")

        # Alice's edit reaches her next request with no copy or restart.
        alice.put("/v1/skills/" + SID, headers=UI, json={**SKILL, "content": "Use 2 paragraphs.", "shared_groups": ["harness-family"]})
        assert ask_with(wife, SID).status_code == 200
        assert "Use 2 paragraphs." in provider.backend_calls[-1]["messages"][0]["content"]

        # Read-only: she cannot delete it or save over its ID, so the ID always names Alice's skill.
        assert wife.delete("/v1/skills/" + SID, headers=UI).status_code == 404
        r = wife.put("/v1/skills/" + SID, headers=UI, json={"name": "Mine", "content": "Her version.", "shared_groups": ["harness-family"]})
        assert r.status_code == 409 and "belongs to another account" in r.text
        assert alice.get("/v1/skills/" + SID, headers=UI).json()["content"] == "Use 2 paragraphs."
        assert [s["shared_by"] for s in wife.get("/v1/skills", headers=UI).json()["data"]] == ["Alice"]


def test_unsharing_stops_listing_and_use_at_once(lab):  # noqa: F811
    alice, wife, provider = two_people(lab)
    with alice, wife:
        sign_in_as(alice, provider, "user-alice", "Alice", "harness-admin")
        alice.put("/v1/skills/" + SID, headers=UI, json={**SKILL, "shared_groups": ["harness-family"]})
        sign_in_as(wife, provider, "user-wife", "Beth", "harness-family")
        assert ask_with(wife, SID).status_code == 200

        alice.put("/v1/skills/" + SID, headers=UI, json={**SKILL, "shared_groups": []})
        assert wife.get("/v1/skills", headers=UI).json()["data"] == []
        assert wife.get("/v1/skills/" + SID, headers=UI).status_code == 404
        r = ask_with(wife, SID)
        assert r.status_code == 400 and "no longer shared with you" in r.text


def test_only_members_of_the_group_see_it(lab):  # noqa: F811
    alice, other, provider = two_people(lab)
    with alice, other:
        sign_in_as(alice, provider, "user-alice", "Alice", "harness-admin")
        alice.put("/v1/skills/" + SID, headers=UI, json={**SKILL, "shared_groups": ["harness-family"]})
        # Another admin is not in harness-family, so the skill stays out of reach.
        sign_in_as(other, provider, "user-other", "Other", "harness-admin")
        assert other.get("/v1/skills", headers=UI).json()["data"] == []
        assert ask_with(other, SID, model="local").status_code == 400


def test_sharing_needs_an_account_and_a_configured_group(lab):  # noqa: F811
    alice, _, provider = two_people(lab)
    with alice:
        key = {"Authorization": "Bearer " + KEY}
        r = alice.put("/v1/skills/" + SID, headers=key, json={**SKILL, "shared_groups": ["harness-family"]})
        assert r.status_code == 400 and "Sign in with your account" in r.text
        assert alice.get("/v1/skills", headers=key).json()["share_groups"] == []
        sign_in_as(alice, provider, "user-alice", "Alice", "harness-admin")
        r = alice.put("/v1/skills/" + SID, headers=UI, json={**SKILL, "shared_groups": ["everyone"]})
        assert r.status_code == 400 and "Unknown group: everyone" in r.text
