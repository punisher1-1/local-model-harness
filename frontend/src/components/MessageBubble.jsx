import React from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import CopyButton from './CopyButton';
import {nodeText} from '../client';
import '../styles/MessageBubble.css';

// Remote images are never loaded; links open outside the app without a referrer.
// Code blocks get their own Copy button.
const markdownComponents = {
  img: ({alt}) => <span>[Image: {alt || 'not loaded'}]</span>,
  a: ({children, href}) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
  pre: ({node, children}) => {
    const language = (node?.children?.[0]?.properties?.className || [])
      .map(String).find(c => c.startsWith('language-'))?.slice(9);
    return (
      <div className="code-block">
        <div className="code-header">
          <span>{language || 'code'}</span>
          <CopyButton className="copy code-copy" text={() => nodeText(node).replace(/\n$/, '')}/>
        </div>
        <pre>{children}</pre>
      </div>
    );
  },
};

// What went wrong in a run, in the words the activity line uses.
function runFlags(r) {
  if (r.error) return [r.error];
  return [r.exit_code !== 0 && `exit ${r.exit_code ?? '?'}`, r.timed_out && 'timed out',
    (r.truncated || r.output_limit) && 'output truncated'].filter(Boolean);
}

// The exact scripts the sandbox ran for this answer and what it returned, to check the
// answer's code and PRINTED blocks against.
function PythonRuns({runs}) {
  const failed = runs.filter(r => runFlags(r).length).length;
  return (
    <details className="python-runs">
      <summary>Python runs ({runs.length}){failed ? ` · ${failed} with problems` : ''}</summary>
      {runs.map((r, i) => {
        const flags = runFlags(r);
        return (
          <section key={i} className="python-run">
            <div className="python-run-head">
              <span>Run {i + 1} · {flags.length ? <span className="run-problem">{flags.join(', ')}</span> : 'exit 0'}</span>
              <CopyButton className="copy code-copy" text={r.code}/>
            </div>
            <pre>{r.code}</pre>
            {r.stdout ? <><div className="python-run-label">Output</div><pre>{r.stdout}</pre></> : !r.error && <div className="python-run-label">No output</div>}
            {r.stderr && <><div className="python-run-label">Errors</div><pre className="run-stderr">{r.stderr}</pre></>}
          </section>
        );
      })}
    </details>
  );
}

// While tools run, show the newest reasoning step instead of a generic wait message.
function latestStep(reasoning) {
  const lines = (reasoning || '').split('\n').map(l => l.trim()).filter(Boolean);
  const last = lines.at(-1) || '';
  return last.length > 140 ? last.slice(0, 137) + '…' : last;
}

function MessageBubble({message: m, skillLabel, busy, onResend}) {
  const isUser = m.role === 'user';

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
        {m.skill && <div className="message-skill">{skillLabel || m.skill}</div>}
        {m.reasoning && <details><summary>Reasoning</summary><pre>{m.reasoning}</pre></details>}
        {isUser ? <>
          {m.attachments?.length > 0 && (
            <ul className="message-attachments">
              {m.attachments.map((a, i) => (
                <li key={i}>
                  <details>
                    <summary>{a.name} · {a.digest ? 'digest · ' : ''}~{a.tokens?.toLocaleString() ?? '?'} tokens</summary>
                    <pre>{a.text.length > 4000 ? a.text.slice(0, 4000) + '\n…' : a.text}</pre>
                  </details>
                </li>
              ))}
            </ul>
          )}
          <p className="user-text">{m.content}</p>
          <div className="user-actions">
            <CopyButton className="copy user-copy" text={m.content}/>
            {onResend && <button type="button" className="copy user-copy" disabled={busy} onClick={() => onResend(m)}
              title="Send this question again as a new message">Resend</button>}
          </div>
        </> : (
          <div className={`markdown ${m.status === 'running' && m.content ? 'streaming' : ''}`}>
            <Markdown remarkPlugins={[remarkGfm]} skipHtml components={markdownComponents}>{m.content}</Markdown>
          </div>
        )}
        {!isUser && m.runs?.length > 0 && <PythonRuns runs={m.runs}/>}
        {m.status === 'running' && !m.content && (
          // The dots keep moving even when no new step arrives, such as during a slow tool call.
          <p className="muted working"><span className="working-dots" aria-hidden="true"><span></span><span></span><span></span></span>{latestStep(m.reasoning) || 'Waiting for answer…'}</p>
        )}
        {m.finish === 'length' && <p role="status" className="muted">Output limit reached; this answer may be incomplete.</p>}
        {m.error && <p className="error" role="alert">{m.error}</p>}
        {(m.meta?.context === 'compacted' || m.usage || (!isUser && m.content && m.status !== 'running')) && (
          <div className="message-meta">
            {m.meta?.context === 'compacted' && <span>Earlier context was compacted.</span>}
            {m.usage && <span>Input {m.usage.prompt_tokens?.toLocaleString()} · Output {m.usage.completion_tokens?.toLocaleString()} · Total {m.usage.total_tokens?.toLocaleString()}</span>}
            {!isUser && m.content && m.status !== 'running' && <CopyButton text={m.content}/>}
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
