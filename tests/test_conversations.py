import conversation_store
from dataclasses import replace
from uuid import uuid4
from test_app import setup, HEADERS


def configured(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_CHAT_DB", str(tmp_path/"history.sqlite3"))
    return setup(tmp_path)[0]


def payload(revision=0):
    return {"profile":"local","title":"Synthetic test","revision":revision,"messages":[{"id":"m1","role":"user","content":"Keep this conversation"}]}


def test_restart_restore_revision_and_delete(tmp_path, monkeypatch):
    cid=str(uuid4());path="/v1/conversations/"+cid
    with configured(tmp_path,monkeypatch) as c:
        assert c.get("/v1/conversations").status_code==401
        assert c.put(path,headers=HEADERS,json=payload()).json()["revision"]==1
        assert c.put(path,headers=HEADERS,json=payload()).status_code==409
    with configured(tmp_path,monkeypatch) as c:
        assert c.get(path,headers=HEADERS).json()["messages"][0]["content"]=="Keep this conversation"
        assert c.get("/v1/conversations",headers=HEADERS).json()["data"][0]["id"]==cid
        assert c.put(path,headers=HEADERS,json=payload(1)).json()["revision"]==2
        assert c.delete(path+"?revision=1",headers=HEADERS).status_code==409
        assert c.delete(path+"?revision=2",headers=HEADERS).status_code==204
        assert c.get(path,headers=HEADERS).status_code==404
        assert c.put(path,headers=HEADERS,json=payload(2)).status_code==409


def test_identity_and_profile_isolation(tmp_path,monkeypatch):
    with configured(tmp_path,monkeypatch) as c:
        path="/v1/conversations/"+str(uuid4())
        assert c.put(path,headers=HEADERS,json=payload()).status_code==200
        identity=c.app.state.identity;principal=identity.authenticate(HEADERS["Authorization"])
        for replacement in [replace(principal,actor_id="other"),replace(principal,kind="jwt_subject"),replace(principal,profiles=frozenset())]:
            monkeypatch.setattr(identity,"authenticate",lambda _,p=replacement:p)
            assert c.get("/v1/conversations",headers=HEADERS).json()["data"]==[]
            assert c.get(path,headers=HEADERS).status_code==404
            assert c.delete(path+"?revision=1",headers=HEADERS).status_code==404
        assert c.put(path,headers=HEADERS,json=payload()).status_code==403


def test_validation_and_limits(tmp_path,monkeypatch):
    with configured(tmp_path,monkeypatch) as c:
        path="/v1/conversations/"+str(uuid4())
        invalid=payload();invalid["messages"][0]["role"]="system"
        assert c.put(path,headers=HEADERS,json=invalid).status_code==400
        invalid=payload();invalid["messages"][0]["reasoning"]="do not persist"
        assert c.put(path,headers=HEADERS,json=invalid).status_code==400
        assert c.put(path,headers=HEADERS,content=b"x"*(conversation_store.MAX_BYTES+1)).status_code==413
        assert c.put(path,headers=HEADERS,json={**payload(),"profile":"not-authorized"}).status_code==403
        assert c.get("/v1/conversations?offset=-1",headers=HEADERS).status_code==400


def test_history_opt_in(tmp_path,monkeypatch):
    monkeypatch.delenv("HARNESS_CHAT_DB",raising=False)
    with setup(tmp_path)[0] as c:
        assert c.get("/v1/conversations",headers=HEADERS).status_code==503


def test_append_adds_messages_without_resending_the_chat(tmp_path, monkeypatch):
    cid=str(uuid4());path="/v1/conversations/"+cid
    answer={"id":"m2","role":"assistant","content":"Kept","status":"stopped","error":"Stopped."}
    with configured(tmp_path,monkeypatch) as c:
        assert c.patch(path,headers=HEADERS,json={"revision":1,"messages":[answer]}).status_code==404
        assert c.put(path,headers=HEADERS,json=payload()).json()["revision"]==1
        assert c.patch(path,headers=HEADERS,json={"revision":2,"messages":[answer]}).status_code==409
        assert c.patch(path,headers=HEADERS,json={"revision":0,"messages":[answer]}).status_code==400
        assert c.patch(path,headers=HEADERS,json={"revision":1,"messages":[{"id":"x","role":"system","content":"no"}]}).status_code==400
        r=c.patch(path,headers=HEADERS,json={"revision":1,"messages":[answer],"skill":"notes","mcp_servers":["vault"]})
        assert r.status_code==200 and r.json()=={"id":cid,"revision":2}
        saved=c.get(path,headers=HEADERS).json()
        assert [m["id"] for m in saved["messages"]]==["m1","m2"] and saved["messages"][0]["content"]=="Keep this conversation"
        assert saved["messages"][1]["status"]=="stopped" and saved["title"]=="Synthetic test"
        assert (saved["skill"],saved["mcp_servers"],saved["revision"])==("notes",["vault"],2)
        # No new messages: only the options change (moving a chat between projects).
        assert c.patch(path,headers=HEADERS,json={"revision":2,"messages":[]}).json()["revision"]==3
        assert len(c.get(path,headers=HEADERS).json()["messages"])==2


def test_append_keeps_the_storage_limits_and_ownership(tmp_path, monkeypatch):
    path="/v1/conversations/"+str(uuid4())
    with configured(tmp_path,monkeypatch) as c:
        assert c.put(path,headers=HEADERS,json=payload()).status_code==200
        monkeypatch.setattr(conversation_store,"MAX_MESSAGES",2)
        two=[{"id":"a","role":"user","content":"x"},{"id":"b","role":"assistant","content":"y"}]
        assert c.patch(path,headers=HEADERS,json={"revision":1,"messages":two}).status_code==400
        monkeypatch.setattr(conversation_store,"MAX_BYTES",200)
        assert c.patch(path,headers=HEADERS,json={"revision":1,"messages":[{"id":"a","role":"user","content":"x"*300}]}).status_code==413
        assert c.get(path,headers=HEADERS).json()["revision"]==1
        identity=c.app.state.identity;principal=identity.authenticate(HEADERS["Authorization"])
        monkeypatch.setattr(identity,"authenticate",lambda _,p=replace(principal,actor_id="other"):p)
        assert c.patch(path,headers=HEADERS,json={"revision":1,"messages":[]}).status_code==404
