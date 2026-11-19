# Deploying with git

These steps run the harness from a git checkout on a Docker host, for example
`/opt/local-model-harness`. Pull with a read-only deploy key that can only read
this one repository.

## Files that stay on the host

These are untracked or ignored, so `git pull` never touches them:

| File | Purpose |
|---|---|
| `.env` | API keys, backend URL, session timeouts |
| `docker-compose.override.yml` | Vault MCP URL, mounts `profiles.local.yaml` over `profiles.yaml` |
| `profiles.local.yaml` | Your live profile set |
| `prompts/assistant.md` | Personal prompt |
| `memory-config/`, `identity-config/` | Database credentials and identity policy |

Edit live profiles in `profiles.local.yaml`, not `profiles.yaml`. The tracked
`profiles.yaml` is the shared template.

## Routine update

On the Docker host:

```bash
cd /opt/local-model-harness
git status --short          # should list no modified tracked files
systemctl start harness-chat-backup.service
docker tag local-model-harness-local-model-harness:latest local-model-harness-local-model-harness:previous
git pull --ff-only
docker compose up -d --build
docker compose ps && curl -fsS http://127.0.0.1:8200/health/live
```

Docker Compose names the image after the project directory and service. Run
`docker images` once to confirm the name on your host.

After a profile or prompt edit, check the file first, then restart only if it passes:

```bash
docker compose exec -T local-model-harness python scripts/check_config.py && docker compose restart
```

The check applies the same rules as startup and names the bad field, for example
`local-home.compaction.timeout_seconds: Input should be less than or equal to 180`.
A failing file never reaches the restart, so the running harness stays up. The check
runs in the current container, so after a `git pull` that changes validation code,
rebuild first. After a `.env` edit, use `docker compose up -d --force-recreate`.

## Rollback

```bash
cd /opt/local-model-harness
git log --oneline -5                      # pick the last good commit
git checkout <commit>                     # detached HEAD on the old code
docker tag local-model-harness-local-model-harness:previous local-model-harness-local-model-harness:latest
docker compose up -d --no-build --force-recreate local-model-harness
```

Return to normal with `git checkout main` and the routine update. Never run
`docker compose down -v`, which deletes the chat-history volume.

## One-time setup

1. Create a key on the host with
   `ssh-keygen -t ed25519 -N "" -C local-model-harness-deploy -f /root/.ssh/local_model_harness_deploy`.
   Add the `.pub` file as a read-only deploy key on your GitHub repository.
2. Add a host alias to `/root/.ssh/config`:
   ```text
   Host github-harness
     HostName github.com
     User git
     IdentityFile /root/.ssh/local_model_harness_deploy
     IdentitiesOnly yes
   ```
   Then run `ssh -T github-harness` and compare the host key fingerprint with the one
   GitHub publishes in its documentation before accepting it.
3. Clone with `git clone github-harness:<owner>/<repo>.git /opt/local-model-harness`.
   To turn an existing copied tree into a checkout without touching its files, run
   `git init -b main`, `git remote add origin github-harness:<owner>/<repo>.git`,
   `git fetch origin`, `git reset origin/main`, then
   `git branch --set-upstream-to=origin/main main` so a plain `git pull` knows what to follow.
4. Put your live profiles in `profiles.local.yaml` and mount them from the override,
   so `git status` shows no tracked changes.
