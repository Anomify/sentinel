#!/bin/sh
# Install (or reinstall) Sentinel's system service, then (re)start it. Run from the checkout as root, through sh
# (files on the CIFS share can't be marked executable):
#   sudo sh deploy/install.sh
# Build first, as si: sh deploy/update.sh. This script never runs pip or npm, so nothing in the checkout or the
# venv ends up owned by root.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
env=/etc/sentinel/sentinel.env

if [ ! -e "$env" ]; then
	install -d -m 0700 /etc/sentinel
	umask 077
	{
		printf 'SENTINEL_TOKEN=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
		cat "$here/sentinel.env.example"
	} > "$env"
	echo "Created $env with a new SENTINEL_TOKEN. Read it with: sudo grep SENTINEL_TOKEN $env"
fi

install -m 0644 "$here/sentinel.service" /etc/systemd/system/sentinel.service
systemctl daemon-reload
systemctl enable sentinel
systemctl restart sentinel
systemctl --no-pager status sentinel
