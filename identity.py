"""Opt-in JWT verification and explicit, immutable authorization context.

The lab service key represents one service, not a verified person. JWT mode trusts
only configured local public keys; it never follows token-supplied key URLs.
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
    tools: list[Literal["search_notes", "read_note"]] = Field(default_factory=list)
    collections: list[Literal["demo_notes"]] = Field(default_factory=list)
    client_tools: bool = False
    backend_metrics: bool = False
    memory_scopes: list[str] = Field(default_factory=lambda: ["legacy"])
    memory_permissions: list[Literal["memory.read", "memory.write", "memory.delete"]] = Field(default_factory=list)


class IdentityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["service_key", "jwt"] = "service_key"
    issuer: str | None = None
    audience: str | None = None
    jwks_file: str | None = None
    required_claims: dict[str, str] = Field(default_factory=dict)
    role_grants: dict[str, Grant] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_mode(self):
        if self.mode == "service_key":
            if self.issuer or self.audience or self.jwks_file or self.required_claims or self.role_grants:
                raise ValueError("JWT configuration cannot be used in service_key mode")
        else:
            if not self.issuer or not self.audience or not self.jwks_file:
                raise ValueError("JWT mode requires issuer, audience, and jwks_file")
            url = urlsplit(self.issuer)
            if url.scheme != "https" or not url.hostname or url.username or url.query or url.fragment:
                raise ValueError("JWT issuer must be an exact HTTPS issuer URL")
            if any(k in {"iss", "aud", "sub", "exp", "iat", "nbf", "roles"} for k in self.required_claims):
                raise ValueError("required_claims cannot override standard claims or roles")
        return self


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
        if self.config.mode == "service_key":
            if len(service_key) < 24 or service_key == "replace-with-a-long-random-key":
                raise RuntimeError("Set HARNESS_API_KEY to a random secret of at least 24 characters")
            return
        for grant in self.config.role_grants.values():
            if set(grant.profiles) - self.profile_names:
                raise ValueError("Identity grants reference an unknown profile")
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
                return Principal("service_key", "lab-service", self.profile_names, DEMO_TOOLS, frozenset({DEMO_COLLECTION}), client_tools=True, backend_metrics=True)
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
            roles = claims.get("roles", [])
            if not isinstance(roles, list) or len(roles) > 100 or any(not isinstance(r, str) or len(r) > 128 for r in roles):
                raise ValueError("Invalid roles")
            profiles, tools, collections, memory_permissions = set(), set(), set(), set()
            memory_scopes = set()
            client_tools = backend_metrics = False
            for role in roles:
                grant = self.config.role_grants.get(role)
                if grant:
                    client_tools |= grant.client_tools
                    backend_metrics |= grant.backend_metrics
                    profiles.update(grant.profiles)
                    tools.update(grant.tools)
                    collections.update(grant.collections)
                    memory_permissions.update(grant.memory_permissions)
                    memory_scopes.update(grant.memory_scopes)
            actor = hashlib.sha256((claims["iss"] + "\0" + claims["sub"]).encode()).hexdigest()
            return Principal("jwt_subject", actor, frozenset(profiles), frozenset(tools), frozenset(collections), claims["exp"], frozenset(memory_permissions), client_tools, backend_metrics, frozenset(memory_scopes))
        except (ValueError, TypeError, KeyError, jwt.PyJWTError):
            # Do not expose token values, claims, or parser exception bodies.
            raise HTTPException(401, "Invalid identity credential", headers={"WWW-Authenticate": "Bearer"}) from None

    def audit(self, principal, action, resource, allowed, request_id=None):
        log.info(json.dumps({"event": "authorization", "actor_id": principal.actor_id,
            "identity_kind": principal.kind, "action": action, "resource": resource,
            "allowed": allowed, "identity_policy_sha256": self.policy_sha256,
            "keyset_sha256": self.keyset_sha256, "request_id": request_id}))
