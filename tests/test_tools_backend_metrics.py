import json
from copy import deepcopy
from dataclasses import replace
import httpx
import pytest
import yaml
from test_app import setup, ask, HEADERS
from test_identity import identity_lab, signing_key, post
from test_compaction import PROFILE, history, fake_backend

TOOLS = [{"type": "function", "function": {"name": "search_web", "description": "Search public web",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}]
CALL = {"id": "call_1", "type": "function", "function": {"name": "search_web", "arguments": '{"query":"example"}'}}
HISTORY = [{"role":"user","content":"Search example"},
    {"role":"assistant","content":None,"tool_calls":[CALL],"reasoning_content":"PRIVATE_THINKING"},
    {"role":"tool","tool_call_id":"call_1","content":"Synthetic result."}]


@pytest.mark.parametrize("stream", [False, True])
def test_client_tool_roundtrip(tmp_path, stream):
    def backend(req):
        if req.url.path.endswith("chat/completions"):
            body = json.loads(req.content)
            if body["messages"][-1]["role"] == "user":
                if not stream:
                    return httpx.Response(200,json={"choices":[{"message":{"role":"assistant","content":None,"tool_calls":[CALL]},"finish_reason":"tool_calls"}]})
                events = [{"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,**CALL}]},"finish_reason":None}]},
                    {"choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}]
                return httpx.Response(200,headers={"content-type":"text/event-stream"},text="".join("data: "+json.dumps(e)+"\n\n" for e in events)+"data: [DONE]\n\n")
    client,calls = setup(tmp_path, {"client_tools":True}, handler=backend)
    with client:
        first = ask(client, tools=TOOLS, stream=stream)
        assert first.status_code==200 and 'tool_calls' in first.text
        final = ask(client, tools=TOOLS, messages=HISTORY)
        assert final.status_code==200,final.text
    wire = json.loads(calls[-1].content)
    assert wire["messages"][-1] == HISTORY[-1]
    assert wire["messages"][-2]["tool_calls"] == [CALL]
    assert "PRIVATE_THINKING" not in str([c.content for c in calls])
    assert json.loads(calls[-2].content)["tools"] == wire["tools"]
    assert wire["parallel_tool_calls"] is False


@pytest.mark.parametrize("bad", [HISTORY[1:], HISTORY[:2], [HISTORY[0],HISTORY[-1]],
    HISTORY+[HISTORY[-1]], HISTORY[:2]+[HISTORY[0]],
    [HISTORY[0],{**HISTORY[1],"role":"user"}],
    [HISTORY[0],{**HISTORY[1],"tool_calls":[CALL,CALL]},HISTORY[-1]],
    [HISTORY[0],{**HISTORY[1],"tool_calls":[{**CALL,"function":{"name":"search_web","arguments":"[]"}}]},HISTORY[-1]]])
def test_invalid_tool_histories_fail_before_backend(tmp_path,bad):
    client,calls=setup(tmp_path,{"client_tools":True})
    with client:
        assert ask(client,messages=bad,tools=TOOLS).status_code==400
    assert not calls


@pytest.mark.parametrize("choice", ["auto", "none", "required", {"type":"function","function":{"name":"search_web"}}])
def test_tool_choice_on_opt_in_profile(tmp_path,choice):
    client,calls=setup(tmp_path,{"client_tools":True})
    with client:
        assert ask(client,tools=TOOLS,tool_choice=choice).status_code==200
        assert json.loads(calls[-1].content)["tool_choice"]==choice
        assert ask(client,tools=TOOLS,tool_choice={"type":"function","function":{"name":"unknown"}}).status_code==400
        assert ask(client,tools=TOOLS*2).status_code==400


def test_other_profiles_still_reject_tool_history(tmp_path):
    client,calls=setup(tmp_path)
    with client:
        assert ask(client,messages=HISTORY).status_code==400
    assert not calls


def test_tools_and_metrics_need_separate_jwt_grants(tmp_path,identity_lab):
    path,config,mint=identity_lab
    def metrics(req):
        if req.url.path=="/metrics":
            return httpx.Response(200,text='vllm:kv_cache_usage_perc 0.25\n')
    client,calls=setup(tmp_path,{"client_tools":True},handler=metrics)
    with client:
        token=mint()
        assert post(client,token,tools=TOOLS).status_code==403
        assert client.get('/v1/backend/metrics',headers={'Authorization':'Bearer '+token}).status_code==403
        assert not calls
    config['role_grants']['reader'].update(client_tools=True,backend_metrics=True)
    path.write_text(yaml.safe_dump(config))
    with client:
        assert post(client,mint(),tools=TOOLS).status_code==200
        assert client.get('/v1/backend/metrics',headers={'Authorization':'Bearer '+mint()}).status_code==200


def test_tool_exchange_survives_compaction(tmp_path):
    seen=[]
    source=history()+deepcopy(HISTORY[1:])
    client,calls=setup(tmp_path,{**PROFILE,"client_tools":True},handler=fake_backend(seen))
    with client:
        result=ask(client,messages=source,tools=TOOLS)
        assert result.status_code==200,result.text
        assert result.headers['x-harness-context-status']=='compacted'
    wire=json.loads(calls[-1].content)
    assert wire['messages'][-2]['tool_calls']==[CALL]
    assert wire['messages'][-1]==HISTORY[-1]
    assert wire['messages'][-3]['content'].endswith(history()[-1]['content'])
    assert wire['tools']==json.loads(calls[-2].content)['tools']


def test_old_tool_arguments_survive_summary_chunking(tmp_path):
    seen=[]
    source=deepcopy(HISTORY)+[{'role':'assistant','content':'Acknowledged'}]+history()
    source[1]['tool_calls'][0]['function']['arguments']=json.dumps({'query':'UNIQUE_ARGUMENT '+'~'*6000})
    client,calls=setup(tmp_path,{**PROFILE,'client_tools':True},handler=fake_backend(seen))
    with client:
        result=ask(client,messages=source,tools=TOOLS)
        assert result.status_code==200,result.text
    assert 'UNIQUE_ARGUMENT' in json.dumps(seen)
    assert 'PRIVATE_THINKING' not in json.dumps(seen)


AUTO={'backend_model':'auto','context_window':131072,'temperature':None,'top_p':None,'presence_penalty':None,
    'backend_presets':{'actual-model':{'temperature':0.7,'top_p':0.8,'presence_penalty':1.5,'context_window':16384,
        'backend_options':{'chat_template_kwargs':{'enable_thinking':False}}}}}


def test_backend_switch_is_per_request_and_drops_qwen_recipe(tmp_path):
    current={'id':'actual-model','max_model_len':95000}
    def backend(req):
        if req.url.path=='/v1/models':return httpx.Response(200,json={'data':[dict(current)]})
    client,calls=setup(tmp_path,AUTO,handler=backend)
    with client:
        first=ask(client)
        assert first.status_code==200
        assert first.headers['x-harness-context-window']=='16384'
        assert json.loads(calls[-1].content)['temperature']==0.7
        current.update(id='different-MoE',max_model_len=262144)
        second=ask(client)
        assert second.status_code==200
        wire=json.loads(calls[-1].content)
        assert wire['model']=='different-MoE'
        assert not {'temperature','top_p','presence_penalty','chat_template_kwargs'} & wire.keys()
        assert second.headers['x-harness-context-window']=='131072'
        current['max_model_len']=8192
        third=ask(client)
        assert third.status_code==200
        assert third.headers['x-harness-context-window']=='8192'
        assert client.get('/health/ready',headers=HEADERS).status_code==200
        assert client.get('/v1/models',headers=HEADERS).json()['data'][0]['id']=='local'


@pytest.mark.parametrize('models',[[],[{'id':'a'},{'id':'b'}],[{'id':'a'}],[{'id':'a','max_model_len':True}],
    [{'id':'a','max_model_len':1024}], [{'id':'a','max_model_len':10000},{'id':'a','max_model_len':10000}]])
def test_auto_model_failures_are_clear_and_do_not_generate(tmp_path,models):
    def backend(req):return httpx.Response(200,json={'data':models})
    client,calls=setup(tmp_path,AUTO,handler=backend)
    with client:
        assert ask(client).status_code==503
        assert client.get('/health/ready',headers=HEADERS).status_code==503
    assert all(c.url.path=='/v1/models' for c in calls)


@pytest.mark.parametrize('stream_options',[None,{}, {'include_usage':True},{'include_usage':False}])
def test_usage_and_vllm_timing_survive_stream(tmp_path,stream_options,caplog):
    usage={'prompt_tokens':12,'completion_tokens':8,'total_tokens':20,'prompt_tokens_details':{'cached_tokens':4}}
    def backend(req):
        if req.url.path.endswith('chat/completions'):
            events=[{'choices':[{'delta':{'content':'hi'},'finish_reason':'stop'}]},
                {'choices':[],'usage':usage,'metrics':{'tokens_per_second':99}}]
            return httpx.Response(200,headers={'content-type':'text/event-stream'},text=''.join('data: '+json.dumps(e)+'\n\n' for e in events)+'data: [DONE]\n\n')
    client,calls=setup(tmp_path,handler=backend)
    with client,caplog.at_level('INFO',logger='uvicorn.error'):
        kwargs={} if stream_options is None else {'stream_options':stream_options}
        response=ask(client,stream=True,**kwargs)
        assert response.status_code==200
        assert 'cached_tokens' in response.text and 'tokens_per_second' in response.text
        assert 'generation_usage' in caplog.text
        assert json.loads(calls[-1].content)['stream_options']==(stream_options if stream_options is not None else {'include_usage':True})


def test_metrics_auth_filter_and_failure(tmp_path):
    state={'fail':False}
    def backend(req):
        assert req.url.path=='/metrics'
        if state['fail']:return httpx.Response(500,text='PRIVATE_ERROR')
        return httpx.Response(200,text='# HELP vllm:kv_cache_usage_perc Cache\n# TYPE vllm:kv_cache_usage_perc gauge\nvllm:kv_cache_usage_perc{model_name="x"} 0.25\npython_info 1\n')
    client,calls=setup(tmp_path,handler=backend)
    with client:
        assert client.get('/v1/backend/metrics').status_code==401
        assert not calls
        response=client.get('/v1/backend/metrics',headers=HEADERS)
        assert response.status_code==200 and '0.25' in response.text
        assert 'python_info' not in response.text
        assert response.headers['x-harness-metrics-scope']=='backend-wide'
        state['fail']=True
        response=client.get('/v1/backend/metrics',headers=HEADERS)
        assert response.status_code==503 and 'PRIVATE_ERROR' not in response.text


def test_small_auto_context_fails_before_compaction(tmp_path):
    client,calls=setup(tmp_path,{**AUTO,'compaction':{'enabled':True}},handler=lambda req:httpx.Response(200,json={'data':[{'id':'small','max_model_len':2000}]}))
    with client:
        assert ask(client).status_code==503
    assert len(calls)==1


def test_pinned_model_uses_exact_id_recipe(tmp_path):
    client,calls=setup(tmp_path,{**AUTO,'backend_model':'actual-model'})
    with client:
        response=ask(client)
        assert response.status_code==200
        assert json.loads(calls[-1].content)['temperature']==0.7
        assert response.headers['x-harness-context-window']=='16384'
    assert all(c.url.path!='/v1/models' for c in calls)


def test_compaction_accounting_preserves_upstream_usage():
    from telemetry import attach_accounting
    usage={'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}
    result={'usage':dict(usage)}
    attach_accounting(result,{'summary_calls':2,'summary_prompt_tokens':300,'summary_completion_tokens':30})
    assert result['usage']==usage
    assert result['harness_usage']['total_tokens_including_compaction']==450


def test_nonstream_usage_and_details_pass_through(tmp_path):
    usage={'prompt_tokens':12,'completion_tokens':8,'total_tokens':20,'completion_tokens_details':{'reasoning_tokens':3}}
    def backend(req):
        if req.url.path.endswith('chat/completions'):
            return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':'Hi'},'finish_reason':'stop'}],
                'usage':usage,'metrics':{'time_to_first_token_ms':80}})
    client,calls=setup(tmp_path,handler=backend)
    with client:
        response=ask(client).json()
        assert response['usage']==usage
        assert response['metrics']['time_to_first_token_ms']==80


from test_memory import memory_lab, save


def test_tool_followup_recall_queries_user_and_preserves_result(tmp_path,memory_lab):
    client,calls=setup(tmp_path,{'client_tools':True,'memory_recall':{'enabled':True}})
    source=deepcopy(HISTORY)
    source[0]['content']='What is my telescope code?'
    with client:
        assert save(client,text='My telescope code is SYNTHETIC-CODE',category='fact').status_code==201
        response=ask(client,messages=source,tools=TOOLS)
        assert response.status_code==200,response.text
        assert response.headers['x-harness-memory-count']=='1'
    wire=json.loads(calls[-1].content)
    assert 'SYNTHETIC-CODE' in wire['messages'][1]['content']
    assert wire['messages'][-1]==source[-1]
