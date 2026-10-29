import React, {useEffect, useState} from 'react';
import {newId} from '../client';
import WorkflowSelect from './WorkflowSelect';
import '../styles/SettingsModal.css';
import '../styles/ProjectModal.css';

// Create or edit a project: its name and the profile, workflow and tools a new chat
// in it starts with. Each chat can still change its own workflow and tools.
function ProjectModal({project, catalog, userSkills, defaultProfile, onSave, onDelete, onClose}) {
  const start = catalog.find(p => p.id === project?.profile) || catalog.find(p => p.id === defaultProfile) || catalog[0];
  const [name, setName] = useState(project?.name || '');
  const [profileId, setProfileId] = useState(start?.id || '');
  const [skill, setSkill] = useState(project?.skill || '');
  const [mcp, setMcp] = useState(project ? project.mcp_servers : (start?.mcp_servers || []).filter(s => s.default).map(s => s.id));
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const profile = catalog.find(p => p.id === profileId);
  const servers = profile?.mcp_servers || [];
  const info = id => profile?.skill_info?.find(s => s.id === id);

  useEffect(() => {
    const onKey = e => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Switching profile resets the workflow and tools to that profile's own defaults.
  function chooseProfile(id) {
    const next = catalog.find(p => p.id === id);
    setProfileId(id); setSkill(s => s.startsWith('user:') ? s : '');
    setMcp((next?.mcp_servers || []).filter(s => s.default).map(s => s.id));
  }

  function toggle(id) {
    setMcp(list => list.includes(id) ? list.filter(s => s !== id) : [...list, id]);
  }

  async function submit(e) {
    e.preventDefault();
    setSaving(true); setError('');
    try {
      await onSave(project?.id || newId(), {name: name.trim(), profile: profileId, skill,
        mcp_servers: servers.map(s => s.id).filter(id => mcp.includes(id))});
    } catch (err) { setError(err.message); setSaving(false); }
  }

  async function remove() {
    setSaving(true); setError('');
    try { await onDelete(project.id); } catch (err) { setError(err.message); setSaving(false); }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <form className="modal-content project-modal" role="dialog" aria-modal="true" aria-labelledby="project-title"
        onClick={e => e.stopPropagation()} onSubmit={submit}>
        <div className="modal-header">
          <h2 id="project-title">{project ? 'Edit project' : 'New project'}</h2>
          <button type="button" className="close-btn" aria-label="Close" onClick={onClose}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        <div className="project-form">
          <label className="field">Name
            <input value={name} maxLength={80} required autoFocus placeholder="IT301" onChange={e => setName(e.target.value)}/>
          </label>
          <label className="field">Profile
            <select value={profileId} onChange={e => chooseProfile(e.target.value)}>
              {catalog.map(p => <option key={p.id} value={p.id}>{p.id}</option>)}
            </select>
          </label>
          <label className="field">Workflow
            <WorkflowSelect profile={profile} userSkills={userSkills} value={skill} onChange={setSkill}/>
          </label>
          <fieldset className="field">
            <legend>Tools on for new chats</legend>
            {servers.length ? (
              <div className="tool-toggles">
                {servers.map(s => (
                  <button type="button" key={s.id} className={`tool-chip ${mcp.includes(s.id) ? 'on' : ''}`} aria-label={s.label} aria-pressed={mcp.includes(s.id)}
                    title={s.description} onClick={() => toggle(s.id)}>
                    <span className="tool-dot" aria-hidden="true"></span>{s.label}
                  </button>
                ))}
              </div>
            ) : <p className="setting-desc">This profile has no harness tools.</p>}
          </fieldset>
          <p className="setting-desc">These are the starting point for each new chat in this project. Change a chat's tools anytime from its Tools row.</p>
          {error && <p className="error" role="alert">{error}</p>}
        </div>

        <div className="modal-footer">
          {project && <button type="button" className="btn danger-btn" disabled={saving} onClick={remove}>Delete project</button>}
          <span className="spacer"></span>
          <button type="button" className="btn secondary-btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary-btn" disabled={saving || !name.trim() || !profileId}>{project ? 'Save' : 'Create project'}</button>
        </div>
      </form>
    </div>
  );
}

export default ProjectModal;
