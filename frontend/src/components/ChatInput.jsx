import React, { useState, useRef, useLayoutEffect } from 'react';
import '../styles/ChatInput.css';

// While a reply is streaming, the send button becomes a Stop button and the
// textarea is disabled so the user can't fire overlapping requests.
function ChatInput({ onSendMessage, onStop, isStreaming = false }) {
  const [text, setText] = useState('');
  const input = useRef(null);

  // Grow with the draft up to the CSS max-height, then scroll.
  useLayoutEffect(() => {
    const el = input.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  }, [text]);
  const handleSubmit = (e) => {
    e.preventDefault();
    if (isStreaming) return;
    if (text.trim()) {
      onSendMessage(text);
      setText('');
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <form className="chat-input-form glass-panel" onSubmit={handleSubmit}>
      <textarea
        ref={input}
        aria-label="Message"
        className="text-input"
        placeholder={isStreaming ? 'Waiting for response…' : 'Send a message...'}
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
          className={`action-btn send-btn ${text.trim() ? 'active' : ''}`}
          disabled={!text.trim()}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="22" y1="2" x2="11" y2="13"></line>
            <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
          </svg>
        </button>
      )}
    </form>
  );
}

export default ChatInput;
