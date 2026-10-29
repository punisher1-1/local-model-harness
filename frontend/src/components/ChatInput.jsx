import React, { useState, useRef, useLayoutEffect } from 'react';
import { convertDocument, digestDocument, newId } from '../client';
import '../styles/ChatInput.css';

const MAX_FILES = 5;
const DEFAULT_ASK = 'Summarize the attached document.';

// While a reply is streaming, the send button becomes a Stop button and the
// textarea is disabled so the user can't fire overlapping requests.
// Documents are converted to text as soon as they are attached, so the chip shows
// progress and size before anything is sent.
function ChatInput({ onSendMessage, onStop, isStreaming = false, profile, docs }) {
  const [text, setText] = useState('');
  const [files, setFiles] = useState([]); // {id, name, state: converting|digesting|ready|error, …}
  const [dragging, setDragging] = useState(false);
  const input = useRef(null);
  const picker = useRef(null);
  const canAttach = docs?.types?.length > 0 && !!profile;

  // Grow with the draft up to the CSS max-height, then scroll.
  useLayoutEffect(() => {
    const el = input.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  }, [text]);

  const update = (id, change) => setFiles(list => list.map(f => f.id === id ? {...f, ...change} : f));

  // Every picked file gets a chip at once; conversions then run one at a time so a batch
  // never floods the converter.
  async function attach(picked) {
    const room = Math.max(MAX_FILES - files.length, 0);
    const entries = [...picked].slice(0, room).map(file => {
      const suffix = file.name.includes('.') ? '.' + file.name.split('.').pop().toLowerCase() : '';
      const error = !docs.types.includes(suffix) ? `Can't read ${suffix || 'this'} files; use ${docs.types.join(' ')}`
        : file.size > docs.max_bytes ? `Larger than ${Math.round(docs.max_bytes / 1048576)} MB` : '';
      return {file, chip: {id: newId(), name: file.name, state: error ? 'error' : 'queued', error}};
    });
    const extra = picked.length > room ? [{id: newId(), name: `${picked.length - room} more`, state: 'error', error: `Up to ${MAX_FILES} documents per message`}] : [];
    setFiles(list => [...list, ...entries.map(e => e.chip), ...extra]);
    for (const {file, chip} of entries.filter(e => e.chip.state === 'queued')) {
      update(chip.id, {state: 'converting'});
      try {
        const doc = await convertDocument(file, profile);
        update(chip.id, {state: 'ready', ...doc});
      } catch (e) { update(chip.id, {state: 'error', error: e.message}); }
    }
  }

  async function digest(file) {
    update(file.id, {state: 'digesting', part: 0, of: 0});
    try {
      const doc = await digestDocument(file, profile, e => e.part && update(file.id, {part: e.part, of: e.of}));
      update(file.id, {state: 'ready', ...doc});
    } catch (e) { update(file.id, {state: 'ready', error: e.message}); }
  }

  const ready = files.filter(f => f.state === 'ready');
  const waiting = files.some(f => ['queued', 'converting', 'digesting'].includes(f.state));
  const tooLong = ready.some(f => !f.fits);
  const canSend = !isStreaming && !waiting && !tooLong && (text.trim() || ready.length > 0);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!canSend) return;
    const attachments = ready.map(({name, text: body, chars, tokens, digest: isDigest}) => ({name, text: body, chars, tokens, digest: !!isDigest}));
    onSendMessage(text.trim() ? text : DEFAULT_ASK, attachments);
    setText(''); setFiles([]);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const drop = canAttach && !isStreaming ? {
    onDragOver: e => { e.preventDefault(); setDragging(true); },
    onDragLeave: () => setDragging(false),
    onDrop: e => { e.preventDefault(); setDragging(false); attach(e.dataTransfer.files); },
  } : {};

  return (
    <form className={`chat-input-form glass-panel ${files.length ? 'has-files' : ''} ${dragging ? 'dragging' : ''}`} onSubmit={handleSubmit} {...drop}>
      {files.length > 0 && (
        <ul className="attachment-list" aria-label="Attached documents">
          {files.map(f => (
            <li key={f.id} className={`attachment-chip ${f.state} ${f.state === 'ready' && !f.fits ? 'too-long' : ''}`}>
              <span className="attachment-name" title={f.name}>{f.name}</span>
              <span className="attachment-info">
                {f.state === 'queued' && 'Queued'}
                {f.state === 'converting' && <><span className="working-dots" aria-hidden="true"><span></span><span></span><span></span></span>Converting…</>}
                {f.state === 'digesting' && <><span className="working-dots" aria-hidden="true"><span></span><span></span><span></span></span>{f.of ? `Summarizing part ${f.part} of ${f.of}…` : 'Preparing…'}</>}
                {f.state === 'ready' && `${f.digest ? 'Digest · ' : ''}~${f.tokens?.toLocaleString()} tokens`}
                {f.state === 'error' && <span className="attachment-error">{f.error}</span>}
              </span>
              {f.state === 'ready' && !f.fits && (
                <span className="attachment-warn">Too long for this chat.
                  <button type="button" className="link-btn" onClick={() => digest(f)}>Summarize in sections</button>
                </span>
              )}
              {f.state === 'ready' && f.error && <span className="attachment-error">{f.error}</span>}
              {f.state === 'ready' && f.partial && <span className="attachment-warn">Some pages could not be read.</span>}
              {(f.state === 'ready' || f.state === 'error') && (
                <button type="button" className="attachment-remove" aria-label={`Remove ${f.name}`} onClick={() => setFiles(list => list.filter(x => x.id !== f.id))}>×</button>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="chat-input-row">
        {canAttach && (
          <>
            <button type="button" className="action-btn attach-btn" title="Attach a document" aria-label="Attach a document"
              disabled={isStreaming || files.length >= MAX_FILES} onClick={() => picker.current?.click()}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>
              </svg>
            </button>
            <input ref={picker} type="file" multiple hidden accept={docs.types.join(',')}
              onChange={e => { attach(e.target.files); e.target.value = ''; }}/>
          </>
        )}
        <textarea
          ref={input}
          aria-label="Message"
          className="text-input"
          placeholder={isStreaming ? 'Waiting for response…' : ready.length ? 'Optional question…' : 'Send a message...'}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          rows="1"
          disabled={isStreaming}
        />

        {isStreaming ? (
          <button
            type="button"
            className="action-btn stop-btn active"
            title="Stop generating"
            onClick={onStop}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" stroke="none">
              <rect x="6" y="6" width="12" height="12" rx="2"></rect>
            </svg>
          </button>
        ) : (
          <button
            type="submit"
            aria-label="Send message"
            className={`action-btn send-btn ${canSend ? 'active' : ''}`}
            disabled={!canSend}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13"></line>
              <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
          </button>
        )}
      </div>
    </form>
  );
}

export default ChatInput;
