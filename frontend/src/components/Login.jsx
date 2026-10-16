import React, {useState} from 'react';
import '../styles/Login.css';

function Login({onConnect, notice}) {
  const [credential, setCredential] = useState('');
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState('');

  async function submit(e) {
    e.preventDefault();
    setConnecting(true); setError('');
    try { await onConnect(credential.trim()); setCredential(''); }
    catch (err) { setError(err.message); }
    finally { setConnecting(false); }
  }

  return (
    <main className="login glass-panel">
      <div className="eyebrow">Your private workspace</div>
      <h1>Connect to your harness</h1>
      <p>Enter your harness API key or access token. The harness exchanges it for a browser session that survives reloads and ends when idle or when you disconnect.</p>
      {notice && <p className="login-notice" role="status">{notice}</p>}
      <form onSubmit={submit}>
        <label htmlFor="credential">Access credential</label>
        <input id="credential" type="password" autoComplete="off" value={credential} onChange={e => setCredential(e.target.value)} required/>
        <button disabled={connecting}>{connecting ? 'Connecting…' : 'Connect'}</button>
      </form>
      {error && <p role="alert">{error}</p>}
    </main>
  );
}

export default Login;
