# Identity and authorization scaffold

Implemented 2026-09-07. Default lab mode remains a shared service key. The separate
JWT mode implements signature/claim checks and role-based profile/tool permissions;
no work identity provider or Open WebUI user-token integration is configured yet.
This is not a production SSO rollout or a per-document authorization system.

## What is enforced

| Boundary | Behavior |
|---|---|
| Authentication | One explicit mode per deployment: service key or JWT. JWT failure never falls back to the service key. |
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
For rollback, restore a reviewed source version and preserve deployment-only
credentials separately. No enterprise identity provider is configured by default.

## Memory permissions

JWT role grants can include `memory_permissions: [memory.read, memory.write,
memory.delete]`, independently of profiles and research tools. Omitted permissions
grant no memory access. The same verified issuer/subject actor ID owns records across
chats; request-body owner fields and user metadata cannot select another owner.
Token expiry is checked again after waiting for a database connection.

Memory is disabled by default. An operator can explicitly opt into
`allow_shared_service_identity: true` in a separate memory configuration, granting
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
