import React, {useEffect, useState} from 'react';
import {adminAccounts, groupLabel} from '../client';

// Recent activity within this window counts as active now; otherwise a live session is idle.
const ACTIVE_SECONDS = 300;
const REFRESH_MS = 30000;

// Who has an account on this harness and who is signed in now (admin grant only).
// Sessions live in harness memory, so after a restart everyone shows as signed out.
function AccountsPanel() {
  const [list, setList] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function load() {
    setBusy(true);
    try { setList(await adminAccounts()); setError(''); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, []);

  const rows = list?.data || [];
  const signedIn = rows.filter(r => r.sessions > 0).length;
  return (
    <section className="settings-section accounts-panel">
      <div className="skills-heading">
        <h3>Accounts</h3>
        <button type="button" className="btn secondary-btn" disabled={busy} onClick={load}>Refresh</button>
      </div>
      <p className="setting-desc">
        Everyone who has signed in with the identity provider. Active means a request in the last {ACTIVE_SECONDS / 60} minutes;
        a signed-in session ends after {list ? formatIdle(list.idle_timeout_seconds) : 'the idle timeout'} without activity. A harness restart signs everyone out.
      </p>
      {error && <p className="error" role="alert">{error}</p>}
      {!list && !error && <p className="muted">Loading…</p>}
      {list && <p className="muted" role="status">{rows.length} account{rows.length === 1 ? '' : 's'} · {signedIn} signed in
        {list.key_sessions > 0 && ` · ${list.key_sessions} access-key session${list.key_sessions === 1 ? '' : 's'}`}</p>}
      {list && !rows.length && <p className="muted">No one has signed in with the identity provider yet.</p>}
      <ul className="memory-list">
        {rows.map(r => {
          const state = presence(r);
          return (
            <li key={r.email || r.name} className="memory-row account-row">
              <div className="account-name">
                <span className={`presence presence-${state.id}`} aria-hidden="true"/>
                <strong>{r.name || r.email || 'Unnamed account'}</strong>
                {r.you && <span className="skill-badge">You</span>}
                {!r.has_access && <span className="skill-badge account-warn">No access</span>}
              </div>
              {r.name && r.email && <p className="account-email">{r.email}</p>}
              <div className="memory-meta">
                <span>{state.label}</span>
                {r.groups.map(g => <span key={g} className="skill-badge" title={g}>{groupLabel(g)}</span>)}
              </div>
              <div className="memory-meta">
                <span>Last sign-in {when(Date.parse(r.last_sign_in))}</span>
                <span>Account since {new Date(r.first_seen).toLocaleDateString()}</span>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function presence(r) {
  if (!r.sessions) return {id: 'off', label: 'Signed out'};
  const quiet = Date.now() / 1000 - r.last_active;
  const devices = r.sessions > 1 ? ` on ${r.sessions} browsers` : '';
  return quiet < ACTIVE_SECONDS ? {id: 'active', label: `Active now${devices}`}
    : {id: 'idle', label: `Signed in${devices}, idle since ${when(r.last_active * 1000)}`};
}

function when(ms) {
  const minutes = Math.round((Date.now() - ms) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 24 * 60) return `${Math.round(minutes / 60)} h ago`;
  return new Date(ms).toLocaleString();
}

function formatIdle(seconds) {
  const hours = seconds / 3600;
  return hours >= 1 ? `${+hours.toFixed(1)} hours` : `${Math.round(seconds / 60)} minutes`;
}

export default AccountsPanel;
