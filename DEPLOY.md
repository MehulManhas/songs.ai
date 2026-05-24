# Deploying songs.ai to a DigitalOcean droplet

Full end-to-end walkthrough: gather all credentials, prepare the droplet, deploy with one command, then set up GitHub Actions so every `git push` redeploys automatically.

Estimated time first run: ~45 minutes (most of it is filling in API portal forms). After that, deploys are one `git push`.

---

## Part 1 — Gather every credential

Open a text file somewhere safe (a password manager, not a `.txt` on your desktop). You'll paste 6 things into it. None of these get committed to git.

### 1.1 Discord bot token

You already have this from earlier. If you've lost it, go to <https://discord.com/developers/applications> → your app → **Bot** → **Reset Token** → copy the new value.

```
DISCORD_TOKEN=<the long string with dots in it>
```

While you're on the Bot page: ensure **NO** privileged intents are enabled (Message Content, Server Members, Presence) — the bot doesn't use them and they slow down Discord verification later.

### 1.2 Jamendo Client ID

1. Go to <https://devportal.jamendo.com/> and sign up (free).
2. Once logged in, click **Create an app** (top right).
3. Name it `songs.ai`, leave the rest blank, save.
4. Copy the **Client ID** value.

```
JAMENDO_CLIENT_ID=<32-character hex string>
```

Free tier: 35,000 requests/month. You won't hit that.

### 1.3 Bot secret key (for encrypting Navidrome credentials in SQLite)

Generate locally. From any machine that has Python:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Output is a 44-character base64 string ending in `=`. Save it.

```
BOT_SECRET_KEY=<44-char string ending in =>
```

⚠️ If you ever lose or rotate this, every `/library setup` configuration on the bot becomes unreadable and admins have to re-enter their Navidrome credentials.

### 1.4 Lavalink password

Generate a strong random one — never use the `youshallnotpass` default in production:

```powershell
# Windows PowerShell:
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object {[char]$_})

# Or on the droplet:
openssl rand -hex 24
```

```
LAVALINK_PASSWORD=<random 32+ character string>
```

This is internal to your droplet (Lavalink only listens inside the docker network), but rotate it if it ever leaks.

### 1.5 Last.fm API key (optional — enables `/discover similar`)

1. Go to <https://www.last.fm/api/account/create>.
2. **Contact email:** yours. **Application name:** `songs.ai`. **Application description:** "Discord music bot — similar-artist metadata." **Callback URL:** leave blank. **Application homepage:** your GitHub repo URL.
3. Submit. The next page shows your **API Key** (32-char hex string).

```
LASTFM_API_KEY=<32-character hex string>
```

If you skip this, only `/discover similar` is disabled — everything else works.

### 1.6 SSH deploy key (for GitHub Actions → droplet auto-deploy)

Generate a key pair locally — **on your laptop, NOT on the droplet**:

```powershell
ssh-keygen -t ed25519 -C "songs-ai-deploy" -f songs_ai_deploy -N '""'
```

That creates two files in your current directory:

- `songs_ai_deploy` — the **PRIVATE** key. Goes into a GitHub Secret in Part 4.
- `songs_ai_deploy.pub` — the **PUBLIC** key. Goes onto the droplet in Part 2.

Open both in Notepad. Keep the windows open — you'll paste them in the next two parts.

### Credential checklist before continuing

You should now have all 6 items copied somewhere safe:

- [ ] `DISCORD_TOKEN`
- [ ] `JAMENDO_CLIENT_ID`
- [ ] `BOT_SECRET_KEY` (44-char Fernet key)
- [ ] `LAVALINK_PASSWORD` (random)
- [ ] `LASTFM_API_KEY` (optional)
- [ ] `songs_ai_deploy` + `songs_ai_deploy.pub` (SSH key pair)

---

## Part 2 — Prepare the droplet

### 2.1 Create the droplet (skip if you already have one)

