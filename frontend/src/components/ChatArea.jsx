import React, {useEffect, useRef} from 'react';
import MessageBubble from './MessageBubble';
import ChatInput from './ChatInput';
import '../styles/ChatArea.css';

// Profiles lock after the first message; a new chat is needed to switch.
// The workflow and tool choices stick to the chat: the workflow is sent as
// `/skill <id>` on every turn, and tools as the X-Harness-MCP header.
function ChatArea({session, profile, catalog, selected, onSelectProfile, skill, onSelectSkill, mcp, onToggleMcp, busy, error, onSend, onStop, onDelete, onRetrySave, onError}) {
  const end = useRef(null);
  const info = id => profile?.skill_info?.find(s => s.id === id);
  const workflow = info(skill || profile?.default_skill);
  const servers = profile?.mcp_servers || [];
  const enabled = servers.filter(s => mcp.includes(s.id));
  useEffect(() => { end.current?.scrollIntoView({block: 'nearest'}); }, [session?.messages]);

  return (
    <main className="chat-area">
      <div className="chat-header">
        <h2 className="chat-header-title">{session?.title || 'New Chat'}</h2>
        <div className="chat-controls">
          <label>Profile
            <select value={selected} disabled={busy || !!session} onChange={e => onSelectProfile(e.target.value)}>
              {catalog.map(p => <option key={p.id} value={p.id}>{p.id}</option>)}
            </select>
          </label>
          <label>Workflow
            <select value={skill} disabled={busy} onChange={e => onSelectSkill(e.target.value)}>
              <option value="">Automatic{profile?.default_skill ? ` · ${info(profile.default_skill)?.title || profile.default_skill}` : ''}</option>
              {profile?.skills.map(s => <option key={s} value={s}>{info(s)?.title || s}</option>)}
            </select>
          </label>
          {session && (
            <button className="icon-btn" title="Delete chat" aria-label="Delete chat" disabled={busy} onClick={onDelete}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>
                <path d="M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path>
              </svg>
            </button>
          )}
        </div>
      </div>

      {(servers.length > 0 || workflow?.description) && (
        <div className="chat-options">
          {servers.length > 0 && (
            <div className="tool-toggles" role="group" aria-label="Harness tools for this chat">
              <span className="options-label">Tools</span>
              {servers.map(s => (
                <button key={s.id} className={`tool-chip ${mcp.includes(s.id) ? 'on' : ''}`} aria-label={s.label} aria-pressed={mcp.includes(s.id)} disabled={busy}
                  title={`${s.description}\nTools: ${s.tools.join(', ')}`} onClick={() => onToggleMcp(s.id)}>
                  <span className="tool-dot" aria-hidden="true"></span>{s.label}
                </button>
              ))}
            </div>
          )}
          {workflow?.description && <p className="workflow-desc"><span className="options-label">{skill ? 'Workflow' : 'Default workflow'}</span>{workflow.description}</p>}
        </div>
      )}

      <div className="messages-container" aria-busy={busy}>
        <div className="messages-list">
          {!session && (
            <div className="empty-state">
              <div className="eyebrow">Ready when you are</div>
              <h1>What are we working on?</h1>
              <p>Choose a profile and start a conversation. Workflows come from the harness.</p>
              <p className="empty-note">
                {enabled.length ? `Tools on: ${enabled.map(s => s.label).join(', ')}. Tool activity appears with the answer.`
                  : servers.length ? 'Harness tools are off for this chat. Turn them on above.' : 'This profile has no harness tools.'}
              </p>
            </div>
          )}
          {session?.messages?.map(m => <MessageBubble key={m.id} message={m} onCopyFailed={() => onError('Copy is unavailable here. Select the answer text to copy it.')}/>)}
          <div ref={end}/>
        </div>
      </div>

      <div className="input-container">
        {session?.unsaved && !busy && (
          <div className="save-status" role="status">
            This chat has unsaved changes.
            <button disabled={busy} onClick={onRetrySave}>Retry save</button>
          </div>
        )}
        {error && <div className="chat-error" role="alert">{error}</div>}
        <ChatInput onSendMessage={onSend} onStop={onStop} isStreaming={busy}/>
      </div>
    </main>
  );
}

export default ChatArea;
