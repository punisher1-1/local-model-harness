import React, {useEffect, useRef, useState} from 'react';
import {copyText} from '../client';

// A small Copy button that confirms with "Copied" (or says it failed) for a moment.
function CopyButton({text, className = 'copy', label = 'Copy'}) {
  const [state, setState] = useState('idle');
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);

  async function copy() {
    const ok = await copyText(typeof text === 'function' ? text() : text);
    setState(ok ? 'copied' : 'failed');
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setState('idle'), ok ? 1500 : 3000);
  }

  return (
    <button type="button" className={`${className} ${state}`} onClick={copy} aria-live="polite">
      {state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy failed' : label}
    </button>
  );
}

export default CopyButton;
