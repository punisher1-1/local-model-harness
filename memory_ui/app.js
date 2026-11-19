"use strict";
const $ = id => document.getElementById(id);
let memoryScope = "legacy";
let token = "", grants = [], cursor = null, pending = null, busy = false, generation = 0;
function status(text, error = false) { $("status").textContent = text; $("status").className = error ? "error" : ""; }
function uuid() { const a = crypto.getRandomValues(new Uint8Array(16)); a[6] = (a[6] & 15) | 64; a[8] = (a[8] & 63) | 128; const h = [...a].map(x => x.toString(16).padStart(2,"0")).join(""); return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`; }
async function api(path, method = "GET", body) {
  const response = await fetch(path, {method, cache:"no-store", redirect:"error", credentials:"omit", headers:{"X-Harness-Memory-Scope":memoryScope, Authorization:`Bearer ${token}`, ...(body ? {"Content-Type":"application/json"} : {})}, body:body ? JSON.stringify(body) : undefined, signal:AbortSignal.timeout(20000)});
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.error?.message || `Request failed (${response.status})`); }
  return response.status === 204 ? null : response.json();
}
async function task(fn) { if (busy) return; busy = true; const version = generation; document.querySelectorAll("button").forEach(b => b.disabled = true); try { await fn(); } catch(e) { if (version === generation) status(e.message, true); } finally { busy = false; document.querySelectorAll("button").forEach(b => b.disabled = false); } }
function disconnect() { generation++; token = ""; grants = []; pending = null; cursor = null; $("workspace").hidden = true; $("login").hidden = false; $("credential").value = ""; $("save").reset(); $("query").value = ""; $("results").replaceChildren(); $("scope").textContent = ""; $("recall").textContent = ""; status("Disconnected. Credential and displayed memories cleared."); }
$("disconnect").onclick = disconnect;
window.addEventListener("pagehide", disconnect);
$("connect").onsubmit = e => { e.preventDefault(); task(async () => {
  token = $("credential").value.trim(); $("credential").value = "";
  try {
    const identity = await api("/v1/identity"); grants = identity.memory_permissions;
    $("memory-scope").replaceChildren();
    for (const scope of identity.memory_scopes || ["legacy"]) { const option = document.createElement("option"); option.value = scope; option.textContent = scope === "legacy" ? "legacy (existing memories)" : scope; $("memory-scope").append(option); }
    if ((identity.memory_scopes || ["legacy"]).includes("legacy")) $("memory-scope").value = "legacy";
    memoryScope = $("memory-scope").value || "legacy";
    $("scope").textContent = `Identity: ${identity.actor_id} · ${identity.kind} · Permissions: ${grants.join(", ") || "none"}`;
    $("writer").hidden = !grants.includes("memory.write"); $("reader").hidden = !grants.includes("memory.read");
    $("workspace").hidden = false; $("login").hidden = true;
    if (grants.includes("memory.read")) { const health = await api("/v1/memories/health"); $("recall").textContent = `Namespace: ${health.namespace} · Scope: ${health.scope}. Recall profiles: ${health.recall_profiles.join(", ") || "none"}. Automatic capture: off.`; await browse(false); }
    status("Connected. Access is enforced by the memory API.");
  } catch(e) { disconnect(); throw e; }
}); };
function render(rows) {
  for (const row of rows) {
    const article = document.createElement("article"), meta = document.createElement("p"), text = document.createElement("p");
    meta.className = "metadata"; meta.textContent = `${row.category} · ${new Date(row.created_at).toLocaleString()} · ${row.memory_id}${row.source_conversation_id ? " · Source: " + row.source_conversation_id : ""}`;
    text.className = "memory-text"; text.textContent = row.content; article.append(meta, text);
    if (grants.includes("memory.delete")) { const button = document.createElement("button"); button.textContent = "Delete memory"; button.className = "delete"; button.onclick = () => {
      if (!confirm(`Delete this saved memory? This cannot be undone. Existing chats retain their copies.\n\n${row.content.slice(0,400)}`)) return;
      task(async () => { await api(`/v1/memories/${encodeURIComponent(row.memory_id)}`, "DELETE"); article.remove(); status("Memory deleted. Start a fresh chat to check recall without earlier copies."); });
    }; article.append(button); }
    $("results").append(article);
  }
}
let activeQuery = "";
async function browse(more) {
  const query = more ? activeQuery : $("query").value.trim();
  const result = query ? await api("/v1/memories/search", "POST", {query,limit:50}) : await api(`/v1/memories?limit=20${more && cursor ? "&cursor=" + encodeURIComponent(cursor) : ""}`);
  if (!more) $("results").replaceChildren(); activeQuery = query; cursor = result.next_cursor || null;
  render(result.data); $("more").hidden = !cursor;
  $("results-info").textContent = query ? `${result.data.length} matches (up to 50). All search words must match; refine your query if needed.` : `${$("results").children.length} memories loaded, newest first.${cursor ? " More available." : " End of list."}`;
}
$("search").onsubmit = e => { e.preventDefault(); task(() => browse(false)); };
$("more").onclick = () => task(() => browse(true));
$("content").oninput = () => { $("bytes").textContent = `${new TextEncoder().encode($("content").value).length} / 8192 UTF-8 bytes`; };
$("save").onsubmit = e => { e.preventDefault(); task(async () => {
  const body = {content:$("content").value, category:$("category").value, source_conversation_id:$("source").value.trim() || null};
  if (!body.content.trim() || new TextEncoder().encode(body.content).length > 8192) throw new Error("Enter nonblank text, at most 8192 UTF-8 bytes.");
  const signature = JSON.stringify({scope:memoryScope,...body});
  if (pending && pending.signature !== signature) throw new Error("A previous save has an uncertain outcome. Restore the original text/category/reference and retry, or disconnect and check the list before starting another save.");
  if (!pending) pending = {signature, key:uuid()};
  status("Saving… If the request fails, retry unchanged to avoid duplicate saves.");
  await api("/v1/memories", "POST", {...body,idempotency_key:pending.key}); pending = null;
  $("save").reset(); $("content").oninput(); status("Memory saved. Retained until explicitly deleted.");
  if (grants.includes("memory.read")) { $("query").value = ""; await browse(false); }
}); };

$("memory-scope").onchange = () => {
  const next = $("memory-scope").value;
  if (busy || pending) { $("memory-scope").value = memoryScope; status("Finish or retry the pending operation before switching scope.", true); return; }
  if ($("content").value && !confirm("Discard this unsaved draft and switch memory scope?")) { $("memory-scope").value = memoryScope; return; }
  task(async () => {
    memoryScope = next; cursor = null; $("results").replaceChildren(); $("query").value = ""; $("save").reset(); $("content").oninput(); $("recall").textContent = "";
    if (grants.includes("memory.read")) {
      const health = await api("/v1/memories/health");
      $("recall").textContent = `Scope: ${health.memory_scope} · Recall profiles: ${health.recall_profiles.join(", ") || "none"}. Automatic capture: off.`;
      await browse(false);
    }
    status(`Active memory scope: ${memoryScope}.`);
  });
};
