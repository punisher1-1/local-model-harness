// Requests authenticate with an explicit bearer token when one is given, and
// otherwise with the harness session cookie. Cookie requests must carry the
// client header; cross-origin pages cannot add it without a CORS preflight.
const CLIENT = {'X-Harness-Client':'chat'};
let unauthorized = null;

export function onUnauthorized(handler) { unauthorized = handler; }

function authHeaders(token) {
  return token ? {Authorization:`Bearer ${token}`} : CLIENT;
}

async function request(path, options={}, token='') {
  const response = await fetch(path, {cache:'no-store', credentials:'same-origin', ...options, headers:{...authHeaders(token), ...options.headers}});
  if (response.status === 401 && !token) unauthorized?.();
  return response;
}

async function failure(response, fallback) {
  try { const data = await response.json(); return data.error?.message || data.detail || fallback; } catch { return fallback; }
}

export async function startSession(key) {
  const response = await fetch('/v1/session', {method:'POST', cache:'no-store', credentials:'same-origin', headers:{...CLIENT, Authorization:`Bearer ${key}`}});
  if (!response.ok) throw new Error(response.status === 401 ? 'The credential was not accepted.' : await failure(response, `Cannot start a session (HTTP ${response.status}).`));
  return response.json();
}

// Returns null when there is no live session, so the page can show sign-in.
export async function currentSession() {
  const response = await fetch('/v1/session', {cache:'no-store', credentials:'same-origin', headers:CLIENT});
  if (response.status === 401) return null;
  if (!response.ok) throw new Error(`Cannot check the session (HTTP ${response.status}).`);
  return response.json();
}

export async function endSession() {
  await fetch('/v1/session', {method:'DELETE', cache:'no-store', credentials:'same-origin', headers:CLIENT}).catch(()=>{});
}

export async function profiles(token) {
  const response = await request('/v1/profiles', {}, token);
  if (!response.ok) throw new Error(response.status === 401 ? 'The credential was not accepted.' : `Cannot load profiles (HTTP ${response.status}).`);
  return (await response.json()).data;
}

export async function identity(token) {
  const response = await request('/v1/identity', {}, token);
  if (!response.ok) throw new Error(`Cannot load identity (HTTP ${response.status}).`);
  return response.json();
}

export function newId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return '10000000-1000-4000-8000-100000000000'.replace(/[018]/g,c=>(Number(c)^crypto.getRandomValues(new Uint8Array(1))[0]&15>>Number(c)/4).toString(16));
}

// Only user turns and complete answers are replayed; stopped or failed output
// never becomes model context. A selected workflow applies to this turn only.
export function replayHistory(messages, text, skill='') {
  const history = messages.filter(m=>m.role==='user' || m.status==='complete').map(m=>({role:m.role,content:m.content}));
  history.push({role:'user',content:skill?`/skill ${skill}\n${text}`:text});
  return history;
}

export async function consumeStream(stream, onEvent) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let complete = false;
  try {
    while (!complete) {
      const {value,done} = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value,{stream:true});
      let match;
      while ((match = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0,match.index);
        buffer = buffer.slice(match.index+match[0].length);
        const data = frame.split(/\r?\n/).filter(line=>line.startsWith('data:')).map(line=>line.slice(5).trimStart()).join('\n');
        if (!data) continue;
        if (data.trim()==='[DONE]') {complete=true;break;}
        let event;
        try {event=JSON.parse(data);} catch {throw new Error('The server sent an invalid stream event.');}
        if (event.error) throw new Error(event.error.message || 'The server reported a streaming error.');
        onEvent(event);
      }
      if (done) break;
    }
    if (!complete) throw new Error('The connection ended before the response completed. The answer may be incomplete.');
  } finally {
    await reader.cancel().catch(()=>{});
    reader.releaseLock();
  }
}

// mcp: undefined leaves the profile default; an array selects those servers ([] turns tools off).
export async function chat({token,profile,messages,signal,onEvent,onHeaders,mcp}) {
  const response=await request('/v1/chat/completions',{method:'POST',headers:{'Content-Type':'application/json',...(mcp?{'X-Harness-MCP':mcp.length?mcp.join(','):'none'}:{})},body:JSON.stringify({model:profile,messages,stream:true,stream_options:{include_usage:true}}),signal},token);
  if (!response.ok) throw new Error(await failure(response, `Request failed (HTTP ${response.status}).`));
  if (!response.headers.get('content-type')?.includes('text/event-stream') || !response.body) throw new Error('The server did not return a chat stream.');
  onHeaders?.({skill:response.headers.get('x-harness-skill-selection'),mcp:response.headers.get('x-harness-mcp'),context:response.headers.get('x-harness-context-status'),requestId:response.headers.get('x-request-id')});
  await consumeStream(response.body,onEvent);
}

export async function historyRequest(token, path='', method='GET', body) {
  const response=await request('/v1/conversations'+path,{method,headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})},token);
  if (!response.ok) throw new Error(await failure(response, `History request failed (HTTP ${response.status}).`));
  return response.status===204?null:response.json();
}
export async function loadHistory(token) {
  const rows=[];let offset=0;
  do {const page=await historyRequest(token,`?offset=${offset}`);rows.push(...page.data);offset=page.next_offset;} while(offset!==null);
  return rows;
}
export function storedConversation(session) {
  return {profile:session.profile,title:session.title,revision:session.revision || 0,skill:session.skill || '',mcp_servers:session.mcp_servers ?? null,
    messages:session.messages.filter(m=>m.status!=='running').map(m=>({id:m.id,role:m.role,content:m.content,skill:m.skill || '',status:m.status || 'complete',error:m.error?.slice(0,1000) || null,finish:m.finish || null}))};
}
