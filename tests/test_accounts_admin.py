"""Settings > Accounts: who has signed in and who is signed in now, for the admin grant only."""
from fastapi.testclient import TestClient

from test_oidc import KEY, UI, grants, lab, sign_in  # noqa: F401  (fixture)


def admin_grants():
    g = grants()
    g["harness-admin"]["accounts_admin"] = True
    return g


def sign_in_as(client, provider, sub, name, group):
    provider.claims = {"sub": sub, "name": name, "email": sub + "@example.test", "groups": [group]}
    sign_in(client, provider)


def test_admin_sees_every_account_and_who_is_signed_in(lab):  # noqa: F811
    alice, provider = lab(role_grants=admin_grants())
    cole = TestClient(alice.app, base_url="http://harness.test")
    with alice, cole:
        sign_in_as(alice, provider, "user-alice", "Alice", "harness-admin")
        sign_in_as(cole, provider, "user-cole", "Cole", "harness-family")
        assert alice.get("/v1/identity", headers=UI).json()["accounts_admin"] is True
        listing = alice.get("/v1/admin/accounts", headers=UI).json()
        rows = {r["name"]: r for r in listing["data"]}
        assert set(rows) == {"Alice", "Cole"} and listing["key_sessions"] == 0
        assert rows["Cole"]["sessions"] == 1 and rows["Cole"]["last_active"] and rows["Cole"]["groups"] == ["harness-family"]
        assert rows["Alice"]["you"] and not rows["Cole"]["you"] and rows["Cole"]["has_access"]
        assert all(k not in rows["Cole"] for k in ("actor_id", "subject", "issuer"))

        cole.delete("/v1/session", headers=UI)
        rows = {r["name"]: r for r in alice.get("/v1/admin/accounts", headers=UI).json()["data"]}
        assert rows["Cole"]["sessions"] == 0 and rows["Cole"]["last_active"] is None and rows["Alice"]["sessions"] == 1


def test_accounts_list_is_refused_without_the_grant(lab):  # noqa: F811
    alice, provider = lab(role_grants=admin_grants())
    cole = TestClient(alice.app, base_url="http://harness.test")
    with alice, cole:
        sign_in_as(cole, provider, "user-cole", "Cole", "harness-family")
        assert cole.get("/v1/identity", headers=UI).json()["accounts_admin"] is False
        assert cole.get("/v1/admin/accounts", headers=UI).status_code == 403
        # The app service key is not a person and never gets the list.
        assert alice.get("/v1/admin/accounts", headers={"Authorization": "Bearer " + KEY}).status_code == 403
        # A key session in the browser is counted, without naming anyone.
        assert alice.post("/v1/session", headers={**UI, "Authorization": "Bearer " + KEY}).status_code == 201
        sign_in_as(cole, provider, "user-alice", "Alice", "harness-admin")
        assert cole.get("/v1/admin/accounts", headers=UI).json()["key_sessions"] == 1


def test_grant_is_off_by_default(lab):  # noqa: F811
    client, provider = lab()
    with client:
        sign_in(client, provider)
        assert client.get("/v1/admin/accounts", headers=UI).status_code == 403
