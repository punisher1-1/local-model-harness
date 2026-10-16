import React, {useState, useRef, useEffect} from 'react';
import Brand from './components/Brand';
import Login from './components/Login';
import Sidebar from './components/Sidebar';
import ChatArea from './components/ChatArea';
import SettingsModal from './components/SettingsModal';
import {profiles as getProfiles, chat, historyRequest, loadHistory, storedConversation, replayHistory, newId, startSession, currentSession, endSession, onUnauthorized} from './client';
import './App.css';

// App owns the sign-in state and the conversation list. The harness credential
// is exchanged once for an HttpOnly session cookie and is never kept in the page;
// transcripts are stored on the harness, never in the browser.
function App() {
  const [connected, setConnected] = useState(false);
  const [checking, setChecking] = useState(true);
  const [notice, setNotice] = useState('');
  const [catalog, setCatalog] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [active, setActive] = useState(null);
  const [selected, setSelected] = useState('');
  const [skill, setSkill] = useState('');
  const [mcp, setMcp] = useState([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const abort = useRef(null);
  const session = sessions.find(s => s.id === active);
  const profile = catalog.find(p => p.id === (session?.profile || selected));

  // Tool servers that start switched on for a new chat on this profile.
  function mcpDefaults(p) {
    return (p?.mcp_servers || []).filter(s => s.default).map(s => s.id);
  }

  function chooseProfile(id, list = catalog) {
    setSelected(id); setSkill(''); setMcp(mcpDefaults(list.find(p => p.id === id)));
  }

  function toggleMcp(id) {
    setMcp(list => list.includes(id) ? list.filter(s => s !== id) : [...list, id]);
  }

  function reset() {
    abort.current?.abort();
    setConnected(false); setCatalog([]); setSessions([]); setActive(null); setSkill(''); setError(''); setSettingsOpen(false);
  }

  // Restore an existing session on load; any later 401 means it has expired.
  useEffect(() => {
    onUnauthorized(() => { reset(); setNotice('Your session expired. Sign in again.'); });
    currentSession().then(s => s && loadWorkspace()).catch(e => setNotice(e.message)).finally(() => setChecking(false));
    return () => { onUnauthorized(null); abort.current?.abort(); };
  }, []);

  async function loadWorkspace() {
    const data = await getProfiles();
    if (!data.length) throw new Error('This identity has no available profiles.');
    const saved = await loadHistory();
    setSessions(saved); setActive(null); setCatalog(data); chooseProfile(data[0].id, data); setError(''); setNotice(''); setConnected(true);
  }

  async function connect(key) {
    await startSession(key);
    try { await loadWorkspace(); } catch (e) { await endSession(); throw e; }
  }

  async function disconnect() {
    reset();
    setNotice('');
    await endSession();
  }

  function fresh() {
    if (busy) return;
    setActive(null); setError(''); chooseProfile(selected);
  }

  function update(sid, mid, fn) {
    setSessions(old => old.map(s => s.id === sid ? {...s, messages: s.messages.map(m => m.id === mid ? fn(m) : m)} : s));
  }

  async function openSession(s) {
    setBusy(true); setError('');
    try {
      const loaded = await historyRequest('', `/${s.id}`);
      setSessions(list => list.map(x => x.id === s.id ? loaded : x));
      // Restore this chat's workflow and tools, limited to what the profile still allows.
      const allowed = catalog.find(p => p.id === loaded.profile);
      const available = (allowed?.mcp_servers || []).map(x => x.id);
      setActive(s.id); setSelected(loaded.profile); setSkill(allowed?.skills.includes(loaded.skill) ? loaded.skill : '');
      setMcp(loaded.mcp_servers ? loaded.mcp_servers.filter(id => available.includes(id)) : mcpDefaults(allowed));
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  async function saveSession(record) {
    const receipt = await historyRequest('', `/${record.id}`, 'PUT', storedConversation(record));
    setSessions(list => list.map(s => s.id === record.id ? {...s, revision: receipt.revision, unsaved: false} : s));
    return {...record, revision: receipt.revision, unsaved: false};
  }

  async function retrySave() {
    setBusy(true);
    try { await saveSession(session); setError(''); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  async function removeSession() {
    if (!window.confirm('Delete this saved conversation? This cannot be undone.')) return;
    setBusy(true);
    try {
      await historyRequest('', `/${session.id}?revision=${session.revision}`, 'DELETE');
      setSessions(list => list.filter(s => s.id !== session.id)); setActive(null); setError('');
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  // Save the user turn first, stream the answer, then save the final state.
  // Stopped or failed answers are kept for display but never replayed.
  async function send(text) {
    if (busy || !profile) return;
    if (session?.unsaved) { setError('Save the previous turn before continuing, or reopen the conversation to load the saved version.'); return; }
    const sid = session?.id || newId(), mid = newId(), user = {id: newId(), role: 'user', content: text, skill};
    const old = session?.messages || [];
    const history = replayHistory(old, text, skill);
    let answer = {id: mid, role: 'assistant', content: '', reasoning: '', status: 'running'};
    let record = {...(session || {id: sid, title: text.slice(0, 48), profile: profile.id, revision: 0}), messages: [...old, user], skill, mcp_servers: mcp, unsaved: true};
    setSessions(list => session ? list.map(s => s.id === sid ? record : s) : [record, ...list]);
    setActive(sid); setBusy(true); setError('');
    const controller = new AbortController(); abort.current = controller;
    let visible = false, toolCalls = false, started = false;
    try {
      record = await saveSession(record);
      if (controller.signal.aborted) return;
      started = true;
      setSessions(list => list.map(s => s.id === sid ? {...s, messages: [...record.messages, answer]} : s));
      await chat({profile: profile.id, messages: history, signal: controller.signal, mcp: profile.mcp_servers?.length ? mcp : undefined,
        onHeaders: meta => { answer = {...answer, meta}; update(sid, mid, () => answer); },
        onEvent: event => {
          const delta = event.choices?.[0]?.delta || {};
          if (delta.content?.trim()) visible = true;
          if (delta.tool_calls?.length) toolCalls = true;
          answer = {...answer, content: answer.content + (delta.content || ''),
            reasoning: answer.reasoning + (delta.reasoning_content || delta.reasoning || ''),
            usage: event.usage || answer.usage, finish: event.choices?.[0]?.finish_reason || answer.finish};
          update(sid, mid, () => answer);
        }});
      if (toolCalls) throw new Error('This client has no tool executor. The requested tool was not run.');
      if (!visible) throw new Error('The model completed without a visible answer.');
      answer = {...answer, status: 'complete'};
    } catch (e) {
      if (started) {
        const stopped = e.name === 'AbortError';
        answer = {...answer, status: stopped ? 'stopped' : 'failed', error: stopped ? 'Stopped. Partial output is not included in future requests.' : e.message};
      } else {
        setError(`Chat was not sent: ${e.message}`);
        setSessions(list => list.map(s => s.id === sid ? {...s, unsaved: true} : s));
      }
    } finally {
      if (started) {
        update(sid, mid, () => answer);
        record = {...record, messages: [...record.messages, answer]};
        try { await saveSession(record); }
        catch (e) { setError(`Answer received but not saved: ${e.message}`); setSessions(list => list.map(s => s.id === sid ? {...s, unsaved: true} : s)); }
      }
      setBusy(false); abort.current = null;
    }
  }

  return (
    <div className="app-container">
      <header className="top-banner">
        <Brand/>
      </header>
      {checking ? null : !connected ? <Login onConnect={connect} notice={notice}/> : (
        <div className="main-content">
          <Sidebar sessions={sessions} active={active} busy={busy} onNewChat={fresh} onSelect={openSession}
            onOpenSettings={() => setSettingsOpen(true)} onDisconnect={disconnect}/>
          <ChatArea session={session} profile={profile} catalog={catalog} busy={busy} error={error}
            selected={session?.profile || selected} onSelectProfile={id => chooseProfile(id)}
            skill={skill} onSelectSkill={setSkill} mcp={mcp} onToggleMcp={toggleMcp} onSend={send} onStop={() => abort.current?.abort()}
            onDelete={removeSession} onRetrySave={retrySave} onError={setError}/>
        </div>
      )}
      {settingsOpen && <SettingsModal catalog={catalog} onDisconnect={disconnect} onClose={() => setSettingsOpen(false)}/>}
    </div>
  );
}

export default App;
