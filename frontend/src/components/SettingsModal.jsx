import React, {useEffect, useState} from 'react';
import {identity as getIdentity, currentSession} from '../client';
import '../styles/SettingsModal.css';

// Read-only view of what the harness grants this credential. Policy is
// server-owned, so nothing here changes permissions or generation settings.
function SettingsModal({catalog, onDisconnect, onClose}) {
  const [tab, setTab] = useState('connection');
  const [who, setWho] = useState(null);
  const [session, setSession] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    Promise.all([getIdentity(), currentSession()]).then(([id, s]) => { if (live) { setWho(id); setSession(s); } }, e => live && setError(e.message));
    return () => { live = false; };
  }, []);

  useEffect(() => {
    const onKey = e => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" role="dialog" aria-modal="true" aria-labelledby="settings-title" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2 id="settings-title">Settings</h2>
          <button className="close-btn" aria-label="Close settings" onClick={onClose}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        <div className="modal-body">
          <div className="settings-sidebar" role="tablist">
            <button role="tab" aria-selected={tab === 'connection'} className={`tab-btn ${tab === 'connection' ? 'active' : ''}`} onClick={() => setTab('connection')}>Connection</button>
            <button role="tab" aria-selected={tab === 'profiles'} className={`tab-btn ${tab === 'profiles' ? 'active' : ''}`} onClick={() => setTab('profiles')}>Profiles</button>
          </div>

          <div className="settings-content">
            {tab === 'connection' && (
              <section className="settings-section">
                <h3>Harness identity</h3>
                <p className="setting-desc">Signed in with a browser session cookie. The key itself is not stored in the page. Activity keeps the session alive until the maximum lifetime.</p>
                {error && <p className="error" role="alert">{error}</p>}
                {!who && !error && <p className="muted">Loading…</p>}
                {who && (
                  <dl className="settings-list">
                    <dt>Identity</dt><dd>{who.kind} · {who.actor_id}</dd>
                    {session && <><dt>Idle timeout</dt><dd>{formatDuration(session.idle_timeout_seconds)} without activity</dd>
                    <dt>Session ends</dt><dd>{new Date(session.expires_at * 1000).toLocaleString()} at the latest</dd></>}
                    {who.expires_at && <><dt>Token expires</dt><dd>{new Date(who.expires_at * 1000).toLocaleString()}</dd></>}
                    <dt>Memory scopes</dt><dd>{who.memory_scopes?.length ? who.memory_scopes.join(', ') : 'None'}</dd>
                  </dl>
                )}
                <button className="btn secondary-btn" onClick={onDisconnect}>Disconnect</button>
              </section>
            )}

            {tab === 'profiles' && (
              <section className="settings-section">
                <h3>Available profiles</h3>
                <p className="setting-desc">Prompts, sampling, memory and tools are configured on the harness in profiles.yaml.</p>
                <dl className="settings-list">
                  {catalog.map(p => (
                    <React.Fragment key={p.id}>
                      <dt>{p.id}</dt>
                      <dd>
                        {p.skills.length ? `Workflows: ${p.skills.join(', ')}` : 'No workflows'}
                        {p.server_tools?.length ? <><br/>Harness tools: {p.server_tools.join(', ')}</> : null}
                      </dd>
                    </React.Fragment>
                  ))}
                </dl>
              </section>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function formatDuration(seconds) {
  const hours = seconds / 3600;
  return hours >= 1 ? `${+hours.toFixed(1)} hour${hours === 1 ? '' : 's'}` : `${Math.round(seconds / 60)} minutes`;
}

export default SettingsModal;