DigitalOcean Cloud → **Create → Droplets**:

- **Region:** closest to you (latency to Discord doesn't matter much, but you'll SSH a lot)
- **Image:** Ubuntu 24.04 LTS x64
- **Size:** Basic → Regular → **$6/mo** (1 GB / 1 CPU / 25 GB SSD). Bootstrap script will add a 2 GB swap file to compensate.
- **Authentication:** SSH key. Add your laptop's public key here. (If you don't have one, generate it with `ssh-keygen -t ed25519` — different key from the deploy one above.)
- **Hostname:** `songs-ai` (or whatever you like)
- Click **Create Droplet**, wait ~30 seconds, copy the **public IPv4 address** that appears.

### 2.2 First SSH and run the bootstrap script

From your laptop:

```powershell
ssh root@<droplet-ip>
```

(First connection asks "Are you sure you want to continue connecting?" — type `yes`.)

You're now on the droplet. Run:

```bash
curl -fsSL https://raw.githubusercontent.com/MehulManhas/songs.ai/main/deploy/bootstrap.sh | bash
```

The script will:

1. Update Ubuntu packages
2. Create a 2 GB swap file (essential on a 1 GB droplet)
3. Install Docker and the Compose plugin
4. Create a non-root `deploy` user
5. Set up the UFW firewall (only SSH allowed inbound)
6. Enable automatic security updates
7. Clone the repo to `/home/deploy/songs.ai`

Partway through, it will **pause and ask you to paste the public deploy key.** Open `songs_ai_deploy.pub` from your laptop, copy the entire contents (starts with `ssh-ed25519 …`), paste into the SSH session, then press **Enter** then **Ctrl+D** on a new line.

When you see `Bootstrap complete`, the droplet is ready.

### 2.3 Create the .env file on the droplet

Still in the SSH session:

```bash
sudo -u deploy -i
cd ~/songs.ai
cp .env.example .env
nano .env
```

Fill in every value from Part 1. The file should look like:

```
DISCORD_TOKEN=<from 1.1>
JAMENDO_CLIENT_ID=<from 1.2>
BOT_SECRET_KEY=<from 1.3>
LAVALINK_PASSWORD=<from 1.4>
LASTFM_API_KEY=<from 1.5, or leave blank>

LAVALINK_HOST=lavalink     # leave as-is (docker network name)
LAVALINK_PORT=2333
DEFAULT_VOLUME=60
SKIP_VOTE_RATIO=0.5
LOG_LEVEL=INFO
```

Save: **Ctrl+O**, **Enter**, **Ctrl+X**.

Lock down permissions:

```bash
chmod 600 .env
```

### 2.4 First start

```bash
docker compose up -d --build
```

This builds the bot image (~2 min on a 1 GB droplet) and pulls Lavalink (~30s). When it returns, check that both containers came up:

```bash
docker compose ps
```

You should see `songs-bot` and `songs-lavalink` both `running`. Watch the bot connect:

```bash
docker compose logs -f bot
```

Within ~10 seconds you should see `Logged in as <your-bot>#1234`. Hit **Ctrl+C** to stop tailing (the bot keeps running in the background).

If the bot shows OOM-killed or Lavalink dies, run `free -h` to see memory. The swap file should be active (`Swap: 2.0Gi`). If it isn't, re-run the bootstrap.

---

## Part 3 — Test it works

Invite the bot to a test server (you already have the invite URL from earlier — same Discord application means same invite URL). Join a voice channel, then in a text channel:

```
/play lofi
```

Within a few seconds the bot should join voice and start playing a Jamendo CC track. If it doesn't, `docker compose logs bot` on the droplet will show why.

---

## Part 4 — Set up auto-deploy from GitHub

### 4.1 Add the four GitHub Secrets

On <https://github.com/MehulManhas/songs.ai>, go to **Settings → Secrets and variables → Actions → New repository secret**. Add four:

