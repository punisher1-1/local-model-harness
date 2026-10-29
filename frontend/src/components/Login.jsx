import React, {useState} from 'react';
import '../styles/Login.css';

// Sign in through the identity provider when the harness has one; the access key form
// stays available for setups without it, or as a fallback the admin can allow.
function Login({onConnect, notice, auth}) {
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

  const keyForm = (
    <form onSubmit={submit}>
      <label htmlFor="credential">Access credential</label>
      <input id="credential" type="password" autoComplete="off" value={credential} onChange={e => setCredential(e.target.value)} required/>
      <button disabled={connecting}>{connecting ? 'Connecting…' : 'Connect'}</button>
    </form>
  );

  if (auth?.oidc) {
    return (
      <main className="login glass-panel">
        <div className="eyebrow">Your private workspace</div>
        <h1>Sign in</h1>
        <p>Use your passkey with {auth.provider}. Your chats, projects and skills are your own, and you stay signed in until you sign out or are idle for a while.</p>
        {notice && <p className="login-notice" role="status">{notice}</p>}
        <a className="provider-btn" href="/v1/auth/login">Sign in with {auth.provider}</a>
        {auth.key_sign_in && (
          <details className="key-sign-in">
            <summary>Use an access key instead</summary>
            {keyForm}
          </details>
        )}
        {error && <p role="alert">{error}</p>}
      </main>
    );
  }

  return (
    <main className="login glass-panel">
      <div className="eyebrow">Your private workspace</div>
      <h1>Connect to your harness</h1>
      <p>Enter your harness API key or access token. The harness exchanges it for a browser session that survives reloads and ends when idle or when you disconnect.</p>
      {notice && <p className="login-notice" role="status">{notice}</p>}
      {keyForm}
      {error && <p role="alert">{error}</p>}
    </main>
  );
}

export default Login;
