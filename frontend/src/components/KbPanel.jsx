import React, {useEffect, useRef, useState} from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {kbImport, kbRequest, newId} from '../client';

const LIMIT = 100000;
const blank = {title: '', body: '', tags: [], status: 'draft', revision: 0};

// The team knowledge base: Markdown articles the model searches with kb_search. Everyone
// with access can read published articles; editors (kb_editor grant) also see drafts and
// can write, publish and delete. Only published articles reach the model.
function KbPanel() {
  const [rows, setRows] = useState(null);
  const [editor, setEditor] = useState(false);
  const [filter, setFilter] = useState('');
  const [editing, setEditing] = useState(null); // null: list; article: view or editor
  const [mode, setMode] = useState('view'); // view | edit | preview
  const [tagText, setTagText] = useState('');
  const [test, setTest] = useState({q: '', result: null});
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const file = useRef(null);

  async function load() {
    try { const data = await kbRequest(); setRows(data.data); setEditor(data.editor); } catch (e) { setError(e.message); }
  }
  useEffect(() => { load(); }, []);

  async function open(row) {
    setError('');
    if (!row) { setEditing({...blank}); setTagText(''); setMode('edit'); return; }
    try { const a = await kbRequest(`/${row.id}`); setEditing(a); setTagText(a.tags.join(', ')); setMode('view'); }
    catch (e) { setError(e.message); }
  }

  async function save(e) {
    e.preventDefault();
    setSaving(true); setError('');
    const tags = tagText.split(',').map(t => t.trim()).filter(Boolean).slice(0, 12);
    try {
      const saved = await kbRequest(`/${editing.id || newId()}`, 'PUT',
        {title: editing.title.trim(), body: editing.body, tags, status: editing.status, revision: editing.revision});
      setEditing(saved); setTagText(saved.tags.join(', ')); setMode('view');
      load();
    } catch (err) { setError(err.message); } finally { setSaving(false); }
  }

  // Fills the editor from a .md file. Fields already typed are kept; the body is replaced.
  async function importFile(e) {
    const picked = e.target.files?.[0];
    e.target.value = '';
    if (!picked) return;
    if (picked.size > LIMIT * 4) { setError(`That file is too large; articles hold up to ${LIMIT.toLocaleString()} characters.`); return; }
    const {title, tags, body} = kbImport(await picked.text(), picked.name);
    if (body.length > LIMIT) { setError(`That file has ${body.length.toLocaleString()} characters; articles hold up to ${LIMIT.toLocaleString()}.`); return; }
    setEditing(a => ({...a, title: a.title.trim() ? a.title : title, body}));
    if (!tagText.trim() && tags.length) setTagText(tags.join(', '));
    setMode('edit'); setError('');
  }

  async function remove() {
    if (!window.confirm(`Delete "${editing.title}"? The model stops finding it right away.`)) return;
    setSaving(true); setError('');
    try { await kbRequest(`/${editing.id}?revision=${editing.revision}`, 'DELETE'); setEditing(null); load(); }
    catch (err) { setError(err.message); } finally { setSaving(false); }
  }

  async function runTest(e) {
    e.preventDefault();
    setError('');
    try { setTest({...test, result: await kbRequest(`/search?q=${encodeURIComponent(test.q)}`)}); } catch (err) { setError(err.message); }
  }

  const close = () => { setEditing(null); setError(''); };
  const when = iso => new Date(iso).toLocaleString();

  if (editing && mode !== 'view') {
    const length = editing.body.length;
    return (
      <form className="settings-section skill-editor" onSubmit={save}>
        <h3>{editing.id ? 'Edit article' : 'New article'}</h3>
        <p className="setting-desc">Write in Markdown or import a .md file. Start each part with a heading (## Symptoms, ## Fix); the model finds and cites articles by section.</p>
        <label className="field">Title
          <input value={editing.title} maxLength={200} required autoFocus placeholder="Domain rename fails: RPC server unavailable"
            onChange={e => setEditing({...editing, title: e.target.value})}/>
        </label>
        <label className="field">Tags
          <input value={tagText} placeholder="active directory, rename" onChange={e => setTagText(e.target.value)}/>
        </label>
        <div className="kb-tabs" role="tablist">
          <button type="button" role="tab" aria-selected={mode === 'edit'} className={`tab-btn ${mode === 'edit' ? 'active' : ''}`} onClick={() => setMode('edit')}>Write</button>
          <button type="button" role="tab" aria-selected={mode === 'preview'} className={`tab-btn ${mode === 'preview' ? 'active' : ''}`} onClick={() => setMode('preview')}>Preview</button>
        </div>
        {mode === 'edit'
          ? <textarea aria-label="Article body" value={editing.body} rows={16} maxLength={LIMIT} required spellCheck
              placeholder={'## Symptoms\n…\n\n## Cause\n…\n\n## Fix\n1. …'} onChange={e => setEditing({...editing, body: e.target.value})}/>
          : <div className="kb-article"><Markdown remarkPlugins={[remarkGfm]} skipHtml>{editing.body || '*Nothing to preview yet.*'}</Markdown></div>}
        <div className="skill-editor-meta">
          <button type="button" className="btn secondary-btn" onClick={() => file.current?.click()}>Import .md file</button>
          <input ref={file} type="file" accept=".md,.markdown,.txt,text/markdown,text/plain" hidden onChange={importFile}/>
          <label className="skill-share-option">
            <input type="checkbox" checked={editing.status === 'published'} onChange={e => setEditing({...editing, status: e.target.checked ? 'published' : 'draft'})}/>
            Published (the model can find it)
          </label>
          <span className="spacer"></span>
          <span className={`char-count ${length > LIMIT * 0.9 ? 'near' : ''}`}>{length.toLocaleString()} / {LIMIT.toLocaleString()}</span>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="skill-editor-actions">
          {editing.id && <button type="button" className="btn danger-btn" disabled={saving} onClick={remove}>Delete</button>}
          <span className="spacer"></span>
          <button type="button" className="btn secondary-btn" onClick={() => editing.id ? open(editing) : close()}>Cancel</button>
          <button type="submit" className="btn primary-btn" disabled={saving || !editing.title.trim() || !editing.body.trim()}>Save</button>
        </div>
      </form>
    );
  }

  if (editing) {
    return (
      <section className="settings-section skill-editor">
        <h3>{editing.title}</h3>
        <p className="setting-desc">
          {editing.status === 'draft' && <span className="skill-badge kb-draft">Draft</span>}
          {editing.tags.map(t => <span key={t} className="skill-badge">{t}</span>)}
          {' '}Revision {editing.revision}, updated {when(editing.updated_at)} by {editing.updated_by}.
        </p>
        <div className="kb-article"><Markdown remarkPlugins={[remarkGfm]} skipHtml>{editing.body}</Markdown></div>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="skill-editor-actions">
          <span className="spacer"></span>
          <button type="button" className="btn secondary-btn" onClick={close}>Close</button>
          {editor && <button type="button" className="btn primary-btn" onClick={() => setMode('edit')}>Edit</button>}
        </div>
      </section>
    );
  }

  const needle = filter.trim().toLowerCase();
  const shown = (rows || []).filter(r => !needle || r.title.toLowerCase().includes(needle) || r.tags.some(t => t.includes(needle)));
  return (
    <section className="settings-section">
      <div className="skills-heading">
        <h3>Knowledge base</h3>
        {editor && <button className="btn primary-btn" onClick={() => open(null)}>New article</button>}
      </div>
      <p className="setting-desc">The team's runbooks and known fixes. The model searches published articles when a chat has the team knowledge base turned on.{editor ? ' Drafts stay hidden from the model.' : ''}</p>
      {error && <p className="error" role="alert">{error}</p>}
      <label className="field">Filter
        <input value={filter} placeholder="Title or tag" onChange={e => setFilter(e.target.value)}/>
      </label>
      {rows === null && !error && <p className="muted">Loading…</p>}
      {rows?.length === 0 && <p className="muted">No articles yet.{editor ? ' Write the first one.' : ''}</p>}
      <ul className="skill-list">
        {shown.map(r => (
          <li key={r.id}>
            <button className="skill-row" onClick={() => open(r)}>
              <span className="skill-name">{r.title}
                {r.status === 'draft' && <span className="skill-badge kb-draft">Draft</span>}
                {r.tags.map(t => <span key={t} className="skill-badge">{t}</span>)}
              </span>
              <span className="skill-summary">Revision {r.revision} · {when(r.updated_at)} · {r.updated_by}</span>
            </button>
          </li>
        ))}
      </ul>
      <form className="kb-test" onSubmit={runTest}>
        <h3 className="skills-shared-heading">Try a search</h3>
        <p className="setting-desc">Runs the same search the model does, so you can check an article is found for the error text people will paste.</p>
        <div className="skill-editor-meta">
          <input aria-label="Test search" value={test.q} maxLength={1000} placeholder="The RPC server is unavailable" onChange={e => setTest({...test, q: e.target.value})}/>
          <button type="submit" className="btn secondary-btn" disabled={!test.q.trim()}>Search</button>
        </div>
        {test.result && (test.result.results.length
          ? <ol className="kb-results">
              {test.result.weak && <p className="muted">Weak match: the model is told the knowledge base may not cover this.</p>}
              {test.result.results.map((r, i) => <li key={i}><strong>{r.title}</strong>{r.locator && ` — ${r.locator}`}</li>)}
            </ol>
          : <p className="muted">Nothing found. The model would answer without the knowledge base.</p>)}
      </form>
    </section>
  );
}

export default KbPanel;
