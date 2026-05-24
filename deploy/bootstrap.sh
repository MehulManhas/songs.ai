#!/usr/bin/env bash
# bootstrap.sh - one-time setup for a fresh Ubuntu 24.04 droplet.
#
# Run as root (or with sudo) the first time you SSH into the droplet.
# After this finishes, you'll have:
#   - 2 GB swap file (essential on a 1 GB droplet running Lavalink)
#   - Docker + the Compose plugin installed
#   - A non-root `deploy` user that owns the repo and runs containers
#   - UFW firewall: only SSH inbound; everything else blocked
#   - Automatic security updates
#
# Run with:
#   curl -fsSL https://raw.githubusercontent.com/MehulManhas/songs.ai/main/deploy/bootstrap.sh | sudo bash
#
# or, if you already have the repo cloned:
#   sudo bash deploy/bootstrap.sh

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run as root (use sudo)."
    exit 1
fi

DEPLOY_USER="${DEPLOY_USER:-deploy}"
REPO_URL="${REPO_URL:-https://github.com/MehulManhas/songs.ai.git}"

echo "==> apt update + upgrade"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq

echo "==> installing prerequisites"
apt-get install -y -qq \
    ca-certificates curl gnupg ufw fail2ban unattended-upgrades \
    git

# ----- swap file (essential on 1 GB droplet) -----------------------------
if ! swapon --show | grep -q "/swapfile"; then
    echo "==> creating 2 GB swap file"
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    echo "/swapfile none swap sw 0 0" >> /etc/fstab
    sysctl vm.swappiness=10 >/dev/null
    echo "vm.swappiness=10" > /etc/sysctl.d/99-swappiness.conf
else
    echo "==> swap already present, skipping"
fi

# ----- docker install (official method) ----------------------------------
if ! command -v docker >/dev/null; then
    echo "==> installing Docker"
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    . /etc/os-release
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq \
        docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
else
    echo "==> docker already installed, skipping"
fi

# ----- deploy user -------------------------------------------------------
if ! id "${DEPLOY_USER}" &>/dev/null; then
    echo "==> creating user '${DEPLOY_USER}'"
    adduser --disabled-password --gecos "" "${DEPLOY_USER}"
    usermod -aG docker "${DEPLOY_USER}"
else
    echo "==> user '${DEPLOY_USER}' already exists, ensuring docker group membership"
    usermod -aG docker "${DEPLOY_USER}"
fi

DEPLOY_HOME="$(getent passwd "${DEPLOY_USER}" | cut -d: -f6)"
install -d -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" -m 0700 "${DEPLOY_HOME}/.ssh"

# ----- SSH key for GitHub Actions ----------------------------------------
echo "==> adding deploy SSH key to authorized_keys"
echo
echo "PASTE the PUBLIC half of the SSH key you generated for GitHub Actions"
echo "(the contents of songs_ai_deploy.pub), then press Ctrl-D on a new line:"
echo
cat >> "${DEPLOY_HOME}/.ssh/authorized_keys"
chown "${DEPLOY_USER}:${DEPLOY_USER}" "${DEPLOY_HOME}/.ssh/authorized_keys"
chmod 600 "${DEPLOY_HOME}/.ssh/authorized_keys"
echo "==> key added"

# ----- firewall ----------------------------------------------------------
echo "==> configuring ufw (allow SSH only)"
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

# ----- automatic security updates ----------------------------------------
echo "==> enabling unattended-upgrades"
dpkg-reconfigure --frontend=noninteractive unattended-upgrades

# ----- clone the repo as the deploy user ---------------------------------
if [[ ! -d "${DEPLOY_HOME}/songs.ai" ]]; then
    echo "==> cloning repo to ${DEPLOY_HOME}/songs.ai"
    sudo -u "${DEPLOY_USER}" git clone "${REPO_URL}" "${DEPLOY_HOME}/songs.ai"
else
    echo "==> repo already cloned, fetching latest"
    sudo -u "${DEPLOY_USER}" git -C "${DEPLOY_HOME}/songs.ai" fetch --quiet
fi

echo
echo "================================================================"
echo "  Bootstrap complete."
echo
echo "  NEXT STEPS:"
echo "    1. As the deploy user, create the .env file:"
echo "         sudo -u ${DEPLOY_USER} -i"
echo "         cd ~/songs.ai"
echo "         cp .env.example .env"
echo "         nano .env       # fill in real values"
echo "    2. First start:"
echo "         docker compose up -d --build"
echo "    3. Watch logs:"
echo "         docker compose logs -f bot"
echo "================================================================"
