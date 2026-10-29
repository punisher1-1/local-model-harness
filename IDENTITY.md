# Identity and authorization scaffold

Implemented 2026-09-07; OIDC sign-in added 2026-10-20 (ADR-004). Default lab mode remains
a shared service key. JWT mode verifies bearer tokens against configured keys; OIDC mode
signs people in to `/chat/` through an identity provider such as Pocket ID and keeps a
scoped service key for apps.
This is not a production SSO rollout or a per-document authorization system.

## What is enforced

| Boundary | Behavior |
|---|---|
| Authentication | One explicit mode per deployment: service key, JWT or OIDC. A failed token or sign-in never falls back to the service key; in OIDC mode the key is a separately granted app credential. |
| Discovery | `/v1/models` lists only the verified principal's granted profiles. |
| Profile use | Direct `/v1/chat/completions` requests require profile permission before calling vLLM. |
| Tool advertisement | Research advertises only the intersection of the profile's two tools, verified tool grants, and the demo collection grant. |
| Tool execution | Profile, tool and collection permissions are checked again before the Python operation; fabricated calls cannot bypass the check. |
| Identity source | `user`, `metadata`, chat claims, and forwarded identity headers do not grant permissions. |
| Expiry | Checked at admission, before each research model round and immediately before tool execution. |

Identity is represented by an immutable `Principal`; verified roles map to local
policy grants. Grants from multiple roles are combined by union. Unknown roles give
no grants, not an administrator default. Token role names have meaning only through
this server's configured mapping. A valid token with no grants gets an empty model
list and 403 for a known profile. Invalid tokens get 401. Ordinary client tool
injection remains rejected. Once streaming starts, errors travel as SSE error events.

## Lab mode (active)

Leave `HARNESS_IDENTITY_CONFIG` unset or empty and keep `HARNESS_API_KEY` configured.
Every holder of this key is the same `lab-service` identity, with the current
configured profiles and demo tools. This preserves existing Open WebUI behavior.
It is not proof that a particular person is using the service, even on a personal
network. No JWT signing keys, issuer, or login server are needed in this mode.

Authenticated `GET /v1/identity` reports identity kind, an actor identifier, granted
profiles/tools/collections and expiry. `jwt_subject` means a verified token subject;
it does not by itself prove a human user rather than a workload. Tool grants reported
there are raw grants; actual use also requires profile and collection permission.

## OIDC mode: people sign in with Pocket ID (ADR-004)

[ADR-004](docs/ADR-004-oidc-sign-in.md) adds `mode: oidc`. People click **Sign in with
Pocket ID** in `/chat/` and use a passkey (Face ID or Touch ID). The harness runs the
authorization code flow with PKCE, state and nonce, exchanges the code server-side,
verifies the ID token, and issues its usual HttpOnly session cookie. Tokens never reach
the browser, and the harness stores no passwords.

| Boundary | Behavior |
|---|---|
| Discovery | Read from `<issuer>/.well-known/openid-configuration` at sign-in, not at startup. Its issuer must match exactly; every endpoint must be HTTPS on the issuer's host; S256 PKCE must be supported. |
| Keys | From the issuer's `jwks_uri`, cached for an hour. An unknown `kid` refreshes them at most once a minute. RS256, ES256 and EdDSA; the algorithm comes from the published key, not the token. |
| ID token | Exact issuer and `client_id` audience (`azp` checked when there are several), `exp`/`iat` with 60 s leeway, single-use nonce, optional `required_claims`. |
| Login state | Ten minutes, single use, bound to the browser by an HttpOnly `harness_oidc` cookie (SameSite=Lax, path `/v1/auth`). |
| Grants | `roles_claim` (`groups` for Pocket ID) through `role_grants`, combined by union. A user with no granted profile is sent back with "no access". |
| Owner | `jwt_subject` plus a hash of issuer and subject, so chats, projects, skills and permissions are per person. |
| Service key | Accepted as a bearer credential only with the `service_key:` grant; omit it to disable the key. `allow_key_sign_in` controls the browser form. |
| Lifetime | The harness session (12 hours idle, 7 days at most). Group changes apply at the next sign-in. Sign out ends the harness session only. |

Failed sign-ins return to `/chat/?auth_error=<code>`, which the page explains:
`cancelled`, `expired`, `no_access`, `provider_unavailable`, `provider_misconfigured`,
`exchange_failed`, `invalid_token`, `failed`. Logs record the outcome and actor hash only.

### Setting it up

1. **Deploy Pocket ID** from `homelab-stacks` (`stacks/pocket-id`) behind Nginx Proxy
   Manager with a real certificate, for example `https://id.example.com`. Passkeys are
   bound to that hostname, so choose it once. Register your passkey as the first admin.
