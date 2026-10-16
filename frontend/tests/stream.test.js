import test from 'node:test';
import assert from 'node:assert/strict';
import {consumeStream,chat,profiles} from '../src/client.js';
function stream(text,size=1){const data=new TextEncoder().encode(text);return new ReadableStream({start(c){for(let i=0;i<data.length;i+=size)c.enqueue(data.slice(i,i+size));c.close();}});}
test('fragmented UTF-8 and CRLF frames preserve reasoning, text and usage',async()=>{const events=[];await consumeStream(stream(': heartbeat\r\n\r\ndata: {"choices":[{"delta":{"reasoning_content":"think"}}]}\r\n\r\ndata: {"choices":[{"delta":{"content":"café"}}]}\r\n\r\ndata: {"usage":{"total_tokens":7}}\r\n\r\ndata: [DONE]\r\n\r\n'),e=>events.push(e));assert.equal(events.length,3);assert.equal(events[1].choices[0].delta.content,'café');assert.equal(events[2].usage.total_tokens,7);});
test('server errors are surfaced',async()=>{await assert.rejects(consumeStream(stream('data: {"error":{"message":"Output limit reached"}}\n\n'),()=>{}),/Output limit reached/);});
test('truncated streams and malformed events fail',async()=>{for(const text of ['data: {"choices":[]}\n\n','data: not-json\n\n'])await assert.rejects(consumeStream(stream(text),()=>{}));});
test('DONE stops parsing further frames',async()=>{const events=[];await consumeStream(stream('data: [DONE]\n\ndata: invalid\n\n',500),e=>events.push(e));assert.equal(events.length,0);});
test('HTTP auth failures are explicit',async()=>{const old=globalThis.fetch;globalThis.fetch=async()=>new Response('{}',{status:401});try{await assert.rejects(profiles('test-only-key'),/credential/);}finally{globalThis.fetch=old;}});
test('chat sends only history, profile and stream controls',async()=>{const old=globalThis.fetch;globalThis.fetch=async(url,options)=>{assert.equal(options.headers.Authorization,'Bearer test-only-key');assert.deepEqual(JSON.parse(options.body),{model:'school',messages:[{role:'user',content:'Draft'}],stream:true,stream_options:{include_usage:true}});return new Response(stream('data: [DONE]\n\n'),{headers:{'content-type':'text/event-stream'}});};try{await chat({token:'test-only-key',profile:'school',messages:[{role:'user',content:'Draft'}],onEvent:()=>{}});}finally{globalThis.fetch=old;}});


test('saved transcripts exclude reasoning, metadata, usage, and running output',async()=>{
 const {storedConversation}=await import('../src/client.js');
 const data=storedConversation({profile:'school',title:'Draft',revision:3,messages:[{id:'1',role:'user',content:'Hello'},{id:'2',role:'assistant',content:'Answer',status:'complete',reasoning:'private',meta:{},usage:{}},{id:'3',role:'assistant',content:'partial',status:'running'}]});
 assert.equal(data.revision,3);assert.equal(data.messages.length,2);
 assert.equal(data.messages[1].reasoning,undefined);assert.equal(data.messages[1].usage,undefined);
});

test('replayed history keeps user turns and complete answers, with a one-turn workflow directive',async()=>{
 const {replayHistory}=await import('../src/client.js');
 const old=[{role:'user',content:'One'},{role:'assistant',content:'Done',status:'complete'},{role:'user',content:'Two'},{role:'assistant',content:'partial',status:'stopped'},{role:'assistant',content:'bad',status:'failed'}];
 assert.deepEqual(replayHistory(old,'Three','apa-review'),[{role:'user',content:'One'},{role:'assistant',content:'Done'},{role:'user',content:'Two'},{role:'user',content:'/skill apa-review\nThree'}]);
 assert.deepEqual(replayHistory([],'Hi').at(-1),{role:'user',content:'Hi'});
});

test('session requests use the cookie plus client header and never send a bearer token',async()=>{
 const {profiles:list,onUnauthorized}=await import('../src/client.js');
 const old=globalThis.fetch;let expired=0;onUnauthorized(()=>expired++);
 globalThis.fetch=async(url,options)=>{assert.equal(options.headers.Authorization,undefined);assert.equal(options.headers['X-Harness-Client'],'chat');assert.equal(options.credentials,'same-origin');return new Response('{"data":[{"id":"local"}]}',{status:200});};
 try{assert.equal((await list())[0].id,'local');
  globalThis.fetch=async()=>new Response('{}',{status:401});
  await assert.rejects(list());assert.equal(expired,1);
 }finally{globalThis.fetch=old;onUnauthorized(null);}
});
test('session check returns null when signed out and start sends the key once',async()=>{
 const {currentSession,startSession}=await import('../src/client.js');
 const old=globalThis.fetch;
 globalThis.fetch=async()=>new Response('{}',{status:401});
 try{assert.equal(await currentSession(),null);
  globalThis.fetch=async(url,options)=>{assert.equal(options.method,'POST');assert.equal(options.headers.Authorization,'Bearer test-only-key');assert.equal(options.headers['X-Harness-Client'],'chat');return new Response('{"actor_id":"lab-service"}',{status:201});};
  assert.equal((await startSession('test-only-key')).actor_id,'lab-service');
 }finally{globalThis.fetch=old;}
});

test('tool selection travels as a header: list, none, or omitted for the profile default',async()=>{
 const old=globalThis.fetch;const seen=[];
 globalThis.fetch=async(url,options)=>{seen.push(options.headers['X-Harness-MCP']);return new Response(stream('data: [DONE]\n\n'),{headers:{'content-type':'text/event-stream'}});};
 try{for(const mcp of [['vault'],[],undefined])await chat({profile:'tools',messages:[{role:'user',content:'x'}],onEvent:()=>{},mcp});
  assert.deepEqual(seen,['vault','none',undefined]);
 }finally{globalThis.fetch=old;}
});
test('saved chats keep their workflow and tool choices',async()=>{
 const {storedConversation}=await import('../src/client.js');
 const data=storedConversation({profile:'tools',title:'t',messages:[],skill:'vault-research',mcp_servers:['vault']});
 assert.equal(data.skill,'vault-research');assert.deepEqual(data.mcp_servers,['vault']);
 assert.equal(storedConversation({profile:'p',title:'t',messages:[]}).mcp_servers,null);
});
