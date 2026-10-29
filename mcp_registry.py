"""Registry of harness-executed MCP servers and per-request selection.

Each server is a reviewed adapter in code: its tool schemas, argument validation,
read-only boundary and model rules live with the adapter, never in a request or
model output. Profiles only choose which registered servers they allow
(`mcp_servers`) and which run when a client makes no choice (`mcp_default`).
A client may narrow that set with the X-Harness-MCP header; it can never add a
server the profile does not allow, and identity grants are rechecked per tool.
"""
from dataclasses import dataclass
import hashlib

from fastapi import HTTPException

HEADER = "x-harness-mcp"


@dataclass(frozen=True)
class MCPServer:
    id: str
    label: str
    description: str
    collection: str
    schemas: list
    rules: str
    factory: object  # callable returning a per-request store with async execute()

    @property
    def tools(self):
        return [t["function"]["name"] for t in self.schemas]


def _vault():
    from vault_mcp import VaultStore, SCHEMAS, COLLECTION, RULES
    return MCPServer("vault", "Local_AI_Vault", "Search, list, read, create and append Markdown notes in the local-model Obsidian vault. No overwrite or delete.",
                     COLLECTION, SCHEMAS, RULES, VaultStore)


def _code():
    from code_mcp import CodeStore, SCHEMAS, COLLECTION, RULES
    return MCPServer("code", "Python sandbox", "Run Python 3.12 scripts in an isolated container on the Hermes VM. No network, fresh state each run.",
                     COLLECTION, SCHEMAS, RULES, CodeStore)


def _web():
    from web_mcp import WebStore, SCHEMAS, COLLECTION, RULES
    return MCPServer("web", "Web search", "Search the web with Brave, get query-relevant page passages and read public pages, fetched from the Hermes VM. Uses paid search credits.",
                     COLLECTION, SCHEMAS, RULES, WebStore)


def _rag():
    from rag_tool import RagStore, SCHEMAS, COLLECTION, RULES
    return MCPServer("rag", "Knowledge base", "Search the curated RAG knowledge base on the RAG gateway host (approved reference documents and notes) and cite its passages.",
                     COLLECTION, SCHEMAS, RULES, RagStore)


_BUILDERS = {"vault": _vault, "code": _code, "web": _web, "rag": _rag}
_CACHE = {}


def server(server_id):
    if server_id not in _CACHE:
        _CACHE[server_id] = _BUILDERS[server_id]()
    return _CACHE[server_id]


def known(server_id):
    return server_id in _BUILDERS


def validate_startup(profile_servers):
    """Fail at startup when an allowed server cannot be configured (for example a missing URL)."""
    for server_id in sorted(set(profile_servers)):
        server(server_id).factory()


def selected_servers(profile, header_value):
    """Return the server IDs to run for this request.

    Absent header: the profile's defaults, so existing clients keep their behavior.
    "none" or an empty value: no servers. Otherwise a comma list of allowed IDs.
    """
    if header_value is None:
        return tuple(profile.mcp_default)
    value = header_value.strip()
    if len(value) > 256:
        raise HTTPException(400, "X-Harness-MCP is too long")
    if value in {"", "none"}:
        return ()
    chosen = [part.strip() for part in value.split(",") if part.strip()]
    if len(set(chosen)) != len(chosen):
        raise HTTPException(400, "X-Harness-MCP lists a server more than once")
    denied = [s for s in chosen if s not in profile.mcp_servers]
    if denied:
        allowed = ", ".join(profile.mcp_servers) or "none"
        raise HTTPException(400, f"MCP server not enabled for this profile. Allowed: {allowed}")
    return tuple(s for s in profile.mcp_servers if s in chosen)


def request_prompt(prompt, fingerprint, servers):
    """Add the rules of the selected servers only, and fingerprint the selection."""
    if not servers:
        return prompt, fingerprint
    prompt += "".join("\n\n" + server(s).rules for s in servers)
    fingerprint = hashlib.sha256((fingerprint + "\nmcp:" + ",".join(servers)).encode()).hexdigest()
    return prompt, fingerprint


def catalog(profile_name, profile, principal):
    """Servers this caller may use on the profile, with the tools their identity grants."""
    rows = []
    for server_id in profile.mcp_servers:
        s = server(server_id)
        tools = [t for t in s.tools if principal.can_tool(profile_name, t, s.collection)]
        if tools:
            rows.append({"id": s.id, "label": s.label, "description": s.description,
                         "tools": tools, "default": server_id in profile.mcp_default})
    return rows