2. **Create groups** in Pocket ID: `harness_admin` (you) and `harness_family` (your wife).
   The token carries each group's **Name**, not its Friendly name, and Pocket ID turns
   hyphens in the Name into underscores. The keys under `role_grants` must match the
   Name exactly; a mismatch signs you in but reports "no access".
   Create her account and send her the sign-up link; she registers her own passkey.
3. **Add an OIDC client** named Local Model Harness, with callback URL
   `http://<harness host>:8200/v1/auth/callback` (or your HTTPS harness URL). Allow it for
   both groups. Copy the client ID and secret.
4. **On the harness host**, copy [examples/identity.oidc.example.yaml](examples/identity.oidc.example.yaml)
   to `identity-config/identity.yaml`, set `issuer`, `client_id` and `redirect_uri`, and
   check the profile names and memory scopes. In `.env` set
   `HARNESS_IDENTITY_CONFIG=/app/identity-config/identity.yaml` and
   `HARNESS_OIDC_CLIENT_SECRET=...`. Mount the folder (override below), then
   `docker compose up -d --force-recreate`.
5. **The harness host must reach Pocket ID by its HTTPS name.** Check with
   `docker compose exec local-model-harness python -c "import httpx;print(httpx.get('https://id.example.com/.well-known/openid-configuration').status_code)"`.
6. **Sign in once**, then move the shared data to your account:
   `docker compose exec local-model-harness python scripts/claim_shared_data.py` lists
   accounts; add `--to you@example.com`, then `--apply`. Take a backup first.
7. **Narrow the `service_key` grant** to what Open WebUI, BoltAI and n8n actually use.

For a work deployment, point `issuer`, `client_id` and `roles_claim` at the company's
provider (Entra ID app roles: `roles_claim: roles`); nothing else changes.

## JWT mode (opt-in, locally configured public keys)

The verifier accepts only **RS256** with a configured RSA public key of at least
2048 bits. It requires a known `kid`, valid signature, exact issuer, a single exact
API audience, nonempty subject, integer `iat`/`exp`, and valid `nbf` if supplied.
It checks expiry/future issuance with zero clock leeway. Keep host clocks synchronized.
The token's algorithm does not choose verification policy. Token-supplied `jku`,
`jwk`, `x5u`, and unsupported critical headers are rejected; no URL is fetched.

`required_claims` optionally pins additional exact string claims, such as the
approved client application's `azp` and a provider-specific tenant ID. Configure
these based on the issuer's **access token** contract. Do not use a UI's ID token
or session JWT as a substitute. Give the API its own audience distinct from the
UI registration, and choose user vs workload authorization explicitly.

See [examples/identity.jwt.example.yaml](examples/identity.jwt.example.yaml).
The public JWKS file contains a `keys` array of RSA public JWKs with unique `kid`
values, optionally `alg: RS256`, `use: sig`, and `key_ops: [verify]`. Private key
material is rejected at startup. Relative `jwks_file` paths resolve beside the
identity config. Only operator-configured files are read; tokens cannot select paths.

To activate in a separate test deployment:

1. Obtain public signing keys through your identity provider's trusted administrative
   process. Set the exact issuer, API audience, allowed client claims, and role mapping.
2. Mount a directory containing the identity YAML and public JWKS read-only at
   `/app/identity-config`. Do not mount private signing keys.
3. Set `HARNESS_IDENTITY_CONFIG=/app/identity-config/identity.yaml` in that deployment's
   `.env`, then recreate the container. JWT mode does not require or accept the lab key.
4. Send a valid API access token in `Authorization: Bearer ...`. Check `/v1/identity`
   and `/v1/models`, then test an allowed and a denied profile before real data.

Example Compose override to combine with the existing compose file:

```yaml
services:
  local-model-harness:
    volumes:
      - ./identity-config:/app/identity-config:ro
```

The base image does not bundle an active identity configuration or keys. No work
provider is inferred from these examples. Switching the current lab to JWT mode
before arranging token acquisition/forwarding would break its shared-key connection.

## Open WebUI and the enterprise boundary

Signing into Open WebUI with an enterprise account does not automatically give the
harness a verifiable user identity: a connection may still send one shared API key.
We have not configured or verified end-user token forwarding in this deployment.
The next integration needs an API-audience access token passed by a trusted connector
or gateway. Do not trust plain username, email, role, or `X-Forwarded-*` headers from
an arbitrary client. Keep the same backend authorization through direct API access.

Public keys and permission config load once at startup. There is no automatic JWKS
refresh, issuer discovery, token introspection, or immediate revocation. For rotation,
install the trusted overlapping public key set and restart; remove retired keys and
restart according to the provider's rotation policy. Unknown keys fail closed until
configured. The current local-file adapter is suitable for controlled scaffolding;
operational key refresh and revocation require a later provider-specific integration.

