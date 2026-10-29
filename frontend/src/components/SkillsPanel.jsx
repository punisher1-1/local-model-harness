import React, {useRef, useState} from 'react';
import {groupLabel, newId, skillRequest} from '../client';

const LIMIT = 16000;

const byName = (a, b) => a.name.localeCompare(b.name, undefined, {sensitivity: 'base'});

// The user's own Markdown workflows: written here or imported from a .md file, saved on the
// harness, and offered under "My skills" in each chat's and project's Workflow menu. Skills
// another account shares with one of the user's groups are listed read-only; edits by their
// owner apply on the next request.
function SkillsPanel({skills, shareGroups = [], onChanged}) {
  const [editing, setEditing] = useState(null); // null: list; {id?, name, content, shared_groups}: editor
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const file = useRef(null);
  const own = skills.filter(s => !s.shared), shared = skills.filter(s => s.shared);

  async function open(skill) {
    setError('');
    if (!skill) { setEditing({name: '', content: '', shared_groups: []}); return; }
    try { setEditing({shared_groups: [], ...await skillRequest(`/${skill.id}`)}); } catch (e) { setError(e.message); }
  }

  async function importFile(e) {
    const picked = e.target.files?.[0];
    e.target.value = '';
    if (!picked) return;
    if (picked.size > LIMIT * 4) { setError(`That file is too large; skills hold up to ${LIMIT.toLocaleString()} characters.`); return; }
    const text = (await picked.text()).trim();
    const heading = text.match(/^#\s+(.+)$/m)?.[1]?.trim();
    setEditing(s => ({...s, content: text, name: s.name || heading || picked.name.replace(/\.(md|markdown|txt)$/i, '')}));
    setError('');
  }

  function toggleGroup(group) {
    const groups = editing.shared_groups.includes(group) ? editing.shared_groups.filter(g => g !== group) : [...editing.shared_groups, group];
    setEditing({...editing, shared_groups: groups});
  }

  async function save(e) {
    e.preventDefault();
    setSaving(true); setError('');
    try {
      const saved = await skillRequest(`/${editing.id || newId()}`, 'PUT',
        {name: editing.name.trim(), content: editing.content, shared_groups: editing.shared_groups.filter(g => shareGroups.includes(g))});
      const row = {id: saved.id, name: saved.name, summary: saved.summary, updated_at: saved.updated_at, shared_groups: saved.shared_groups};
      onChanged([...skills.filter(s => s.id !== saved.id), row].sort(byName));
      setEditing(null);
    } catch (err) { setError(err.message); } finally { setSaving(false); }
  }

  async function remove() {
    const sharedNote = editing.shared_groups.length ? ' It is also removed for everyone it is shared with.' : '';
    if (!window.confirm(`Delete "${editing.name}"? Chats and projects that use it switch to Automatic.${sharedNote}`)) return;
    setSaving(true); setError('');
    try { await skillRequest(`/${editing.id}`, 'DELETE'); onChanged(skills.filter(s => s.id !== editing.id)); setEditing(null); }
    catch (err) { setError(err.message); } finally { setSaving(false); }
  }

  // A shared skill opens read-only; Duplicate starts an editable copy of the user's own.
  if (editing?.shared) {
    return (
      <section className="settings-section skill-editor">
        <h3>{editing.name}</h3>
        <p className="setting-desc">Shared with you by {editing.shared_by}. It updates when they edit it. To change it for yourself, duplicate it into your own skills.</p>
        <pre className="skill-readonly">{editing.content}</pre>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="skill-editor-actions">
          <span className="spacer"></span>
          <button type="button" className="btn secondary-btn" onClick={() => { setEditing(null); setError(''); }}>Close</button>
          <button type="button" className="btn primary-btn"
            onClick={() => setEditing({name: `${editing.name} (copy)`.slice(0, 80), content: editing.content, shared_groups: []})}>Duplicate</button>
        </div>
      </section>
    );
  }

  if (editing) {
    const length = editing.content.length;
    return (
      <form className="settings-section skill-editor" onSubmit={save}>
        <h3>{editing.id ? 'Edit skill' : 'New skill'}</h3>
        <p className="setting-desc">Write how the model should handle a kind of task, in Markdown. It applies only when you choose it for a chat or a project.</p>
        <label className="field">Name
          <input value={editing.name} maxLength={80} required autoFocus placeholder="Peer reply" onChange={e => setEditing({...editing, name: e.target.value})}/>
        </label>
        <label className="field">Instructions
          <textarea value={editing.content} rows={12} maxLength={LIMIT} required spellCheck
            placeholder={'# Peer reply\nWrite a warm reply of about 120 words to a classmate\'s post.\n\n- Name one specific point they made\n- End with one question'}
            onChange={e => setEditing({...editing, content: e.target.value})}/>
        </label>
        <div className="skill-editor-meta">
          <button type="button" className="btn secondary-btn" onClick={() => file.current?.click()}>Import .md file</button>
          <input ref={file} type="file" accept=".md,.markdown,.txt,text/markdown,text/plain" hidden onChange={importFile}/>
          <span className={`char-count ${length > LIMIT * 0.9 ? 'near' : ''}`}>{length.toLocaleString()} / {LIMIT.toLocaleString()}</span>
        </div>
        {shareGroups.length > 0 && (
          <fieldset className="skill-share">
            <legend>Share with</legend>
            {shareGroups.map(g => (
              <label key={g} className="skill-share-option">
                <input type="checkbox" checked={editing.shared_groups.includes(g)} onChange={() => toggleGroup(g)}/>
                {groupLabel(g)} <span className="muted">({g})</span>
              </label>
            ))}
            <p className="setting-desc">Members can use it from their Workflow menu but cannot change it. Your edits reach them on their next message.</p>
          </fieldset>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        <div className="skill-editor-actions">
          {editing.id && <button type="button" className="btn danger-btn" disabled={saving} onClick={remove}>Delete</button>}
          <span className="spacer"></span>
          <button type="button" className="btn secondary-btn" onClick={() => { setEditing(null); setError(''); }}>Cancel</button>
          <button type="submit" className="btn primary-btn" disabled={saving || !editing.name.trim() || !editing.content.trim()}>Save skill</button>
        </div>
      </form>
    );
  }

  return (
    <section className="settings-section">
      <div className="skills-heading">
        <h3>My skills</h3>
        <button className="btn primary-btn" onClick={() => open(null)}>New skill</button>
      </div>
      <p className="setting-desc">Your own workflows, saved on the harness. Pick one from a chat's Workflow menu, or set it as a project's workflow so every new chat in that project uses it. A skill shapes the answer; it cannot turn on tools.</p>
      {error && <p className="error" role="alert">{error}</p>}
      {!own.length && <p className="muted">No skills yet. Create one, or import a Markdown file.</p>}
      <ul className="skill-list">
        {own.map(s => (
          <li key={s.id}>
            <button className="skill-row" onClick={() => open(s)}>
              <span className="skill-name">{s.name}
                {s.shared_groups?.length > 0 && <span className="skill-badge">Shared with {s.shared_groups.map(groupLabel).join(', ')}</span>}
              </span>
              {s.summary && <span className="skill-summary">{s.summary}</span>}
            </button>
          </li>
        ))}
      </ul>
      {shared.length > 0 && <>
        <h3 className="skills-shared-heading">Shared with me</h3>
        <ul className="skill-list">
          {shared.map(s => (
            <li key={s.id}>
              <button className="skill-row" onClick={() => open(s)}>
                <span className="skill-name">{s.name}<span className="skill-badge">From {s.shared_by}</span></span>
                {s.summary && <span className="skill-summary">{s.summary}</span>}
              </button>
            </li>
          ))}
        </ul>
      </>}
    </section>
  );
}

export default SkillsPanel;
