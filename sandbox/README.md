# Python sandbox server (tools VM)

This server implements [ADR-003](../docs/ADR-003-code-sandbox.md). It runs on a dedicated tools VM
(`tools-vm.example.test` in these examples) and exposes one MCP tool, `python_run`. Each call runs in a fresh
container from `harness-sandbox:py312`, with no network, a read-only root, uid 10001, no
capabilities, 1 CPU, 512 MB of RAM, 64 processes, 30 seconds and 16 KB of output per
stream, and the container is removed afterwards. At most two runs happen at once. The
only client is the harness on the harness host, which must send the bearer token.

| File | Purpose |
|---|---|
| `server.py` | FastMCP server, container invocation, output caps, token check |
| `image/` | Runner image: Python 3.12 slim with numpy, pandas, sympy, matplotlib |
| `harness-sandbox.service` | systemd unit (user `sandbox`, env from `/etc/harness-sandbox.env`) |
| `selftest.py` | Escape and correctness tests against real Docker |
| `web_server.py` | Web search (Brave) and page reader MCP server; see "Web search server" below |
| `harness-web.service` | systemd unit (user `webtools`, env from `/etc/harness-web.env`) |
| `common.py` | Bearer-token guard shared by both servers |

## One-time setup

Run these as root on the tools VM unless noted. Replace the example host names with your own.

1. **Snapshot first.** Take a VM snapshot (for example `before-sandbox`) in your hypervisor.
2. **Check for anything to keep.** Run `docker ps -a`, `ls /home`, `crontab -l` for each user,
   and `loginctl list-users`. Stop or remove whatever you no longer need, so the VM
   only runs the sandbox.
3. **Get the code.** Use a read-only deploy key. If your firewall blocks outbound
   port 22, so the alias uses GitHub's SSH endpoint on port 443:
   ```bash
   ssh-keygen -t ed25519 -N "" -C tools-vm-local-model-harness -f /root/.ssh/local_ai_harness_deploy
   cat /root/.ssh/local_ai_harness_deploy.pub   # add as a read-only deploy key on GitHub
   printf 'Host github-harness\n  HostName ssh.github.com\n  Port 443\n  User git\n  IdentityFile /root/.ssh/local_ai_harness_deploy\n  IdentitiesOnly yes\n' >> /root/.ssh/config
   git clone github-harness:your-org/local-model-harness.git /opt/local-ai-harness
   ```
4. **Create the service user, the venv and the image:**
   ```bash
   useradd --system --no-create-home --shell /usr/sbin/nologin sandbox
   apt-get install -y python3-venv
   python3 -m venv /opt/harness-sandbox-venv
   /opt/harness-sandbox-venv/bin/pip install -r /opt/local-ai-harness/sandbox/requirements.txt
   docker build -t harness-sandbox:py312 /opt/local-ai-harness/sandbox/image
   ```
5. **Create the token and environment.** Keep the token for the harness host's `.env`:
   ```bash
   TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
   printf 'SANDBOX_TOKEN=%s\nSANDBOX_ALLOWED_HOSTS=tools-vm.example.test:*\n' "$TOKEN" > /etc/harness-sandbox.env
   chmod 600 /etc/harness-sandbox.env && echo "$TOKEN"
   ```
6. **Run the escape tests** before the server is reachable. All 16 must pass:
   ```bash
   cd /opt/local-ai-harness/sandbox && sudo -u sandbox -g docker /opt/harness-sandbox-venv/bin/python selftest.py
   ```
7. **Firewall: allow TCP 8202 from the harness host only.** This assumes ufw denies all incoming and most
   outgoing traffic, and blocks connections into the lab subnet. Add one rule:
   ```bash
   ufw allow from harness.example.test to any port 8202 proto tcp comment 'Harness sandbox MCP from the harness host'
   ```
   If the VM's NIC also has a hypervisor firewall with an input policy of DROP, add the same
   rule there. The containers publish no ports and have
   no network, so Docker's ufw bypass for published ports does not apply.
8. **Start the service:**
   ```bash
   cp /opt/local-ai-harness/sandbox/harness-sandbox.service /etc/systemd/system/
   systemctl daemon-reload && systemctl enable --now harness-sandbox
   journalctl -u harness-sandbox -n 5 --no-pager   # expect {"event": "start", ...}
   ```
9. **Start the VM at boot** in your hypervisor's settings.

## Connect the harness (the harness host)

