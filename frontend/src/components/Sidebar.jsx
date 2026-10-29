import React, {useEffect, useState} from 'react';
import '../styles/Sidebar.css';

const ChatIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
  </svg>
);

function ChatItem({s, active, busy, onSelect, nested}) {
  return (
    <button className={`chat-item ${nested ? 'nested' : ''} ${s.id === active ? 'active' : ''}`} disabled={busy} onClick={() => onSelect(s)}
      aria-current={s.id === active ? 'page' : undefined}>
      <ChatIcon/>
      <span className="chat-item-text">
        <span className="chat-item-title">{s.title}</span>
        <span className="chat-item-profile">{s.profile}</span>
      </span>
    </button>
  );
}

// Projects are folders of chats; a chat whose project no longer exists shows under Chats.
function Sidebar({account, sessions, projects, active, activeProject, busy, onNewChat, onSelect, onEditProject, onOpenSettings, onDisconnect}) {
  const [open, setOpen] = useState(() => new Set());
  const known = new Set(projects.map(p => p.id));
  const loose = sessions.filter(s => !known.has(s.project_id));

  // Keep the folder of the chat you are in expanded.
  useEffect(() => { if (activeProject) setOpen(o => o.has(activeProject) ? o : new Set([...o, activeProject])); }, [activeProject]);

  function toggle(id) {
    setOpen(o => { const n = new Set(o); n.has(id) ? n.delete(id) : n.add(id); return n; });
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <button className="new-chat-btn" onClick={() => onNewChat(null)} disabled={busy}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
          New Chat
        </button>
      </div>

      <nav className="sidebar-content" aria-label="Projects and conversations">
        <div className="list-heading">
          <h2 className="list-title">Projects</h2>
          <button className="list-action" title="New project" aria-label="New project" disabled={busy} onClick={() => onEditProject(null)}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
          </button>
        </div>
        {!projects.length && <p className="empty-history">Group chats by class or topic, each with its own default tools.</p>}
        <div className="project-list">
          {projects.map(p => {
            const chats = sessions.filter(s => s.project_id === p.id);
            const expanded = open.has(p.id);
            return (
              <div key={p.id} className="project-group">
                <div className={`project-row ${activeProject === p.id ? 'current' : ''}`}>
                  <button className="project-toggle" aria-expanded={expanded} onClick={() => toggle(p.id)}>
                    <svg className={`chevron ${expanded ? 'open' : ''}`} width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <polyline points="9 6 15 12 9 18"></polyline>
                    </svg>
                    <svg className="folder" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                    </svg>
                    <span className="project-name">{p.name}</span>
                    <span className="project-count">{chats.length || ''}</span>
                  </button>
                  <button className="row-action" title={`New chat in ${p.name}`} aria-label={`New chat in ${p.name}`} disabled={busy} onClick={() => onNewChat(p.id)}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line>
                    </svg>
                  </button>
                  <button className="row-action" title={`Edit ${p.name}`} aria-label={`Edit ${p.name}`} disabled={busy} onClick={() => onEditProject(p)}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M12 20h9"></path><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"></path>
                    </svg>
                  </button>
                </div>
                {expanded && (
                  <div className="chat-list nested-list">
                    {chats.map(s => <ChatItem key={s.id} s={s} active={active} busy={busy} onSelect={onSelect} nested/>)}
                    {!chats.length && <p className="empty-history nested">No chats yet.</p>}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <h2 className="list-title chats-title">Chats</h2>
        {!loose.length && <p className="empty-history">{sessions.length ? 'Every chat is in a project.' : 'Your conversations will appear here.'}</p>}
        <div className="chat-list">
          {loose.map(s => <ChatItem key={s.id} s={s} active={active} busy={busy} onSelect={onSelect}/>)}
        </div>
      </nav>

      <div className="sidebar-footer">
        <p className="shared-note">{account
          ? `Signed in as ${account.name || account.email}. Your chats are saved on the harness and only you can see them.`
          : 'Chats are saved on the harness. Anyone signed in with the same access key shares this history.'}</p>
        <button className="settings-btn" onClick={onOpenSettings}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="3"></circle>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
          </svg>
          Settings
        </button>
        <button className="settings-btn" onClick={onDisconnect} disabled={busy}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
            <polyline points="16 17 21 12 16 7"></polyline>
            <line x1="21" y1="12" x2="9" y2="12"></line>
          </svg>
          Sign out
        </button>
      </div>
    </aside>
  );
}

export default Sidebar;
