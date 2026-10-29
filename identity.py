"""Identity modes and explicit, immutable authorization context.

The lab service key represents one service, not a verified person. JWT mode trusts
only configured local public keys; it never follows token-supplied key URLs. OIDC mode
(ADR-004) signs people in through an OpenID provider (see oidc.py) and still accepts
the service key for apps, limited to the grant configured for it.
"""
from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import secrets
import time
from typing import Literal
from urllib.parse import urlsplit

import jwt
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
import yaml

log = logging.getLogger("uvicorn.error")
DEMO_TOOLS = frozenset({"search_notes", "read_note"})
DEMO_COLLECTION = "demo_notes"


class Grant(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    profiles: list[str] = Field(default_factory=list)
    tools: list[Literal["search_notes", "read_note", "vault_search", "vault_read_note", "vault_list_notes", "vault_create_note", "vault_append", "python_run", "web_context", "web_search", "web_read", "rag_search"]] = Field(default_factory=list)
    collections: list[Literal["demo_notes", "local_ai_vault", "code_sandbox", "web", "knowledge_base"]] = Field(default_factory=list)
    client_tools: bool = False
    backend_metrics: bool = False
    memory_scopes: list[str] = Field(default_factory=lambda: ["legacy"])
    memory_permissions: list[Literal["memory.read", "memory.write", "memory.delete"]] = Field(default_factory=list)


OIDC_FIELDS = ("client_id", "redirect_uri", "service_key", "provider_name")
CLAIM_PATH = r"^[A-Za-z0-9_:-]{1,64}(\.[A-Za-z0-9_:-]{1,64}){0,3}$"


class IdentityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["service_key", "jwt", "oidc"] = "service_key"
    issuer: str | None = None
    audience: str | None = None
    jwks_file: str | None = None
    required_claims: dict[str, str] = Field(default_factory=dict)
    role_grants: dict[str, Grant] = Field(default_factory=dict)
    # Where the role or group names sit in a verified token: "roles" (Entra app roles),
    # "groups" (Pocket ID), or a dotted path such as "realm_access.roles" (Keycloak).
    roles_claim: str = Field(default="roles", pattern=CLAIM_PATH)
    # OIDC mode only.
    provider_name: str | None = Field(default=None, max_length=40)
    client_id: str | None = Field(default=None, min_length=1, max_length=256)
    client_secret_env: str = Field(default="HARNESS_OIDC_CLIENT_SECRET", pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    redirect_uri: str | None = None
    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email", "groups"], max_length=16)
    service_key: Grant | None = None
    allow_key_sign_in: bool = True

    @model_validator(mode="after")
    def valid_mode(self):
        oidc_only = [f for f in OIDC_FIELDS if getattr(self, f) is not None]
        if self.mode == "service_key":
            if self.issuer or self.audience or self.jwks_file or self.required_claims or self.role_grants or oidc_only:
                raise ValueError("JWT configuration cannot be used in service_key mode")
        elif self.mode == "oidc":
            if self.audience or self.jwks_file:
                raise ValueError("OIDC mode reads keys from the issuer; set client_id instead of audience/jwks_file")
            if not self.issuer or not self.client_id or not self.redirect_uri:
                raise ValueError("OIDC mode requires issuer, client_id and redirect_uri")
            url = urlsplit(self.issuer)
            if url.scheme != "https" or not url.hostname or url.username or url.query or url.fragment:
                raise ValueError("OIDC issuer must be an exact HTTPS issuer URL")
            cb = urlsplit(self.redirect_uri)
            if cb.scheme not in {"http", "https"} or not cb.hostname or cb.username or cb.query or cb.fragment or cb.path != "/v1/auth/callback":
                raise ValueError("redirect_uri must be the harness URL ending in /v1/auth/callback")
            if "openid" not in self.scopes or any(not s or len(s) > 64 or not s.replace("_", "").replace(":", "").replace(".", "").isalnum() for s in self.scopes):
                raise ValueError("scopes must include openid and contain simple scope names")
            if any(k in {"iss", "aud", "sub", "exp", "iat", "nbf", "nonce", self.roles_claim.split(".")[0]} for k in self.required_claims):
                raise ValueError("required_claims cannot override standard claims or roles")
        else:
            if oidc_only:
                raise ValueError("client_id, redirect_uri, service_key and provider_name apply to oidc mode only")
            if not self.issuer or not self.audience or not self.jwks_file:
                raise ValueError("JWT mode requires issuer, audience, and jwks_file")
            url = urlsplit(self.issuer)
            if url.scheme != "https" or not url.hostname or url.username or url.query or url.fragment:
                raise ValueError("JWT issuer must be an exact HTTPS issuer URL")
            if any(k in {"iss", "aud", "sub", "exp", "iat", "nbf", "roles", self.roles_claim.split(".")[0]} for k in self.required_claims):
                raise ValueError("required_claims cannot override standard claims or roles")
        return self


def claim_at(claims, path):
    value = claims
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


SERVICE_TOOLS = DEMO_TOOLS | frozenset({"vault_search", "vault_read_note", "vault_list_notes", "vault_create_note", "vault_append",
                                        "python_run", "web_context", "web_search", "web_read", "rag_search"})
SERVICE_COLLECTIONS = frozenset({DEMO_COLLECTION, "local_ai_vault", "code_sandbox", "web", "knowledge_base"})


@dataclass(frozen=True)
class Principal:
    kind: str
    actor_id: str
    profiles: frozenset[str]
    tools: frozenset[str]
    collections: frozenset[str]
    expires_at: int | None = None
    memory_permissions: frozenset[str] = frozenset()

    client_tools: bool = False
    backend_metrics: bool = False
    memory_scopes: frozenset[str] = frozenset({"legacy"})
    # Configured groups this identity belongs to (role_grants keys), for skills shared with a group.
    groups: frozenset[str] = frozenset()

    def ensure_current(self):
        if self.expires_at is not None and time.time() >= self.expires_at:
            raise HTTPException(401, "Identity token expired", headers={"WWW-Authenticate": "Bearer"})

    def can_profile(self, name):
        return name in self.profiles

    def can_tool(self, profile, name, collection=DEMO_COLLECTION):
        return self.can_profile(profile) and name in self.tools and collection in self.collections

    def require_profile(self, name):
        self.ensure_current()
        if not self.can_profile(name):
            raise HTTPException(403, "Profile access denied")

    def require_tool(self, profile, name, collection=DEMO_COLLECTION):
        self.ensure_current()
        if not self.can_tool(profile, name, collection):
            raise HTTPException(403, "Tool or collection access denied")


class IdentityProvider:
    def __init__(self, config_path, service_key, profile_names):
        self.profile_names = frozenset(profile_names)
        path = Path(config_path).resolve() if config_path else None
        self.config = IdentityConfig.model_validate(yaml.safe_load(path.read_text()) if path else {})
        self.policy_sha256 = hashlib.sha256(json.dumps({"identity": self.config.model_dump(),
            "profiles": sorted(self.profile_names)}, sort_keys=True).encode()).hexdigest()
        self.keys = {}
        self.keyset_sha256 = None
        self.service_key = service_key
        weak_key = len(service_key) < 24 or service_key == "replace-with-a-long-random-key"
        if self.config.mode == "service_key":
            if weak_key:
                raise RuntimeError("Set HARNESS_API_KEY to a random secret of at least 24 characters")
            return
        for grant in [*self.config.role_grants.values(), *([self.config.service_key] if self.config.service_key else [])]:
            if set(grant.profiles) - self.profile_names:
                raise ValueError("Identity grants reference an unknown profile")
        if self.config.mode == "oidc":
            # People sign in through the provider (oidc.py); the key is for apps, if granted.
            if self.config.service_key is not None and weak_key:
                raise RuntimeError("service_key is granted in identity config: set HARNESS_API_KEY to a random secret of at least 24 characters")
            return
        key_path = Path(self.config.jwks_file)
        if not key_path.is_absolute():
            key_path = path.parent / key_path
        raw = key_path.read_bytes()
        if len(raw) > 131072:
            raise ValueError("JWKS file is too large")
        entries = json.loads(raw).get("keys")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 16:
            raise ValueError("JWKS must contain 1 to 16 public keys")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Invalid JWKS entry")
            kid = entry.get("kid")
            if not isinstance(kid, str) or not 1 <= len(kid) <= 128 or kid in self.keys:
                raise ValueError("Public keys require unique bounded kid values")
            if entry.get("kty") != "RSA" or entry.get("alg", "RS256") != "RS256" or entry.get("use", "sig") != "sig":
                raise ValueError("Only RSA RS256 signature keys are supported")
            if any(k in entry for k in ("d", "p", "q", "dp", "dq", "qi", "oth")):
                raise ValueError("Private keys must never be supplied to the harness")
            if entry.get("key_ops", ["verify"]) != ["verify"]:
                raise ValueError("Public keys must be for verification only")
            key = jwt.PyJWK.from_dict(entry, algorithm="RS256").key
            if key.key_size < 2048:
                raise ValueError("RSA keys must be at least 2048 bits")
            self.keys[kid] = key
        self.keyset_sha256 = hashlib.sha256(raw).hexdigest()

    def authenticate(self, authorization):
        try:
            if not isinstance(authorization, str) or len(authorization) > 16384:
                raise ValueError("Invalid authorization")
            scheme, token = authorization.split(" ", 1)
            if scheme.lower() != "bearer" or not token or token != token.strip():
                raise ValueError("Invalid authorization")
            if self.config.mode == "service_key":
                if not secrets.compare_digest(token.encode(), self.service_key.encode()):
                    raise ValueError("Invalid service key")
                return Principal("service_key", "lab-service", self.profile_names, SERVICE_TOOLS, SERVICE_COLLECTIONS, client_tools=True, backend_metrics=True)
            if self.config.mode == "oidc":
                # Bearer credentials here are only the app service key, and only if granted.
                grant = self.config.service_key
                if grant is None or not secrets.compare_digest(token.encode(), self.service_key.encode()):
                    raise ValueError("Invalid service key")
                return Principal("service_key", "lab-service", frozenset(grant.profiles), frozenset(grant.tools), frozenset(grant.collections),
                                 None, frozenset(grant.memory_permissions), grant.client_tools, grant.backend_metrics, frozenset(grant.memory_scopes))
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if header.get("alg") != "RS256" or not isinstance(kid, str) or kid not in self.keys or header.get("crit"):
                raise ValueError("Unsupported token header")
            if any(k in header for k in ("jku", "jwk", "x5u")):
                raise ValueError("Token-supplied keys are not trusted")
            claims = jwt.decode(token, self.keys[kid], algorithms=["RS256"],
                issuer=self.config.issuer, audience=self.config.audience,
                options={"require": ["exp", "iat", "iss", "aud", "sub"], "strict_aud": True})
            if not isinstance(claims["sub"], str) or not 1 <= len(claims["sub"]) <= 256:
                raise ValueError("Invalid subject")
            for k in ("exp", "iat", "nbf"):
                if k in claims and type(claims[k]) is not int:
                    raise ValueError("Numeric dates must be integers")
            if claims["exp"] <= claims["iat"]:
                raise ValueError("Invalid token lifetime")
            if any(claims.get(k) != v for k, v in self.config.required_claims.items()):
                raise ValueError("Required claim mismatch")
            return self.principal_from_claims(claims, claims["exp"])
        except (ValueError, TypeError, KeyError, jwt.PyJWTError):
            # Do not expose token values, claims, or parser exception bodies.
            raise HTTPException(401, "Invalid identity credential", headers={"WWW-Authenticate": "Bearer"}) from None

    def roles_of(self, claims):
        roles = claim_at(claims, self.config.roles_claim)
        roles = [] if roles is None else roles
        if not isinstance(roles, list) or len(roles) > 100 or any(not isinstance(r, str) or len(r) > 128 for r in roles):
            raise ValueError("Invalid roles")
        return roles

    def principal_from_claims(self, claims, expires_at):
        """Union of the grants of every verified role; unknown roles grant nothing.
        The actor is a hash of issuer and subject, so it is stable across sign-ins and
        the same for a bearer JWT and an OIDC sign-in from one issuer."""
        if not isinstance(claims.get("sub"), str) or not 1 <= len(claims["sub"]) <= 256:
            raise ValueError("Invalid subject")
        profiles, tools, collections, memory_permissions = set(), set(), set(), set()
        memory_scopes = set()
        client_tools = backend_metrics = False
        groups = set()
        for role in self.roles_of(claims):
            grant = self.config.role_grants.get(role)
            if grant:
                groups.add(role)
                client_tools |= grant.client_tools
                backend_metrics |= grant.backend_metrics
                profiles.update(grant.profiles)
                tools.update(grant.tools)
                collections.update(grant.collections)
                memory_permissions.update(grant.memory_permissions)
                memory_scopes.update(grant.memory_scopes)
        actor = hashlib.sha256((claims["iss"] + "\0" + claims["sub"]).encode()).hexdigest()
        return Principal("jwt_subject", actor, frozenset(profiles), frozenset(tools), frozenset(collections), expires_at,
                         frozenset(memory_permissions), client_tools, backend_metrics, frozenset(memory_scopes), frozenset(groups))

    def audit(self, principal, action, resource, allowed, request_id=None):
        log.info(json.dumps({"event": "authorization", "actor_id": principal.actor_id,
            "identity_kind": principal.kind, "action": action, "resource": resource,
            "allowed": allowed, "identity_policy_sha256": self.policy_sha256,
            "keyset_sha256": self.keyset_sha256, "request_id": request_id}))
