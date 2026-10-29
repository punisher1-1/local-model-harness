# ADR-004: People sign in with OIDC; apps keep a scoped service key

**Status:** Accepted
**Date:** 2026-10-20
**Deciders:** Project owner
**Supersedes:** ADR-001 action items 3 and 4 (provider and token flow), and its rule that
a deployment has exactly one identity mode

## Context

Two people now use `/chat/`: the owner and a family member. Both sign in with the shared lab service
key, so the harness sees one `lab-service` identity. Every chat, project and skill sits
under that one owner, and nothing stops either person from using any profile. The
harness already enforces per-identity ownership (rows keyed by identity kind and actor)
and has an RS256 JWT verifier with role-to-grant mapping (ADR-001), but there is no
login flow, and its keys come from a hand-maintained JWKS file.

The design must also serve as a template for a work deployment, where people sign in
through the company's identity provider (likely Microsoft Entra ID) and the harness
must never hold their passwords.

Open WebUI, BoltAI and n8n call the harness as applications. They cannot complete a
browser sign-in, so they still need a credential of their own.

## Decision

1. **People sign in with OpenID Connect**, using the authorization code flow with PKCE
   (S256), state and nonce. The harness is the OIDC client and does the code exchange
   server-side; tokens never reach the browser. After it verifies the ID token, it
   issues its existing HttpOnly session cookie. The harness stores no passwords.
2. **Pocket ID is the home provider:** a single container whose only sign-in is
   passkeys. Work deployments swap the issuer, client and claim name for Entra ID or
   any other OIDC provider, with no code change.
3. **Keys come from the issuer's discovery document** and are cached. An unknown `kid`
   triggers a rate-limited JWKS refresh, so key rotation needs no restart. Accepted
   algorithms: RS256, ES256 and EdDSA, taken from the key and never from the token.
   Only the configured issuer's `jwks_uri` is fetched, never a token-supplied URL.
4. **Groups map to grants.** The groups claim is configurable (`groups` for Pocket ID,
   `roles` for Entra app roles) and goes through the existing `role_grants` union. A
   user with no granted profile is refused at sign-in with a clear message.
5. **The service key coexists, scoped.** In `oidc` mode a bearer service key is still
   accepted, but only with the grant written under `service_key:`. Leaving that out
   disables the key. This is not a fallback: each credential is verified in its own way,
   and a failed OIDC sign-in never becomes a service-key session. `allow_key_sign_in`
   controls whether the browser form also accepts the key, as a fallback if the
   provider is down.
6. **Existing data moves once, on request.** `scripts/claim_shared_data.py` moves chats,
   projects and skills from the `lab-service` owner to a signed-in account. It does a
   dry run by default.
7. **Provider outages never stop the harness.** Discovery happens at sign-in, not at
   startup, so an unreachable Pocket ID breaks only new sign-ins.

## Options considered

| Option | Complexity | Scales to work | Password handling | Notes |
|---|---|---|---|---|
| Accounts and passwords in the harness | Low at first | Poorly: no SSO | Harness owns hashing, resets, MFA | Rewritten for work anyway |
| Reverse-proxy auth headers (Authelia, oauth2-proxy) | Low | Partly | Proxy | The harness must trust headers; ADR-001 rejected unverified headers |
| **OIDC client in the harness** | Moderate | Yes, standard | Provider | Chosen |
| Authentik or Keycloak as the home provider | Higher operations | Yes | Provider | Too heavy for two users; easy to swap in later |

## Consequences

- Each person gets their own chats, projects, skills and permissions. Your wife's grant
  can be limited to her profiles and her own memory scope.
- Group changes in Pocket ID apply at the next sign-in. Existing sessions keep their
  grants until they expire (12 hours idle, 7 days at most) or the person signs out.
  There is no back-channel logout.
- Signing out ends the harness session, not the Pocket ID session; with passkeys, signing
  back in is one tap.
- The service key remains a shared secret for apps. Scope it to what those apps need.
- Passkeys need HTTPS on Pocket ID's own hostname. The harness can stay on LAN HTTP, but
  HTTPS through Nginx Proxy Manager is recommended so the session cookie is `Secure`.

## Action items

1. [x] OIDC sign-in, discovery, JWKS rotation, groups-to-grants and scoped service key
2. [x] Sign-in UI, account display and the shared-data migration script
3. [x] Pocket ID stack in `homelab-stacks`
4. [ ] Deploy Pocket ID behind HTTPS, register the harness client, create the groups
5. [ ] Switch the harness host to `oidc` mode, migrate the shared data, then narrow the service key
