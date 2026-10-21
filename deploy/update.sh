#!/bin/sh
# Bring Sentinel up to date with this checkout: Python dependencies, Chromium, the dashboard build, then a restart
# if the service is installed. Run as si, not root, after a git pull:
#   sh deploy/update.sh
set -eu
cd "$(dirname "$0")/.."
venv=/home/si/venvs/sentinel

"$venv/bin/pip" install -q -e ".[browser,dev]"
"$venv/bin/playwright" install chromium

# Vite 8 needs Node >= 20.19; use the newest Node 22 that nvm has installed.
node_bin=$(ls -d "$HOME"/.nvm/versions/node/v22.*/bin | sort -V | tail -n 1)
PATH="$node_bin:$PATH"
# The checkout is on a CIFS share, which can't hold symlinks, so the links npm makes in node_modules/.bin fail
# with EIO: install without them and run the build tools through node directly.
cd web
npm ci --no-bin-links --no-audit --no-fund
node node_modules/typescript/bin/tsc --noEmit
node node_modules/vite/bin/vite.js build
cd ..

if systemctl is-enabled --quiet sentinel 2>/dev/null; then
	sudo systemctl restart sentinel
	echo "Restarted sentinel."
fi
