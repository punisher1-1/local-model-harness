import React from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import '../styles/MessageBubble.css';

// Remote images are never loaded; links open outside the app without a referrer.
const markdownComponents = {
  img: ({alt}) => <span>[Image: {alt || 'not loaded'}]</span>,
  a: ({children, href}) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
};

// While tools run, show the newest reasoning step instead of a generic wait message.
function latestStep(reasoning) {
  const lines = (reasoning || '').split('\n').map(l => l.trim()).filter(Boolean);
  const last = lines.at(-1) || '';
  return last.length > 140 ? last.slice(0, 137) + '…' : last;
}

function MessageBubble({message: m, onCopyFailed}) {
  const isUser = m.role === 'user';

  async function copy() {
    try { await navigator.clipboard.writeText(m.content); } catch { onCopyFailed(); }
  }

  return (
    <div className={`message-wrapper ${isUser ? 'user' : 'ai'}`}>
      {!isUser && (
        <div className="avatar ai-avatar" aria-hidden="true">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="4" y="4" width="16" height="16" rx="3"></rect>
            <rect x="9" y="9" width="6" height="6"></rect>
            <path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"></path>
          </svg>
        </div>
      )}

      <article className="message-content" aria-label={isUser ? 'You' : 'Assistant'}>
        {m.skill && <div className="message-skill">{m.skill}</div>}
        {m.reasoning && <details><summary>Reasoning</summary><pre>{m.reasoning}</pre></details>}
        {isUser ? <p className="user-text">{m.content}</p> : (
          <div className={`markdown ${m.status === 'running' && m.content ? 'streaming' : ''}`}>
            <Markdown remarkPlugins={[remarkGfm]} skipHtml components={markdownComponents}>{m.content}</Markdown>
          </div>
        )}
        {m.status === 'running' && !m.content && <p className="muted working">{latestStep(m.reasoning) || 'Waiting for answer…'}</p>}
        {m.finish === 'length' && <p role="status" className="muted">Output limit reached; this answer may be incomplete.</p>}
        {m.error && <p className="error" role="alert">{m.error}</p>}
        {(m.meta?.context === 'compacted' || m.usage || (!isUser && m.content && m.status !== 'running')) && (
          <div className="message-meta">
            {m.meta?.context === 'compacted' && <span>Earlier context was compacted.</span>}
            {m.usage && <span>Input {m.usage.prompt_tokens?.toLocaleString()} · Output {m.usage.completion_tokens?.toLocaleString()} · Total {m.usage.total_tokens?.toLocaleString()}</span>}
            {!isUser && m.content && m.status !== 'running' && <button className="copy" onClick={copy}>Copy</button>}
          </div>
        )}
      </article>

      {isUser && (
        <div className="avatar user-avatar" aria-hidden="true">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
            <circle cx="12" cy="7" r="4"></circle>
          </svg>
        </div>
      )}
    </div>
  );
}

export default MessageBubble;
