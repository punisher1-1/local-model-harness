import asyncio
import json
from dataclasses import replace
import pytest
from test_app import setup, ask, HEADERS
from test_research import completion, tool
from vault_mcp import VaultStore, safe_path


def test_read_only_validation_and_search_receipts(monkeypatch):
    monkeypatch.setenv('HARNESS_VAULT_MCP_URL','http://vault/mcp')
    store=VaultStore();calls=[]
    async def fake(name,args):
        calls.append(name)
        return {'results':[{'path':'Lab/note.md','snippet':'test'},{'path':'../secret.md'},{'path':'.obsidian/config.md'}]} if name=='vault_search' else {'content':'x'*50000}
    monkeypatch.setattr(store,'call',fake)
    async def run():
        assert (await store.execute('vault_delete_note',{'path':'Lab/note.md'}))['error']=='tool_not_allowed'
        assert (await store.execute('vault_read_note',{'path':'Lab/note.md'}))['error']=='search_for_note_first'
        assert not calls
        assert len((await store.execute('vault_search',{'query':'Lab'}))['results'])==1
        result=await store.execute('vault_read_note',{'path':'Lab/note.md'})
        assert result['truncated'] and len(result['content'])==48000
        assert (await store.execute('vault_search',{'query':'x','limit':100}))['error']=='invalid_arguments'
    asyncio.run(run())


@pytest.mark.parametrize('stream',[False,True])
def test_vault_loop_registers_only_reviewed_tools(tmp_path,monkeypatch,stream):
    monkeypatch.setenv('HARNESS_VAULT_MCP_URL','http://vault/mcp')
    calls=[];rounds=[]
    async def fake(self,name,args):
        calls.append(name)
        return {'results':[{'path':'Lab/note.md','snippet':'evidence'}]} if name=='vault_search' else {'content':'Verified synthetic evidence.'}
    monkeypatch.setattr(VaultStore,'call',fake)
    def backend(request):
        if request.url.path!='/v1/chat/completions':return None
        body=json.loads(request.content);rounds.append(body)
        assert {t['function']['name'] for t in body.get('tools',[])}=={'vault_search','vault_read_note','vault_list_notes','vault_create_note','vault_append'}
        n=len(rounds)
        if n==1:return completion({'role':'assistant','tool_calls':[tool('vault_search',{'query':'evidence'})]},'tool_calls')
        if n==2:return completion({'role':'assistant','tool_calls':[tool('vault_read_note',{'path':'Lab/note.md'},'call2')]},'tool_calls')
        return completion({'role':'assistant','content':'Verified synthetic evidence [Lab/note.md].'})
    client,_=setup(tmp_path,{'client_tools':True,'mcp_vault':True},handler=backend)
    with client:
        response=ask(client,stream=stream)
        assert response.status_code==200
        assert 'Vault MCP activity' in response.text
        assert 'Demo research activity' not in response.text
        assert calls==['vault_search','vault_read_note']
        identity=client.app.state.identity;principal=identity.authenticate(HEADERS['Authorization'])
        monkeypatch.setattr(identity,'authenticate',lambda _:replace(principal,tools=frozenset(),collections=frozenset()))
        # Catalog remains declarative; execution honors identity permissions each round.
        assert client.get('/v1/profiles',headers=HEADERS).status_code==200


def test_path_constraints():
    for path in ['/etc/passwd','../note.md','a/../b.md','.hidden/note.md','a\\b.md','config.json']:
        assert not safe_path(path)
    assert safe_path('Home Lab/note.md')


def test_folder_listing_grants_only_safe_in_folder_reads(monkeypatch):
    monkeypatch.setenv('HARNESS_VAULT_MCP_URL','http://vault/mcp')
    store=VaultStore();calls=[]
    async def fake(name,args):
        calls.append((name,args))
        return {'notes':[{'path':'IN254/Unit 5/Prompt.md'},{'path':'IN254/Unit 50/Other.md'},{'path':'IN254/Unit 5/.hidden.md'}]} if name=='vault_list_notes' else {'content':'Full prompt'}
    monkeypatch.setattr(store,'call',fake)
    async def run():
        for prefix in ['../x','/etc','a//b','a/.hidden']:
            assert (await store.execute('vault_list_notes',{'path_prefix':prefix}))['error']=='invalid_folder'
        assert not calls
        result=await store.execute('vault_list_notes',{'path_prefix':'IN254/Unit 5'})
        assert result['notes']==[{'path':'IN254/Unit 5/Prompt.md'}]
        assert (await store.execute('vault_read_note',{'path':'IN254/Unit 5/Prompt.md'}))['content']=='Full prompt'
        assert store.read_paths=={'IN254/Unit 5/Prompt.md'}
    asyncio.run(run())


