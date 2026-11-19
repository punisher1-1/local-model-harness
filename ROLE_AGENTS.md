# Future role-scoped agents

Status: payroll/help desk scenarios are design notes. The identity/profile/tool
authorization scaffold is now implemented; see IDENTITY.md for its boundaries.
The payroll/help desk designs remain inactive. The separate `local-research` demo
now executes two read-only tools over synthetic notes; see RESEARCH.md.
Search the template for `FUTURE(role-agents)` to find the corresponding comments.

## Concept

Several specialized assistants can share one loaded model. Each combines a task
prompt with server-enforced permissions, a small approved tool set, and a defined
data scope. An agent additionally has an execution loop: request a tool, receive its
result, and continue within limits. The assistant and creative profiles remain configured assistants; local-research
adds a bounded tool loop. Opt-in JWT role authorization is implemented for the existing profiles and demo
tools. Payroll/help desk data ownership and downstream authorization remain future work.

The employee's verified identity and permissions determine access. Choosing a model
named `payroll-assistant`, claiming a role in chat, or changing client metadata must
never grant permission. A role described in a system prompt is behavior guidance,
not authorization.

## Demonstration scenarios

| Assistant | Example request | Proposed tools | Enforced scope |
|---|---|---|---|
| Payroll self-service | Explain the deductions on my latest pay statement | `get_my_pay_statement`, `search_payroll_policy` | Employee ID resolved by the server from verified identity; authorized policy documents |
| Help desk self-service | What is happening with my ticket? | `get_my_ticket_status`, `search_support_kb` | Caller-owned tickets and authorized knowledge collections |

These tool names and permissions are illustrative, not callable functions or supported
configuration fields. Use synthetic employees, pay statements, and tickets in demos.
Do not present a prompt-only simulation as a demonstration of enforced access control.

A future payroll specialist or help desk technician may have a broader scope, but
only through an explicitly assigned permission and resource policy. Administrative
access to the UI does not automatically confer payroll or ticket access.

Start read-only. Creating tickets, changing employee records, resetting credentials,
or issuing payments would be separate capabilities with separate authorization,
approvals where required, and auditable execution. A read permission must never
implicitly enable any of these actions.

## Control flow and remaining work

1. The JWT scaffold can authenticate a signed token using configured public keys;
   provider integration is pending. The current shared
   harness key cannot identify an individual user. Use established token-validation
   libraries and tokens intended for the API; validate issuer, audience, and expiry.
2. Authorize access to the selected assistant profile using authoritative policy.
3. Build the available tool set from profile policy intersected with caller permissions.
   Keep credentials outside the prompt and model-visible tool arguments.
4. When the model requests a tool, validate the arguments and recheck action/resource
   permissions. Derive owner/tenant scope server-side; treat requested IDs as untrusted.
5. Execute through a narrowly scoped adapter. The downstream service also enforces
   resource access, using delegated identity or a trusted, scoped service design.
6. Bound tool calls, runtime, output size, and overall context. Return structured errors
   for denied/unavailable actions, and treat retrieved text as untrusted data.
7. Record caller, action, scope, decision, policy version, and outcome with an appropriate
   retention/redaction policy. Do not routinely log full pay statements or credentials.

Open WebUI can show permitted profiles and tools. The backend remains authoritative
when a caller uses a different UI or sends requests directly. Keep one execution loop
owner; do not accidentally enable both UI-managed and harness-managed tools.

## Acceptance examples for a future implementation

- An employee can retrieve their own synthetic pay statement; another employee's
  statement remains inaccessible even when its ID is supplied directly.
- A help desk user can see their own ticket; a guessed ticket ID outside their scope
  is denied by the backend and data service.
- Unauthorized profile selection fails before data retrieval. A forged role in a
  prompt or request body cannot change the decision.
- A tool not in the permitted set cannot execute, even if the model emits its name.
- Expired credentials, missing identity, unavailable authorization services, and
  malformed tool calls do not fall back to broader access.
- The same decisions hold through Open WebUI and a direct API client after upgrades.

## References

- [Open WebUI RBAC](https://docs.openwebui.com/features/authentication-access/rbac/)
- [Microsoft claims validation](https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation)
- [OWASP authorization guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)
