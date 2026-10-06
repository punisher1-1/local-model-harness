import json
from copy import deepcopy
import httpx
import pytest
from test_app import setup, ask
from test_tools_backend_metrics import HISTORY, TOOLS, CALL

PROFILE={"client_tools":True,"context_window":2400,"max_output_tokens":200,"context_margin":10,
    "compaction":{"enabled":True,"summarize_tool_results":True,"max_summary_tokens":256,"max_calls":4},
    "backend_options":{"chat_template_kwargs":{"enable_thinking":False}}}


def fixture(seen,finish="stop", fail=False):
    def handle(request):
        p=json.loads(request.content)
        if request.url.path=="/tokenize":
            n=sum(len(json.dumps(m)) for m in p['messages'])//4+len(json.dumps(p.get('tools',[])))//4
            return httpx.Response(200,json={'count':n})
        if p['messages'][0]['content'].startswith('Summarize'):
            if fail:raise httpx.ReadTimeout('private fixture',request=request)
            data=json.loads(p['messages'][1]['content'])
            seen.extend(data['visible_history_segment'])
            assert p['tool_choice']=='none' and 'tools' not in p and p['chat_template_kwargs']['enable_thinking'] is False
            assert data['question_for_relevance_only']=='Which release is current?'
            return httpx.Response(200,json={'choices':[{'finish_reason':finish,'message':{'role':'assistant','content':'Source https://example.test/releases ; stable v1.2.3; synthetic evidence.'}}],'usage':{'prompt_tokens':500,'completion_tokens':40}})
        result={'choices':[{'index':0,'message':{'role':'assistant','content':'Synthetic v1.2.3'},'finish_reason':'stop'}],'usage':{'prompt_tokens':500,'completion_tokens':20,'total_tokens':520}}
        if p['stream']:
            chunks=[{'choices':[{'index':0,'delta':{'content':'Synthetic v1.2.3'},'finish_reason':'stop'}]}, {'choices':[],'usage':result['usage']}]
            return httpx.Response(200,headers={'content-type':'text/event-stream'},text=''.join('data: '+json.dumps(x)+'\n\n' for x in chunks)+'data: [DONE]\n\n')
        return httpx.Response(200,json=result)
    return handle


def source(size=18000):
    h=deepcopy(HISTORY)
    h[0]['content']='Which release is current?'
    h[-1]['content']='https://example.test/releases v1.2.3 '+('x'*size)+' END-OF-EVIDENCE'
    return h


@pytest.mark.parametrize('stream',[False,True])
def test_large_current_tool_result_is_summarized_in_full(tmp_path,stream,caplog):
    seen=[];h=source();original=deepcopy(h)
    client,calls=setup(tmp_path,PROFILE,handler=fixture(seen))
    with client,caplog.at_level('INFO',logger='uvicorn.error'):
        r=ask(client,messages=h,tools=TOOLS,stream=stream)
        assert r.status_code==200,r.text
        assert r.headers['x-harness-context-status']=='compacted'
        assert r.headers['x-harness-summarized-tool-results']=='1'
        assert 'Large tool results were summarized' in r.text
        assert 'END-OF-EVIDENCE' not in caplog.text
    assert h==original
    assert ''.join(m['content'] for m in seen)==h[-1]['content']
    assert len([c for c in calls if c.url.path.endswith('chat/completions')])>=3
    wire=json.loads(calls[-1].content)
    assert wire['messages'][1]['content']==h[0]['content']
    assert wire['messages'][-2]['tool_calls']==[CALL]
    assert wire['messages'][-1]['tool_call_id']==h[-1]['tool_call_id']
    evidence=json.loads(wire['messages'][-1]['content'])
    assert 'Lossy' in evidence['notice'] and 'https://example.test/releases' in evidence['harness_evidence_summary']
    assert json.loads(calls[-2].content)['messages']==wire['messages']
    assert 'summary_prompt_tokens' in r.text


@pytest.mark.parametrize('enabled',[False,True])
def test_small_tool_result_unchanged(tmp_path,enabled):
    seen=[];profile=deepcopy(PROFILE);profile['compaction']['summarize_tool_results']=enabled
    client,calls=setup(tmp_path,profile,handler=fixture(seen))
    h=source(20)
    with client:
        r=ask(client,messages=h,tools=TOOLS)
        assert r.status_code==200 and not seen
        assert json.loads(calls[-1].content)['messages'][-1]==h[-1]