def test_two_discoveries_reserve_a_read(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_VAULT_MCP_URL','http://vault/mcp')
    rounds=[];calls=[]
    async def fake(self,name,args):
        calls.append(name)
        return {'results':[{'path':'Course/Unit 5/Prompt.md'}]} if name=='vault_search' else {'content':'Full prompt evidence'}
    monkeypatch.setattr(VaultStore,'call',fake)
    def backend(request):
        if request.url.path!='/v1/chat/completions':return None
        body=json.loads(request.content);rounds.append(body);n=len(rounds)
        if n<=2:return completion({'role':'assistant','tool_calls':[tool('vault_search',{'query':'prompt'},f'call{n}')]},'tool_calls')
        if n==3:
            assert body['tool_choice']=={'type':'function','function':{'name':'vault_read_note'}}
            assert [x['function']['name'] for x in body['tools']]==['vault_read_note']
            return completion({'role':'assistant','tool_calls':[tool('vault_read_note',{'path':'Course/Unit 5/Prompt.md'},'call3')]},'tool_calls')
        return completion({'role':'assistant','content':'Read the full prompt.'})
    c,_=setup(tmp_path,{'client_tools':True,'mcp_vault':True},handler=backend)
    with c:
        assert ask(c).status_code==200
    assert calls==['vault_search','vault_search','vault_read_note']


def test_create_and_append_are_the_only_writes(monkeypatch):
    monkeypatch.setenv('HARNESS_VAULT_MCP_URL','http://vault/mcp')
    store=VaultStore();calls=[]
    async def fake(name,args):
        calls.append((name,args))
        if name=='vault_create_note':
            return {'error':'note already exists: Drafts/a.md'} if args['path']=='Drafts/a.md' else {'status':'created','path':args['path']}
        if name=='vault_append':
            return {'error':'note not found: Notes/x.md'} if args['path']=='Notes/x.md' else {'status':'appended','path':args['path']}
        return {'content':'Draft body'}
    monkeypatch.setattr(store,'call',fake)
    async def run():
        for bad in ['../out.md','/etc/x.md','.obsidian/a.md','Drafts/a.txt']:
            assert (await store.execute('vault_create_note',{'path':bad,'content':'x'}))['error']=='invalid_note_path'
        assert (await store.execute('vault_create_note',{'path':'Drafts/b.md','content':'x'*20001}))['error']=='invalid_arguments'
        for name in ['vault_delete_note','vault_overwrite_note','vault_move_note']:
            assert (await store.execute(name,{'path':'Drafts/b.md'}))['error']=='tool_not_allowed'
        assert not calls
        assert (await store.execute('vault_create_note',{'path':'Drafts/a.md','content':'x'}))['error']=='note_already_exists'
        created=await store.execute('vault_create_note',{'path':'Drafts/b.md','content':'# Draft'})
        assert created=={'source':'Local_AI_Vault','status':'created','path':'Drafts/b.md'}
        # A note created in this request can be read back without searching for it.
        assert (await store.execute('vault_read_note',{'path':'Drafts/b.md'}))['content']=='Draft body'
        assert (await store.execute('vault_append',{'path':'Notes/x.md','text':'more'}))['error']=='note_not_found'
        assert (await store.execute('vault_append',{'path':'Drafts/b.md','text':'more'}))['status']=='appended'
        assert store.writes==['Drafts/b.md','Drafts/b.md']
    asyncio.run(run())


def test_unconfirmed_writes_are_not_reported_as_success(monkeypatch):
    monkeypatch.setenv('HARNESS_VAULT_MCP_URL','http://vault/mcp')
    store=VaultStore()
    async def fake(name,args):
        return {'status':'ok'}
    monkeypatch.setattr(store,'call',fake)
    assert asyncio.run(store.execute('vault_create_note',{'path':'Drafts/c.md','content':'x'}))['error']=='vault_write_failed'
    assert store.writes==[]


def test_loop_writes_a_full_length_note(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_VAULT_MCP_URL','http://vault/mcp')
    body='# Unit 6 draft\n'+'Paragraph text. '*400
    rounds=[];calls=[]
    async def fake(self,name,args):
        calls.append((name,len(args.get('content',''))))
        return {'status':'created','path':args['path']}
    monkeypatch.setattr(VaultStore,'call',fake)
    def backend(request):
        if request.url.path!='/v1/chat/completions':return None
        rounds.append(json.loads(request.content))
        if len(rounds)==1:
            return completion({'role':'assistant','tool_calls':[tool('vault_create_note',{'path':'Drafts/Unit 6.md','content':body})]},'tool_calls')
        return completion({'role':'assistant','content':'Saved to Drafts/Unit 6.md.'})
    c,_=setup(tmp_path,{'client_tools':True,'mcp_servers':['vault']},handler=backend)
    with c:
        r=ask(c)
        assert r.status_code==200 and 'vault_create_note' in r.text
    assert calls==[('vault_create_note',len(body))] and len(body)>2048


def test_read_cap_is_configurable_and_bounded(monkeypatch):
    from vault_mcp import DEFAULT_READ_CHARS
    monkeypatch.setenv('HARNESS_VAULT_MCP_URL','http://vault/mcp')
    assert VaultStore().read_chars == DEFAULT_READ_CHARS == 48000
    monkeypatch.setenv('HARNESS_VAULT_READ_CHARS','90000')
    store = VaultStore()
    async def fake(name,args):
        return {'results':[{'path':'Lab/long.md','snippet':'s'}]} if name=='vault_search' else {'content':'y'*85000}
    monkeypatch.setattr(store,'call',fake)
    async def run():
        await store.execute('vault_search',{'query':'long'})
        result = await store.execute('vault_read_note',{'path':'Lab/long.md'})
        assert len(result['content']) == 85000 and result['truncated'] is False
    asyncio.run(run())
    for bad in ['abc', '1000', '500000']:
        monkeypatch.setenv('HARNESS_VAULT_READ_CHARS', bad)
        with pytest.raises(ValueError):
            VaultStore()


def test_long_notes_fit_through_the_transport(monkeypatch):
    import vault_mcp
    monkeypatch.setenv('HARNESS_VAULT_MCP_URL','http://vault/mcp')
    seen = {}
    async def fake_call_tool(url, name, args, timeout, prefix, headers=None, max_bytes=65536):
        seen['max_bytes'] = max_bytes
        return {'content': 'z'}
    monkeypatch.setattr(vault_mcp, 'call_tool', fake_call_tool)
    asyncio.run(VaultStore().call('vault_read_note', {'path': 'Lab/a.md'}))
    assert seen['max_bytes'] >= 48000 * 6
