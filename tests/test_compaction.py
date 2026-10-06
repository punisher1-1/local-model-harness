import json

import httpx
import pytest

from test_app import setup, ask
from test_research import research_setup

PROFILE = {"context_window": 1600, "max_output_tokens": 150, "context_margin": 10,
    "compaction": {"enabled": True, "max_summary_tokens": 128, "max_calls": 8},
    "backend_options": {"chat_template_kwargs": {"enable_thinking": True, "reasoning_effort": "medium"}}}


def history():
    return [
        {"role":"user","content":"Home lab GPU is HOME-RTX; keep home separate. " + "~"*2500},
        {"role":"assistant","content":"Home acknowledged. " + "~"*2500, "reasoning_content":"PRIVATE_REASONING_DO_NOT_FORWARD"},
        {"role":"user","content":"Work lab GPU is WORK-A4000; same hostname, different environment. " + "~"*2500},
        {"role":"assistant","content":"Work acknowledged. " + "~"*2500},
        {"role":"user","content":"Latest request: compare the two environments without mixing them."}]


def fake_backend(seen, summary_finish="stop", summary_text=None, fail=False):
    def handler(request):
        payload=json.loads(request.content)
        if request.url.path=="/tokenize":
            count=sum(len(m["content"]) for m in payload["messages"])//4 + len(json.dumps(payload.get("tools",[])))//4
            return httpx.Response(200,json={"count":count})
        if request.url.path.endswith("chat/completions"):
            if payload["messages"][0]["content"].startswith("Summarize the supplied visible conversation"):
                if fail: raise httpx.ReadTimeout("private error",request=request)
                assert payload["tool_choice"]=="none" and "tools" not in payload
                assert payload["chat_template_kwargs"]["enable_thinking"] is False
                data=json.loads(payload["messages"][1]["content"])
                seen.extend(data["visible_history_segment"])
                pieces=([data["previous_summary"]] if data["previous_summary"] else [])
                pieces += [m["content"].split("~")[0] for m in data["visible_history_segment"]]
                text=summary_text if summary_text is not None else " | ".join(pieces).strip()
                return httpx.Response(200,json={"choices":[{"message":{"role":"assistant","content":text},"finish_reason":summary_finish}],"usage":{"completion_tokens":50}})
            if payload["stream"]:
                events=[{"id":"chatcmpl-test","object":"chat.completion.chunk","created":1,"model":"actual-model","choices":[{"index":0,"delta":{"content":"Answer"},"finish_reason":None}]},
                        {"id":"chatcmpl-test","object":"chat.completion.chunk","created":1,"model":"actual-model","choices":[{"index":0,"delta":{"content":"."},"finish_reason":"stop"}]}]
                return httpx.Response(200,text="".join("data: "+json.dumps(e)+"\n\n" for e in events)+"data: [DONE]\n\n",headers={"content-type":"text/event-stream"})
            return httpx.Response(200,json={"choices":[{"message":{"role":"assistant","content":"Answer."},"finish_reason":"stop"}],"usage":{"completion_tokens":10}})
    return handler


