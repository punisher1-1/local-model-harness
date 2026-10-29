"""Private UI transcripts and the projects that group them. Separate from recalled memories and model policy."""
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

# Room for a few attached documents (each up to 1,000,000 characters of text).
MAX_BYTES = 16_000_000


class Run(BaseModel):
    """One python_run behind an answer, as the sandbox returned it (Python runs panel)."""
    model_config = ConfigDict(extra="forbid", strict=True)
    code: str = Field(max_length=20_000)
    stdout: str | None = Field(default=None, max_length=16_000)
    stderr: str | None = Field(default=None, max_length=16_000)
    exit_code: int | None = None
    timed_out: bool | None = None
    output_limit: bool | None = None
    truncated: bool | None = None
    error: str | None = Field(default=None, max_length=200)


class Attachment(BaseModel):
    """A document attached to a user message, as converted text (documents.py). Saved with
    the chat so later turns replay it; the original file is never stored."""
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=1_000_000)
    chars: int = Field(ge=0)
    tokens: int | None = Field(default=None, ge=0)
    digest: bool = False


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=128)
    role: Literal["user", "assistant"]
    content: str = Field(max_length=500_000)
    skill: str = Field(default="", max_length=128)
    status: Literal["complete", "stopped", "failed"] = "complete"
    error: str | None = Field(default=None, max_length=1000)
    finish: str | None = Field(default=None, max_length=64)
    runs: list[Run] | None = Field(default=None, max_length=16)
    attachments: list[Attachment] | None = Field(default=None, max_length=5)


class Conversation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    profile: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=160)
    revision: int = Field(ge=0)
    messages: list[Message] = Field(max_length=4096)
    # Per-chat UI choices. They are display state only; the chat request still
    # carries the selection and the server revalidates it every time.
    skill: str = Field(default="", max_length=128)
    mcp_servers: list[Annotated[str, Field(min_length=1, max_length=64)]] | None = Field(default=None, max_length=8)
    project_id: UUID | None = None


class Project(BaseModel):
    """A folder of chats with the defaults a new chat in it starts from. Defaults are
    display state like a chat's options: every request is still checked by the server."""
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=80)
    profile: str = Field(min_length=1, max_length=128)
    skill: str = Field(default="", max_length=128)
    mcp_servers: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(default_factory=list, max_length=8)


MAX_PROJECTS = 100
MAX_USER_SKILLS = 50
USER_SKILL_CHARS = 16000


class UserSkill(BaseModel):
    """A Markdown workflow the user writes or imports. It is applied as user-authored
    instructions for one request at a time and never grants tools or permissions."""
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=USER_SKILL_CHARS)
    # Identity groups (role_grants names) whose members may use it, read-only. Empty: private.
    shared_groups: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(default_factory=list, max_length=8)


def skill_summary(content):
    """The first sentence of a skill's first paragraph (headings skipped), for pickers."""
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            first = line.split(". ")[0].rstrip(".")
            return (first if len(first) <= 160 else first[:157] + "…") + "."
    return ""