The collection permission currently covers **the entire synthetic demo catalog**.
There are no caller-owned tickets, payroll data or document ACLs yet. The separate
[explicit memory API](MEMORY.md) now uses principal-derived owner scopes and forced
row-level security. Do not treat `demo_notes` as a general private-data
permission. Resource checks must also exist in a future data service. TLS, network
isolation, rate limiting, token acquisition and audit retention remain deployment
responsibilities. In-flight generation can finish after token expiry; the next
research round/tool execution is blocked. Policy changes take effect after restart,
and there is no mid-request external revocation lookup.

## Audit and verification

Authorization events include the principal kind, an actor identifier (SHA-256 of
issuer and subject for JWTs), action, configured resource/tool, decision, identity policy hash and configured public-key-set hash. Research tool
authorization events also include the generation request ID. No raw token, claims, prompt or tool arguments are logged. Hashed actor
IDs are still correlatable identifiers: choose access and retention accordingly.
These events are not a complete compliance audit; authentication failures and
end-to-end identity-provider events need separate coverage.

Run `.venv/bin/python -m pytest -q tests/test_identity.py` after installing
`requirements-dev.txt`. Tests generate ephemeral RSA keys and synthetic tokens,
use mocked vLLM responses, and make no identity-provider/GPU/network requests.
They cover expiry and claim validation, signatures and key headers, no service-key
fallback, hidden/denied profiles, ignored client roles, tool/collection enforcement,
expiry before execution, streaming denials, and invalid startup configurations.
The full suite passed 83 cases when this scaffold was added.

## Before cloning to work machines

Clone the repository and provision a new environment, credentials and trusted public
key configuration. Do not copy the lab `.env`, signed tokens, SSH identities, or
private keys into the work deployment. Confirm model endpoints, identity mode,
API audience, role grants and the demo corpus explicitly. Keep JWT mode opt-in until
the work identity/token flow has been tested end to end.

References: [PyJWT verification API](https://pyjwt.readthedocs.io/en/stable/api.html),
[Microsoft API claims validation](https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation).

## Container verification (2026-09-07)

An isolated process in the rebuilt harness image verified synthetic JWTs with temporary
keys and a mocked backend. A Chat-role subject saw only `local-assistant` and could
call it. A Research-role subject saw only `local-research` and received 403 when
requesting the assistant, even with forged role metadata; no model request occurred.
An unknown role saw no profiles and was denied; an expired token received 401.
This verifies the packaged scaffold, not an enterprise login flow. The live service
remains in service-key mode and its identity endpoint reports `lab-service`.

Live readiness and streaming checks passed for assistant, creative and research.
The research check executed search/read tools and completed without SSE errors.
Rollback archive on the harness host: `/root/harness-before-identity-20260907.tar`; the live `.env`
was preserved. No work identity provider, JWT config, or public keys were installed
in the live service.

## Memory permissions

JWT role grants can include `memory_permissions: [memory.read, memory.write,
memory.delete]`, independently of profiles and research tools. Omitted permissions
grant no memory access. The same verified issuer/subject actor ID owns records across
chats; request-body owner fields and user metadata cannot select another owner.
Token expiry is checked again after waiting for a database connection.

The live lab remains in shared-key mode. The owner explicitly opted into
`allow_shared_service_identity: true` in the separate memory configuration, granting
all three operations to `lab-service`. Every key holder shares that scope. Changing
to JWT mode does not automatically transfer or reveal service-owned records.
`/v1/identity` reports effective memory permissions; see MEMORY.md for transport,
retention, backups and the limits of application-set database identity context.

## Client-tool transport and operator metrics — 2026-09-10

Role grants now support two independent booleans, omitted/false by default:
`client_tools` and `backend_metrics`. A caller needs both a `local-tools` profile grant
and `client_tools: true` to use that profile. This authorizes transport of client
functions; it does not authorize or authenticate their execution in BoltAI/Open WebUI.
The executor controls tool permissions, resource scopes and write approvals.
`backend_metrics: true` grants access to `/v1/backend/metrics`, which exposes shared
backend-wide statistics rather than user-specific accounting. Do not grant it to every
enterprise chat user. Both capabilities are reported by `/v1/identity` and enabled
for the existing personal lab service key. Existing JWT grants do not gain access.

Example additions inside a verified operator role's grant (not request-body claims):

```yaml
profiles: [local-tools]
client_tools: true
backend_metrics: true
```

See [TOOLS_AND_MODELS.md](TOOLS_AND_MODELS.md) and [TELEMETRY.md](TELEMETRY.md).

### Memory scope grants

JWT role grants may include `memory_scopes: [home]` or `[work]`; this is separate
from `memory_permissions` and profile access. Existing grants default to legacy.
Grant the matching `local-home` or `local-work` profile as needed. A single shared
service key still accesses all configured scopes and is not a per-person boundary.
See MEMORY.md for namespace mapping and the management request header.