@pytest.mark.parametrize("stream",[False,True])
def test_compaction_preserves_environments_and_latest_turn(tmp_path,caplog,stream):
    seen=[]
    client,calls=setup(tmp_path,PROFILE,handler=fake_backend(seen))
    source=history()
    with client,caplog.at_level("INFO",logger="uvicorn.error"):
        r=ask(client,messages=source,stream=stream)
        assert r.status_code==200,r.text
        assert r.headers["x-harness-context-status"]=="compacted"
        assert "Context compacted" in r.text
        assert not client.app.state.slots.locked()
    final=json.loads(calls[-1].content)
    assert "HOME-RTX" in json.dumps(final["messages"])
    assert "WORK-A4000" in json.dumps(final["messages"])
    assert final["messages"][-1]["content"].endswith(source[-1]["content"])
    assert "HOME-RTX" not in final["messages"][0]["content"]
    assert all("PRIVATE_REASONING" not in c.content.decode() for c in calls)
    assert "PRIVATE_REASONING" not in caplog.text
    assert all("reasoning_content" not in m for m in seen)
    for i,c in enumerate(calls):
        if c.url.path.endswith("chat/completions"):
            assert calls[i-1].url.path=="/tokenize"
            assert json.loads(calls[i-1].content)["messages"]==json.loads(c.content)["messages"]
    if stream:
        assert r.text.count("Context compacted")==1
        assert r.text.index("Context compacted") < r.text.index('"finish_reason": "stop"')
        assert r.text.count("[DONE]")==1
        events=[json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ") and line[6:]!="[DONE]"]
        assert {event["id"] for event in events} == {"chatcmpl-test"}
        visible="".join(ch.get("delta",{}).get("content","") for event in events for ch in event.get("choices",[]))
        assert visible.startswith("Answer.\n\n---\n*Context compacted")


def test_oversized_old_message_split_without_silent_drops(tmp_path):
    seen=[]
    client,_=setup(tmp_path,PROFILE,handler=fake_backend(seen))
    old="Home GPU HOME-RTX. "+"~"*13000
    with client:
        r=ask(client,messages=[{"role":"user","content":old},{"role":"assistant","content":"Acknowledged."},{"role":"user","content":"Which GPU?"}])
        assert r.status_code==200,r.text
    assert "".join(m["content"] for m in seen if m["role"]=="user")==old


def test_latest_request_cannot_be_summarized(tmp_path):
    seen=[]
    client,calls=setup(tmp_path,PROFILE,handler=fake_backend(seen))
    with client:
        r=ask(client,messages=[{"role":"user","content":"x"*10000}])
        assert r.status_code==400 and "latest turn" in r.text
    assert not seen
    assert not any(c.url.path.endswith("chat/completions") for c in calls)


@pytest.mark.parametrize("options,status",[({"summary_finish":"length"},502),({"summary_text":""},502),({"summary_text":"x"*9000},502),({"fail":True},504)])
def test_failed_summary_never_replaces_history_or_leaks_capacity(tmp_path,options,status):
    seen=[]
    client,calls=setup(tmp_path,PROFILE,settings={"max_concurrent_requests":1},handler=fake_backend(seen,**options))
    with client:
        for _ in range(2):
            r=ask(client,messages=history())
            assert r.status_code==status,r.text
            assert "private error" not in r.text
            assert not client.app.state.slots.locked()
    for c in calls:
        if c.url.path.endswith("chat/completions"):
            assert json.loads(c.content)["messages"][0]["content"].startswith("Summarize")


def test_compaction_call_limit_is_enforced(tmp_path):
    seen=[]
    profile={**PROFILE,"compaction":{**PROFILE["compaction"],"max_calls":1}}
    client,calls=setup(tmp_path,profile,handler=fake_backend(seen))
    with client:
        r=ask(client,messages=history())
        assert r.status_code==400 and "work limit" in r.text
    assert sum(c.url.path.endswith("chat/completions") for c in calls)==1


@pytest.mark.parametrize("stream",[False,True])
def test_research_compacts_history_before_its_tool_loop(tmp_path,stream):
    seen=[]
    profile={**PROFILE,"research":{"notes_directory":"notes","max_round_output_tokens":128}}
    client,calls=research_setup(tmp_path,fake_backend(seen),**profile)
    with client:
        r=ask(client,messages=history(),stream=stream)
        assert r.status_code==200,r.text
        assert "Context compacted" in r.text
        assert "Demo research activity" in r.text
    final=json.loads(calls[-1].content)
    assert {t["function"]["name"] for t in final["tools"]}=={"search_notes","read_note"}


def test_short_chat_skips_summarization(tmp_path):
    seen=[]
    client,calls=setup(tmp_path,PROFILE,handler=fake_backend(seen))
    with client:
        r=ask(client)
        assert r.status_code==200 and r.headers["x-harness-context-status"]=="not_needed"
    assert not seen
    assert sum(c.url.path.endswith("chat/completions") for c in calls)==1


@pytest.mark.parametrize("field,value",[("reasoning_content","discard this reasoning"),("reasoning_content",None),("reasoning","discard alternate reasoning")])
def test_boltai_followup_fields_accepted_but_never_forwarded(tmp_path,field,value):
    client,calls=setup(tmp_path)
    with client:
        r=ask(client,messages=[{"role":"user","content":"First"},{"role":"assistant","content":"Visible answer",field:value},{"role":"user","content":"Follow up"}])
        assert r.status_code==200
    for c in calls:
        assert all(field not in m for m in json.loads(c.content)["messages"])
        assert "discard" not in c.content.decode()


def test_other_fields_and_invalid_reasoning_types_still_rejected(tmp_path):
    client,calls=setup(tmp_path)
    with client:
        for extra in ({"reasoning_content":{"text":"no"}},{"unknown":"no"},{"tool_calls":[{}]}):
            r=ask(client,messages=[{"role":"user","content":"First"},{"role":"assistant","content":"Visible",**extra},{"role":"user","content":"Next"}])
            assert r.status_code==400
    assert not calls


def test_four_recent_turns_and_latest_followup_remain_verbatim(tmp_path):
    from compaction import CompactionPolicy
    assert CompactionPolicy(max_summary_tokens=4096,max_summary_bytes=32768).max_summary_tokens==4096
    seen=[]
    source=[{"role":"user","content":"Old background " + "~"*14000},{"role":"assistant","content":"Old answer completed."}]
    for n in range(3):
        source += [{"role":"user","content":f"Recent question {n}"},{"role":"assistant","content":f"Completed answer {n}"}]
    source += [{"role":"user","content":"New request: continue with deployment; do not repeat the completed comparison."}]
    client,calls=setup(tmp_path,{**PROFILE,"compaction":{**PROFILE["compaction"],"target_recent_turns":4}},handler=fake_backend(seen))
    with client:
        r=ask(client,messages=source)
        assert r.status_code==200,r.text
    final=json.loads(calls[-1].content)["messages"]
    assert final[-1]==source[-1]
    assert final[-6:]==source[-6:]
    assert final[-7]["content"].endswith(source[-7]["content"])
    assert "do not replay" in final[0]["content"]
