# ADR-001: Explicit service-key and verified JWT identity modes

**Status:** Accepted for scaffold; action items 3–4 and the single-mode rule superseded by [ADR-004](ADR-004-oidc-sign-in.md)
**Date:** 2026-09-07
**Deciders:** Project owner; implementation within the agreed identity scaffold

## Context

The personal lab has one operator and a working Open WebUI connection. Work-machine
clones should support backend-owned authorization without depending on UI roles or
client-supplied names. No work tenant, API registration, or user-token flow has been
selected. The existing research catalog is synthetic and shared.

## Decision

Keep the current explicit service-key default. Add an opt-in RS256 JWT verifier using
trusted, locally configured public keys, exact issuer/API audience and optional
provider-specific claims. Map verified roles into immutable profile, tool and demo
collection grants. Filter discovery/tool schemas and recheck permissions at execution.
Never fall back between modes. Document provider integration as unfinished work.

## Options considered

| Option | Complexity | Cost | Scalability | Familiarity |
|---|---|---|---|---|
| Trust UI-provided headers | Low | Low | Simple | Familiar, but not a trustworthy boundary without a verified gateway |
| Static public JWKS + JWT validation | Moderate | No added service | Local verification; operator-managed rotation | Familiar Python/library integration |
| Full provider discovery + delegated token flow | Higher | Provider-dependent | Supports operational rotation and enterprise SSO | Requires tenant/client decisions not yet made |

Plain UI headers are rejected as identity evidence. Full provider integration is the
likely later direction, but would invent deployment assumptions today. Static public
keys let us test the contract and permissions without introducing a login service.

## Trade-off analysis

This establishes real signature and permission enforcement while preserving the lab.
It does not solve key refresh, login, delegation, immediate revocation, document ACLs
or compliance auditing. Those are explicit follow-up components, not hidden defaults.

## Consequences

- A different UI or direct API client gets the same permission decisions.
- Open WebUI's current shared key still identifies a service, not an individual.
- Operators must handle trusted public-key rotation and restart the static verifier.
- Private-data connectors remain out of scope until resource ownership is enforced.

## Action items

1. [x] Implement and test separate identity modes and permission checks.
2. [x] Document configuration, denied cases and lab behavior.
3. [ ] Select the work identity provider and access-token contract.
4. [ ] Implement and verify the UI/gateway token flow and operational key rotation.
5. [ ] Add resource-level authorization before connecting sensitive data.
