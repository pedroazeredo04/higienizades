#!/usr/bin/env bash
# Pull the latest code and restart. Run it over SSH, or from cron for
# hands-off updates:  0 4 * * 1  /home/pi/higienizades/update.sh >> /tmp/hig.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"

git pull --ff-only
docker compose up -d --build
docker image prune -f
echo "Updated. Board is at http://$(hostname -I | awk '{print $1}'):3000"
