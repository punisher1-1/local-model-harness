import React, {useEffect, useState} from 'react';
import {memoryRequest, newId, scopeLabel, utf8Length} from '../client';

const LIMIT = 8192;

// The signed-in person's saved memories, one scope at a time. Only that person's own
// memories are listed; profiles that recall a scope bring matching ones into its chats.
function MemoryPanel({scopes, permissions}) {
  const [scope, setScope] = useState(scopes.includes('home') ? 'home' : scopes.find(s => s !== 'legacy') || scopes[0]);
  const [health, setHealth] = useState(null);
  const [rows, setRows] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [query, setQuery] = useState('');
  const [searched, setSearched] = useState('');
  const [draft, setDraft] = useState({content: '', category: 'fact', key: newId()});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const can = p => permissions.includes(p);

  async function load(more = false, search = '') {
    setBusy(true); setError('');
    try {
      const page = search ? await memoryRequest(scope, '/search', 'POST', {query: search, limit: 50})
        : await memoryRequest(scope, `?limit=20${more && cursor ? '&cursor=' + encodeURIComponent(cursor) : ''}`);
      setRows(list => more ? [...list, ...page.data] : page.data);
      setCursor(search ? null : page.next_cursor); setSearched(search);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  useEffect(() => {
    let live = true;
    setRows([]); setCursor(null); setQuery(''); setSearched(''); setStatus(''); setHealth(null);
    memoryRequest(scope, '/health').then(h => live && setHealth(h), e => live && setError(e.message));
    load();
    return () => { live = false; };
  }, [scope]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save(e) {
    e.preventDefault();
    setBusy(true); setError(''); setStatus('');
    try {
      // The key stays with the draft until it saves, so a retried save never duplicates.
      const row = await memoryRequest(scope, '', 'POST', {content: draft.content, category: draft.category, idempotency_key: draft.key});
      setRows(list => [row, ...list.filter(r => r.memory_id !== row.memory_id)]);
      setDraft({content: '', category: draft.category, key: newId()}); setStatus('Saved.');
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }

  async function remove(row) {
    if (!window.confirm('Delete this memory? Copies already in chat history are not removed.')) return;
    setBusy(true); setError(''); setStatus('');
    try { await memoryRequest(scope, `/${row.memory_id}`, 'DELETE'); setRows(list => list.filter(r => r.memory_id !== row.memory_id)); setStatus('Deleted.'); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  const size = utf8Length(draft.content);
  return (
    <section className="settings-section memory-panel">
      <div className="skills-heading">
        <h3>Memory</h3>
        <label className="memory-scope">Scope
          <select value={scope} disabled={busy} onChange={e => setScope(e.target.value)}>
            {scopes.map(s => <option key={s} value={s}>{scopeLabel(s)}</option>)}
          </select>
        </label>
      </div>
      <p className="setting-desc">
        Facts and preferences saved for you. Only you can see these. {health && (health.recall_profiles?.length
          ? `Chats on ${health.recall_profiles.join(', ')} recall matching memories from this scope.`
          : 'No profile you can use recalls this scope.')} Nothing is saved automatically.
      </p>

      {can('memory.write') && (
        <form className="memory-add" onSubmit={save}>
          <textarea value={draft.content} rows={3} placeholder="Something worth remembering, in one or two sentences"
            onChange={e => setDraft({...draft, content: e.target.value})}/>
          <div className="skill-editor-meta">
            <select value={draft.category} onChange={e => setDraft({...draft, category: e.target.value})} aria-label="Category">
              <option value="fact">Fact</option><option value="preference">Preference</option><option value="note">Note</option>
            </select>
            <span className={`char-count ${size > LIMIT * 0.9 ? 'near' : ''}`}>{size.toLocaleString()} / {LIMIT.toLocaleString()} bytes</span>
            <button type="submit" className="btn primary-btn" disabled={busy || !draft.content.trim() || size > LIMIT}>Save</button>
          </div>
        </form>
      )}

      <form className="memory-search" onSubmit={e => { e.preventDefault(); load(false, query.trim()); }}>
        <input value={query} placeholder="Search by keyword" onChange={e => setQuery(e.target.value)}/>
        <button type="submit" className="btn secondary-btn" disabled={busy}>Search</button>
        {searched && <button type="button" className="btn secondary-btn" disabled={busy} onClick={() => { setQuery(''); load(); }}>Show all</button>}
      </form>

      {error && <p className="error" role="alert">{error}</p>}
      {status && <p className="muted" role="status">{status}</p>}
      {!busy && !rows.length && !error && <p className="muted">{searched ? 'No memories match every word.' : 'No memories in this scope yet.'}</p>}
      <ul className="memory-list">
        {rows.map(r => (
          <li key={r.memory_id} className="memory-row">
            <p className="memory-text">{r.content}</p>
            <div className="memory-meta">
              <span className="skill-badge">{r.category}</span>
              <span>{new Date(r.created_at).toLocaleDateString()}</span>
              {can('memory.delete') && <button type="button" className="copy" disabled={busy} onClick={() => remove(r)}>Delete</button>}
            </div>
          </li>
        ))}
      </ul>
      {cursor && <button type="button" className="btn secondary-btn" disabled={busy} onClick={() => load(true)}>Load more</button>}
    </section>
  );
}

export default MemoryPanel;
