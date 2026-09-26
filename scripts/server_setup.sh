#!/usr/bin/env bash
# One-shot bootstrap for a fresh Ubuntu 24.04 host (DigitalOcean "Docker" Marketplace image or plain Ubuntu).
# Usage (as root on the server):
#   curl -fsSL https://raw.githubusercontent.com/alkaid040492/nl-regex-platform/main/scripts/server_setup.sh | bash
# Then copy your .env to /opt/nl-regex-platform/.env and run:  /opt/nl-regex-platform/scripts/deploy.sh
set -euo pipefail

REPO="https://github.com/alkaid040492/nl-regex-platform.git"
DIR="/opt/nl-regex-platform"

if ! command -v docker >/dev/null 2>&1; then
  echo ">> installing docker"
  curl -fsSL https://get.docker.com | sh
fi
if ! docker compose version >/dev/null 2>&1; then
  apt-get update && apt-get install -y docker-compose-plugin
fi

# 2 GB swap: Spark + Postgres + Redis on an 8 GB box is fine, but swap avoids OOM kills during image builds.
if [ ! -f /swapfile ]; then
  echo ">> adding 2G swap"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# firewall: ssh + http + https only
if command -v ufw >/dev/null 2>&1; then
  ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
  ufw --force enable >/dev/null
fi

if [ -d "$DIR/.git" ]; then
  echo ">> updating $DIR"; git -C "$DIR" pull --ff-only
else
  echo ">> cloning into $DIR"; git clone "$REPO" "$DIR"
fi
chmod +x "$DIR"/scripts/*.sh

echo
echo "Bootstrap done. Next:"
echo "  1. scp .env root@<server>:$DIR/.env   (from your machine)"
echo "  2. $DIR/scripts/deploy.sh"
