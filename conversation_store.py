"""Private UI transcripts. Separate from recalled memories and model policy."""
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

MAX_BYTES = 2_000_000


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=128)
    role: Literal["user", "assistant"]
    content: str = Field(max_length=500_000)
    skill: str = Field(default="", max_length=128)
    status: Literal["complete", "stopped", "failed"] = "complete"
    error: str | None = Field(default=None, max_length=1000)
    finish: str | None = Field(default=None, max_length=64)


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
            rows = db.execute("SELECT id,profile,title,revision,updated_at FROM conversations WHERE owner=? ORDER BY updated_at DESC,id", (owner,)).fetchall()
        rows = [dict(row) for row in rows if p.can_profile(row["profile"])]
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
                options = json.dumps({"skill": item.skill, "mcp_servers": item.mcp_servers})
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