@pytest.mark.parametrize('options,status',[({'finish':'length'},502),({'fail':True},504)])
def test_failed_evidence_never_used_and_capacity_released(tmp_path,options,status):
    seen=[];client,calls=setup(tmp_path,PROFILE,settings={'max_concurrent_requests':1},handler=fixture(seen,**options))
    h=source();original=deepcopy(h)
    with client:
        r=ask(client,messages=h,tools=TOOLS)
        assert r.status_code==status,r.text
        assert not client.app.state.slots.locked()
    assert h==original
    assert all(json.loads(c.content)['messages'][0]['content'].startswith('Summarize') for c in calls if c.url.path.endswith('chat/completions'))


def test_tool_summary_work_is_bounded(tmp_path):
    seen=[];profile=deepcopy(PROFILE);profile['compaction']['max_calls']=1
    client,calls=setup(tmp_path,profile,handler=fixture(seen))
    with client:
        r=ask(client,messages=source(),tools=TOOLS)
        assert r.status_code==400 and 'work limit' in r.text
    assert sum(c.url.path.endswith('chat/completions') for c in calls)==1


def test_huge_user_question_never_summarized(tmp_path):
    seen=[];h=source();h[0]['content']='x'*20000
    client,calls=setup(tmp_path,PROFILE,handler=fixture(seen))
    with client:
        r=ask(client,messages=h,tools=TOOLS)
        assert r.status_code==400 and not seen
    assert all(c.url.path=='/tokenize' for c in calls)


def test_disabled_policy_still_rejects_huge_current_tool(tmp_path):
    seen=[];profile=deepcopy(PROFILE);profile['compaction']['summarize_tool_results']=False
    client,calls=setup(tmp_path,profile,handler=fixture(seen))
    with client:
        r=ask(client,messages=source(),tools=TOOLS)
        assert r.status_code==400 and 'input tokens' in r.text and not seen


def test_multiple_tool_results_keep_call_links(tmp_path):
    seen=[];h=source(9000)
    second={**deepcopy(CALL),'id':'call_2'}
    h[1]['tool_calls'].append(second)
    h.append({'role':'tool','tool_call_id':'call_2','content':'y'*9000})
    client,calls=setup(tmp_path,PROFILE,handler=fixture(seen))
    with client:
        r=ask(client,messages=h,tools=TOOLS)
        assert r.status_code==200,r.text
    wire=json.loads(calls[-1].content)['messages']
    assert [m['tool_call_id'] for m in wire if m['role']=='tool']==['call_1','call_2']
    assert len(wire[-3]['tool_calls'])==2


def test_plain_text_blocks_normalized_without_losing_markdown(tmp_path):
    client,calls=setup(tmp_path)
    with client:
        r=ask(client,messages=[{'role':'user','content':[{'type':'text','text':'# Work lab\n'},{'type':'text','text':'Use RTX A4000.'}]}])
        assert r.status_code==200
    assert json.loads(calls[-1].content)['messages'][-1]['content']=='# Work lab\nUse RTX A4000.'


@pytest.mark.parametrize('part',[{'type':'file','file':{'file_data':'hidden'}},{'type':'image_url','image_url':{'url':'hidden'}}, {'type':'text','text':123}])
def test_binary_or_invalid_blocks_never_silently_dropped(tmp_path,part):
    client,calls=setup(tmp_path)
    with client:
        assert ask(client,messages=[{'role':'user','content':[{'type':'text','text':'Keep'},part]}]).status_code==400
    assert not calls


def test_evidence_chunks_respect_separate_input_cap(tmp_path):
    seen=[];profile=deepcopy(PROFILE)
    profile['context_window']=20000
    profile['compaction'].update(tool_result_chunk_tokens=2048,max_calls=2)
    client,calls=setup(tmp_path,profile,handler=fixture(seen))
    with client:
        r=ask(client,messages=source(90000),tools=TOOLS)
        assert r.status_code==400 and 'work limit' in r.text
    requests=[json.loads(c.content) for c in calls if c.url.path.endswith('chat/completions')]
    assert len(requests)==2
    assert all(sum(len(json.dumps(m)) for m in p['messages'])//4+len(json.dumps([]))//4<=2048 for p in requests)