@contextmanager
def database(path):
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def install_conversations(app, auth):
    path = os.getenv("HARNESS_CHAT_DB")
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with database(path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS conversations (owner TEXT NOT NULL, id TEXT NOT NULL, profile TEXT NOT NULL, title TEXT NOT NULL, revision INTEGER NOT NULL, messages TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(owner,id))")
            if "options" not in {row["name"] for row in db.execute("PRAGMA table_info(conversations)")}:
                db.execute("ALTER TABLE conversations ADD COLUMN options TEXT NOT NULL DEFAULT '{}'")
            db.execute("CREATE TABLE IF NOT EXISTS accounts (actor_id TEXT PRIMARY KEY, issuer TEXT NOT NULL, subject TEXT NOT NULL, name TEXT NOT NULL, email TEXT NOT NULL, groups TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS user_skills (owner TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, content TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(owner,id))")
            if "shared_groups" not in {row["name"] for row in db.execute("PRAGMA table_info(user_skills)")}:
                db.execute("ALTER TABLE user_skills ADD COLUMN shared_groups TEXT NOT NULL DEFAULT '[]'")
            db.execute("CREATE TABLE IF NOT EXISTS projects (owner TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, profile TEXT NOT NULL, skill TEXT NOT NULL, mcp_servers TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(owner,id))")
        os.chmod(path, 0o600)

    def identity(request):
        p = request.state.principal
        p.ensure_current()
        if not path:
            raise HTTPException(503, "Chat history storage is not configured")
        return p, json.dumps([p.kind, p.actor_id])

    def allowed_row(db, owner, cid, principal):
        row = db.execute("SELECT * FROM conversations WHERE owner=? AND id=?", (owner,str(cid))).fetchone()
        if row is None or not principal.can_profile(row["profile"]):
            raise HTTPException(404, "Conversation not found")
        return row

    def response(data):
        return JSONResponse(data, headers={"Cache-Control":"no-store"})

    @app.get("/v1/conversations", dependencies=[Depends(auth)])
    def listing(request: Request, offset: int = 0):
        p, owner = identity(request)
        if offset < 0:
            raise HTTPException(400, "Invalid offset")
        with database(path) as db:
            rows = db.execute("SELECT id,profile,title,revision,updated_at,options FROM conversations WHERE owner=? ORDER BY updated_at DESC,id", (owner,)).fetchall()
        rows = [dict(row) for row in rows if p.can_profile(row["profile"])]
        for row in rows:
            row["project_id"] = json.loads(row.pop("options") or "{}").get("project_id")
        return response({"data":rows[offset:offset+100], "next_offset":offset+100 if len(rows)>offset+100 else None})

    @app.get("/v1/conversations/{cid}", dependencies=[Depends(auth)])
    def read(cid: UUID, request: Request):
        p, owner = identity(request)
        with database(path) as db:
            row = dict(allowed_row(db,owner,cid,p))
        row.pop("owner")
        row["messages"] = json.loads(row["messages"])
        options = json.loads(row.pop("options") or "{}")
        row["skill"] = options.get("skill", "")
        row["mcp_servers"] = options.get("mcp_servers")
        row["project_id"] = options.get("project_id")
        return response(row)

    @app.put("/v1/conversations/{cid}", dependencies=[Depends(auth)])
    async def save(cid: UUID, request: Request):
        p, owner = identity(request)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>MAX_BYTES:
                raise HTTPException(413, "Conversation exceeds the 2 MB storage limit; start a new chat")
        try:
            item = Conversation.model_validate_json(body)
        except ValidationError:
            raise HTTPException(400, "Invalid conversation") from None
        p.require_profile(item.profile)
        if item.profile not in app.state.settings.profiles:
            raise HTTPException(400, "Unknown profile")
        def commit():
            # A short transaction serializes the revision check and write across workers.
            with database(path) as db:
                db.execute("BEGIN IMMEDIATE")
                old = db.execute("SELECT profile,revision FROM conversations WHERE owner=? AND id=?", (owner,str(cid))).fetchone()
                if old and old["profile"] != item.profile:
                    raise HTTPException(409, "A conversation cannot change profiles")
                if item.revision != (old["revision"] if old else 0):
                    raise HTTPException(409, "This chat changed in another tab. Reopen it before continuing")
                if not old and db.execute("SELECT count(*) FROM conversations WHERE owner=?", (owner,)).fetchone()[0]>=1000:
                    raise HTTPException(409, "Chat history limit reached; delete an old conversation first")
                revision = item.revision+1
                # A project deleted in another tab leaves the chat ungrouped rather than failing the save.
                project = str(item.project_id) if item.project_id and db.execute(
                    "SELECT 1 FROM projects WHERE owner=? AND id=?", (owner,str(item.project_id))).fetchone() else None
                options = json.dumps({"skill": item.skill, "mcp_servers": item.mcp_servers, "project_id": project})
                db.execute("INSERT INTO conversations (owner,id,profile,title,revision,messages,updated_at,options) VALUES (?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'),?) ON CONFLICT(owner,id) DO UPDATE SET title=excluded.title, revision=excluded.revision, messages=excluded.messages, updated_at=excluded.updated_at, options=excluded.options", (owner,str(cid),item.profile,item.title,revision,json.dumps([m.model_dump() for m in item.messages]),options))
            return revision
        revision = await run_in_threadpool(commit)
        return response({"id":str(cid),"revision":revision})

    @app.delete("/v1/conversations/{cid}", dependencies=[Depends(auth)])
    def delete(cid: UUID, revision: int, request: Request):
        p, owner = identity(request)
        with database(path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = allowed_row(db,owner,cid,p)
            if row["revision"] != revision:
                raise HTTPException(409, "This chat changed in another tab. Reopen it before deleting")
            db.execute("DELETE FROM conversations WHERE owner=? AND id=?", (owner,str(cid)))
        return Response(status_code=204)

    def project_row(row):
        return {"id": row["id"], "name": row["name"], "profile": row["profile"], "skill": row["skill"],
                "mcp_servers": json.loads(row["mcp_servers"]), "updated_at": row["updated_at"]}

    @app.get("/v1/projects", dependencies=[Depends(auth)])
    def projects(request: Request):
        p, owner = identity(request)
        with database(path) as db:
            rows = db.execute("SELECT * FROM projects WHERE owner=? ORDER BY name COLLATE NOCASE,id", (owner,)).fetchall()
        return response({"data": [project_row(r) for r in rows if p.can_profile(r["profile"])]})

    @app.put("/v1/projects/{pid}", dependencies=[Depends(auth)])
    async def save_project(pid: UUID, request: Request):
        p, owner = identity(request)
        body = await request.body()
        if len(body) > 16384:
            raise HTTPException(413, "Project is too large")
        try:
            item = Project.model_validate_json(body)
        except ValidationError:
            raise HTTPException(400, "Invalid project") from None
        p.require_profile(item.profile)
        if item.profile not in app.state.settings.profiles:
            raise HTTPException(400, "Unknown profile")
        if len(set(item.mcp_servers)) != len(item.mcp_servers):
            raise HTTPException(400, "A tool server is listed more than once")
        def commit():
            with database(path) as db:
                db.execute("BEGIN IMMEDIATE")
                exists = db.execute("SELECT 1 FROM projects WHERE owner=? AND id=?", (owner,str(pid))).fetchone()
                if not exists and db.execute("SELECT count(*) FROM projects WHERE owner=?", (owner,)).fetchone()[0] >= MAX_PROJECTS:
                    raise HTTPException(409, f"Project limit reached ({MAX_PROJECTS}); delete one first")
                db.execute("INSERT INTO projects (owner,id,name,profile,skill,mcp_servers,updated_at) VALUES (?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now')) ON CONFLICT(owner,id) DO UPDATE SET name=excluded.name, profile=excluded.profile, skill=excluded.skill, mcp_servers=excluded.mcp_servers, updated_at=excluded.updated_at",
                           (owner,str(pid),item.name.strip() or item.name,item.profile,item.skill,json.dumps(item.mcp_servers)))
                return project_row(db.execute("SELECT * FROM projects WHERE owner=? AND id=?", (owner,str(pid))).fetchone())
        return response(await run_in_threadpool(commit))

    @app.delete("/v1/projects/{pid}", dependencies=[Depends(auth)])
    def delete_project(pid: UUID, request: Request):
        """Remove the folder only. Its chats stay saved and return to the ungrouped list."""
        p, owner = identity(request)
        with database(path) as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM projects WHERE owner=? AND id=?", (owner,str(pid))).fetchone():
                raise HTTPException(404, "Project not found")
            db.execute("DELETE FROM projects WHERE owner=? AND id=?", (owner,str(pid)))
            db.execute("UPDATE conversations SET options=json_set(options,'$.project_id',NULL) WHERE owner=? AND json_extract(options,'$.project_id')=?", (owner,str(pid)))
        return Response(status_code=204)

    def skill_row(row, content=False):
        data = {"id": row["id"], "name": row["name"], "summary": skill_summary(row["content"]), "updated_at": row["updated_at"]}
        if "shared_by" in row.keys():
            data.update(shared=True, shared_by=row["shared_by"] or "another account")
        else:
            data["shared_groups"] = json.loads(row["shared_groups"])
        if content:
            data["content"] = row["content"]
        return data

    # Other accounts' skills shared with one of this identity's groups, named by their owner.
    # The groups come from the signed-in session, so leaving a group in Pocket ID removes
    # access at the next sign-in. A skill with the same ID as one of your own is hidden.
    SHARED = """SELECT s.*, COALESCE(NULLIF(a.name,''), NULLIF(a.email,'')) AS shared_by FROM user_skills s
        LEFT JOIN accounts a ON json_extract(s.owner,'$[0]')='jwt_subject' AND a.actor_id=json_extract(s.owner,'$[1]')
        WHERE s.owner<>? AND EXISTS (SELECT 1 FROM json_each(s.shared_groups) g WHERE g.value IN (SELECT value FROM json_each(?)))
          AND NOT EXISTS (SELECT 1 FROM user_skills o WHERE o.owner=? AND o.id=s.id)"""

    def shared_rows(db, p, owner, sid=None):
        query = SHARED + (" AND s.id=?" if sid else "") + " ORDER BY s.name COLLATE NOCASE, s.id"
        return db.execute(query, (owner, json.dumps(sorted(p.groups)), owner, *([sid] if sid else []))).fetchall()

    def share_options(request):
        config = getattr(getattr(request.app.state, "identity", None), "config", None)
        return sorted(getattr(config, "role_grants", None) or {})

    @app.get("/v1/skills", dependencies=[Depends(auth)])
    def user_skills(request: Request):
        p, owner = identity(request)
        with database(path) as db:
            rows = db.execute("SELECT * FROM user_skills WHERE owner=? ORDER BY name COLLATE NOCASE,id", (owner,)).fetchall()
            shared = shared_rows(db, p, owner)
        groups = share_options(request) if p.kind == "jwt_subject" else []
        return response({"data": [skill_row(r) for r in rows] + [skill_row(r) for r in shared], "share_groups": groups})

    @app.get("/v1/skills/{sid}", dependencies=[Depends(auth)])
    def read_skill(sid: UUID, request: Request):
        p, owner = identity(request)
        with database(path) as db:
            row = db.execute("SELECT * FROM user_skills WHERE owner=? AND id=?", (owner, str(sid))).fetchone()
            row = row or next(iter(shared_rows(db, p, owner, str(sid))), None)
        if row is None:
            raise HTTPException(404, "Skill not found")
        return response(skill_row(row, content=True))

    @app.put("/v1/skills/{sid}", dependencies=[Depends(auth)])
    async def save_skill(sid: UUID, request: Request):
        p, owner = identity(request)
        body = await request.body()
        if len(body) > USER_SKILL_CHARS * 4 + 1024:
            raise HTTPException(413, f"Skill is too large; keep it under {USER_SKILL_CHARS:,} characters")
        try:
            item = UserSkill.model_validate_json(body)
        except ValidationError:
            raise HTTPException(400, f"Invalid skill: it needs a name (up to 80 characters) and content (up to {USER_SKILL_CHARS:,} characters)") from None
        if not item.name.strip() or not item.content.strip():
            raise HTTPException(400, "A skill needs a name and some content")
        if item.shared_groups:
            unknown = set(item.shared_groups) - set(share_options(request))
            if p.kind != "jwt_subject":
                raise HTTPException(400, "Sign in with your account to share skills")
            if unknown:
                raise HTTPException(400, "Unknown group: " + ", ".join(sorted(unknown)))
        groups = json.dumps(sorted(set(item.shared_groups)))
        def commit():
            with database(path) as db:
                db.execute("BEGIN IMMEDIATE")
                # IDs are unique across accounts, so a shared skill's ID always names one skill.
                if db.execute("SELECT 1 FROM user_skills WHERE id=? AND owner<>?", (str(sid), owner)).fetchone():
                    raise HTTPException(409, "That skill ID belongs to another account; save it as a new skill")
                exists = db.execute("SELECT 1 FROM user_skills WHERE owner=? AND id=?", (owner, str(sid))).fetchone()
                if not exists and db.execute("SELECT count(*) FROM user_skills WHERE owner=?", (owner,)).fetchone()[0] >= MAX_USER_SKILLS:
                    raise HTTPException(409, f"Skill limit reached ({MAX_USER_SKILLS}); delete one first")
                db.execute("INSERT INTO user_skills (owner,id,name,content,shared_groups,updated_at) VALUES (?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now')) ON CONFLICT(owner,id) DO UPDATE SET name=excluded.name, content=excluded.content, shared_groups=excluded.shared_groups, updated_at=excluded.updated_at",
                           (owner, str(sid), item.name.strip(), item.content.strip(), groups))
                return skill_row(db.execute("SELECT * FROM user_skills WHERE owner=? AND id=?", (owner, str(sid))).fetchone(), content=True)
        return response(await run_in_threadpool(commit))

    @app.delete("/v1/skills/{sid}", dependencies=[Depends(auth)])
    def delete_skill(sid: UUID, request: Request):
        """Chats and projects that chose it fall back to Automatic in the UI."""
        p, owner = identity(request)
        with database(path) as db:
            if db.execute("DELETE FROM user_skills WHERE owner=? AND id=?", (owner, str(sid))).rowcount == 0:
                raise HTTPException(404, "Skill not found")
        return Response(status_code=204)

    def load_user_skill(principal, value):
        """The named skill of this identity, or one shared with its groups, for the chat route:
        (name, content, shared_by or None). Raises a 400 the user can act on."""
        try:
            sid = str(UUID(value.strip()))
        except (ValueError, AttributeError):
            raise HTTPException(400, "Invalid X-Harness-User-Skill; expected a skill ID") from None
        if not path:
            raise HTTPException(400, "Your skills need chat history storage, which is not configured")
        principal.ensure_current()
        owner = json.dumps([principal.kind, principal.actor_id])
        with database(path) as db:
            row = db.execute("SELECT name,content FROM user_skills WHERE owner=? AND id=?", (owner, sid)).fetchone()
            if row is not None:
                return row["name"], row["content"], None
            row = next(iter(shared_rows(db, principal, owner, sid)), None)
        if row is None:
            raise HTTPException(400, "That skill no longer exists or is no longer shared with you. Choose another workflow for this chat.")
        return row["name"], row["content"], row["shared_by"] or "another account"

    app.state.load_user_skill = load_user_skill

    async def record_account(principal, issuer, subject, user):
        """Remember who has signed in, so scripts/claim_shared_data.py can name a target account."""
        if not path:
            return
        def write():
            with database(path) as db:
                db.execute("INSERT INTO accounts (actor_id,issuer,subject,name,email,groups,first_seen,last_seen) VALUES (?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'),strftime('%Y-%m-%dT%H:%M:%fZ','now')) "
                           "ON CONFLICT(actor_id) DO UPDATE SET name=excluded.name, email=excluded.email, groups=excluded.groups, last_seen=excluded.last_seen",
                           (principal.actor_id, issuer, subject, user["name"], user["email"], json.dumps(user["groups"])))
        await run_in_threadpool(write)

    app.state.record_account = record_account