| Name | Value |
|------|-------|
| `DROPLET_HOST` | Your droplet's public IP (e.g. `167.99.x.x`) |
| `DROPLET_USER` | `deploy` |
| `DROPLET_SSH_KEY` | The entire contents of `songs_ai_deploy` (private key), including the `-----BEGIN OPENSSH PRIVATE KEY-----` and `-----END OPENSSH PRIVATE KEY-----` lines |
| `DROPLET_PORT` | `22` *(optional — workflow defaults to 22)* |

### 4.2 Trigger the first deploy

The workflow file (`.github/workflows/deploy.yml`) is already in the repo and runs on every push to `main`. To trigger it now, either:

- Push a trivial commit (edit the README, push), **or**
- Go to **Actions** tab → **Deploy to droplet** → **Run workflow** → branch `main` → **Run**.

Watch it run. The two-step workflow:

1. SSHes in, pulls latest, rebuilds + restarts containers
2. Waits 20s, checks the bot logged in to Discord

Green checkmark = deployed. Red X = it tells you which step failed and shows the log.

### 4.3 From now on

Local edit → commit → push to main → ~2 minutes later the droplet is running the new code. No SSH needed for normal changes.

If you need to ship a hotfix without pushing through main (rare):

```bash
ssh deploy@<droplet-ip>
cd ~/songs.ai
git pull
docker compose up -d --build
```

---

## Part 5 — Going public (Discord verification)

Once you cross 75 servers, Discord requires verification. To prepare:

1. **Add `/privacy` command to the bot** (links to a PRIVACY.md in the repo).
2. **Privacy policy** should disclose: encrypted Navidrome credentials per guild (deletable with `/library disconnect`), bot ID logging for vote-skip state, no analytics, no message content access.
3. **Terms of service** disclaimer about the music sources (CC, public domain, your own library).
4. **Apply at <https://support.discord.com/hc/en-us/articles/360040720412>.** Include a link to the public GitHub repo so they can audit the code.

---

## Operations cheatsheet

All of these run on the droplet as the `deploy` user:

```bash
# See container status
docker compose ps

# Tail bot logs (Ctrl+C to stop)
docker compose logs -f bot

# Tail Lavalink logs
docker compose logs -f lavalink

# Restart only the bot (e.g. after editing .env)
docker compose restart bot

# Full restart of everything
docker compose restart

# Stop everything (e.g. for maintenance)
docker compose down

# Bring back up after `down`
docker compose up -d

# Update manually (same thing GitHub Actions does)
git pull && docker compose up -d --build && docker image prune -f

# Check memory pressure
free -h

# Check what's chewing CPU
docker stats --no-stream
```

## Troubleshooting

**Bot keeps crashing with `Cannot connect to Lavalink`.** Lavalink needs ~30s to boot. The `depends_on: condition: service_healthy` in docker-compose handles this on first start, but if you `docker compose restart bot` alone, give Lavalink a moment.

**OOM-killed bot or Lavalink.** Your 1 GB droplet is at capacity. Check `free -h`. Solutions in order of preference: (1) verify swap is mounted, (2) drop Lavalink heap further (`_JAVA_OPTIONS=-Xmx256M -Xms192M` in compose), (3) resize to 2 GB.

**GitHub Actions fails with `Permission denied (publickey)`.** The `DROPLET_SSH_KEY` secret content is wrong. Re-paste it — include the `-----BEGIN` and `-----END` lines and the trailing newline. The private key file looks ~400 chars and starts with `-----BEGIN OPENSSH PRIVATE KEY-----`.

**Discord token leaked into a commit.** Reset the token immediately on the Discord Developer Portal (Bot → Reset Token), update `.env` on the droplet, `docker compose restart bot`. The old token is dead the moment you reset.

**Slash commands not appearing.** They take up to 1 hour for global sync. Set `DEV_GUILD_ID` in `.env` to your test server's ID for instant sync during development.