Add the following to `/opt/local-model-harness/.env`, using the token from step 5:
```text
HARNESS_CODE_MCP_URL=http://tools-vm.example.test:8202/mcp
HARNESS_CODE_MCP_TOKEN=<token>
```
Then pull and recreate the container, so it picks up both the new code and the `.env`:
```bash
git pull --ff-only && docker compose up -d --build --force-recreate
```
Add `code` to the profiles that should get the sandbox in `profiles.local.yaml`. For
example, `mcp_servers: [vault, code]` on local-tools, and on local-home and local-work,
where `mcp_default: []` keeps it off until a chat turns it on. Then check and restart:
```bash
docker compose exec -T local-model-harness python scripts/check_config.py && docker compose restart
```
In `/chat/` a **Python sandbox** chip appears. Ask something that needs real arithmetic.
The activity line should end in `python_run`.

## Updating

```bash
cd /opt/local-ai-harness && git pull --ff-only
docker build -t harness-sandbox:py312 sandbox/image          # if image/ changed
/opt/harness-sandbox-venv/bin/pip install -r sandbox/requirements.txt   # if requirements changed
cd sandbox && sudo -u sandbox -g docker /opt/harness-sandbox-venv/bin/python selftest.py
systemctl restart harness-sandbox
```

## Operations

- **Logs:** `journalctl -u harness-sandbox`. One JSON line per run, with metadata only.
- **Disable:** remove `code` from the harness profiles, or run
  `systemctl disable --now harness-sandbox`. Harness calls then fail with `sandbox_unavailable`.
- **Leftover containers:** the server removes them at startup.
  `docker ps -a --filter label=harness-sandbox=1` should normally be empty.
- **Rollback:** restore the `before-sandbox` VM snapshot.


# Web search server (tools VM)

`web_server.py` exposes two MCP tools on TCP 8203:
- `web_search` queries the Brave Search API and returns up to 8 results, each with a title,
  URL, snippet, up to three extra snippets and its age.
- `web_read` fetches one public page and returns up to 16,000 characters of readable text.

The Brave key lives only in `/etc/harness-web.env`. The server runs as its own `webtools`
user with no Docker access and no capabilities, and the systemd unit sandboxes it.

Guards on `web_read`:
- Only http(s) URLs on the default ports, with no credentials in the URL, are accepted.
- Every address a host resolves to must be public, and that check is repeated after each
  redirect, up to 5. This blocks the lab subnet and any other private networks (RFC 1918 ranges,
  CGNAT/VPN 100.64.0.0/10) that the host firewall may not block outbound. The firewall's lab
  rule is the second layer.
- A response body is capped at 2 MB, and only text content types are accepted.
- Searches are capped at `WEB_DAILY_SEARCH_LIMIT` per UTC day (default 300) to protect the
  prepaid credits. At most four calls run at once. Logs record only the tool, status, result
  count and page host.

## Setup

As root on the tools VM, after the sandbox setup above (it reuses the clone and the venv):

```bash
cd /opt/local-ai-harness && git pull --ff-only
/opt/harness-sandbox-venv/bin/pip install -r sandbox/requirements.txt
useradd --system --no-create-home --shell /usr/sbin/nologin webtools
TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
printf 'WEB_TOKEN=%s\nWEB_ALLOWED_HOSTS=tools-vm.example.test:*\nWEB_DAILY_SEARCH_LIMIT=300\nBRAVE_API_KEY=\n' "$TOKEN" > /etc/harness-web.env
chmod 600 /etc/harness-web.env && echo "$TOKEN"
```

Paste your Brave key after `BRAVE_API_KEY=` in `/etc/harness-web.env`, using an editor on
the tools VM so it never appears in shell history or chat. Then open the port to the harness host and start
the service:

```bash
ufw allow from harness.example.test to any port 8203 proto tcp comment 'Harness web MCP from the harness host'
cp /opt/local-ai-harness/sandbox/harness-web.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now harness-web
journalctl -u harness-web -n 5 --no-pager   # expect {"event": "start", "port": 8203, ...}
```

## Connect the harness

In the harness host's `.env`, using the token printed above:
```text
HARNESS_WEB_MCP_URL=http://tools-vm.example.test:8203/mcp
HARNESS_WEB_MCP_TOKEN=<token>
```
Then `git pull --ff-only && docker compose up -d --build --force-recreate`. In
`profiles.local.yaml`, add `web` to `mcp_servers` on local-tools, local-home and local-work.
Keep it out of `mcp_default`, so it starts off and spends credits only when you turn on the
**Web search** chip. On local-tools that means `mcp_default: [vault, code]`. Run
`check_config.py`, then restart.
