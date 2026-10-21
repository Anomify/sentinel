# Sentinel as a system service

On hpz2g9, one systemd service, `sentinel`, runs the dashboard, the API and the scheduler, listening on port 1115 on every interface.

| What | Where |
|---|---|
| Checkout | `/mnt/home/si/repos/sentinel` (a CIFS share) |
| Python venv | `/home/si/venvs/sentinel` (editable install) |
| Data: SQLite, evidence screenshots, workspaces | `/var/lib/sentinel` (created by systemd, owned by si) |
| Secrets: `SENTINEL_TOKEN`, API keys | `/etc/sentinel/sentinel.env` (root, mode 0600) |
| Unit | `/etc/systemd/system/sentinel.service`, installed from `deploy/sentinel.service` |
| Logs | `journalctl -u sentinel` |

Addresses: http://10.10.121.63:1115 on the LAN; http://hpz2g9:1115 and https://hpz2g9.tail548525.ts.net:8443 on the tailnet.

## First install

1. As si, build everything: `sh deploy/update.sh`. This installs the Python dependencies and Chromium, then builds the dashboard. It restarts the service only once the service exists.
2. Install and start the service: `sudo sh deploy/install.sh`. On the first run it creates the secrets file with a new random `SENTINEL_TOKEN`.
3. Read the token with `sudo grep SENTINEL_TOKEN /etc/sentinel/sentinel.env`, and enter it when the dashboard asks.
4. Firewall: check `sudo ufw status verbose`. If incoming connections are denied by default, allow the port from the LAN and the tailnet only:

   ```
   sudo ufw allow from 10.10.121.0/24 to any port 1115 proto tcp
   sudo ufw allow in on tailscale0 to any port 1115 proto tcp
   ```

5. HTTPS on the tailnet: `tailscale serve --bg --https=8443 http://127.0.0.1:1115`, then confirm with `tailscale serve status`. The root of that name already belongs to another app, so leave it alone. The dashboard can't move to a sub-path, because it uses absolute `/api` and `/assets` URLs.
6. Set `digest.app_url` in `config/settings.yaml` to the address digest readers should open. Email and Slack links, and the digest's font, are loaded from it.

The scripts are run through `sh` because files on the CIFS share can't be marked executable.

## Updating

After `git pull`, run `sh deploy/update.sh` as si. It reinstalls dependencies, rebuilds the dashboard and restarts the service, asking for your sudo password for the restart. If `deploy/sentinel.service` changed, also run `sudo sh deploy/install.sh`, which reinstalls the unit and keeps the existing secrets file.

The dashboard can't be built with `make web` or a plain `npm ci` from this checkout: npm puts symlinks in `node_modules/.bin`, and the CIFS share can't hold them, so the install fails with `EIO`. `update.sh` installs with `--no-bin-links` and runs `tsc` and `vite` through Node 22 from nvm instead. The default Node, 18, is too old for Vite 8.

## Secrets and API keys

Edit them with `sudoedit /etc/sentinel/sentinel.env`, then `sudo systemctl restart sentinel`. systemd reads this file, not Sentinel, so a comment must sit on a line of its own: anything after a value, even `   # note`, becomes part of the value. Don't copy lines from `.env.example`, whose inline comments would turn into values. A key listed in this file wins over the repo's `.env`, even when it is empty, so keep no `.env` on the server: every file on the share is readable by every local user.

Each AI-search key is spent on a schedule: the visibility run is daily at 04:30, asking every question of every engine that has a key.

## Running it

- **Status and logs:** `systemctl status sentinel` and `journalctl -u sentinel -f`. Access-log lines show `token=***` in place of the token.
- **Won't start?** If `systemctl status` shows `ExecStartPre` exiting with status 1, `SENTINEL_TOKEN` is empty. That process exits too quickly for journald to file its message under the unit, so find it with `journalctl -b -t sh | grep SENTINEL_TOKEN`.
- **An open dashboard keeps itself current**, which suits a kiosk. It polls `/api/pulse` every 15 seconds (every 2.5 while a job runs), refreshes its views when any run finishes, and refreshes them anyway every 5 minutes. After a deploy it reloads itself once the restarted service is serving the new build. A dashboard loaded before this behaviour existed needs one manual reload.
- **Restarting is safe.** A job cut off by a restart is marked failed ("interrupted: Sentinel stopped before this run finished"), and a cut-off full scan stops blocking its deep dive. Run it again from the dashboard. A scheduled job that was cut off waits for its next slot.
- **Run a module by hand** from the dashboard's Run menu, or with `curl -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:1115/api/jobs/dns`. Either way it runs inside the service, with its secrets and data directory. A bare `sentinel dns` in a shell would use `./data` and no keys.
- **Schedule times** in `config/settings.yaml` are machine time, which here is UTC. Config edits apply without a restart.
- **Backups:** `/var/lib/sentinel`. For a consistent copy of the database while the service is running, use `sqlite3 /var/lib/sentinel/sentinel.db ".backup /path/to/copy.db"`.
- **GitHub Actions:** `.github/workflows/monitor.yml` collects separately into its own database on the `sentinel-data` branch. The server doesn't need it, so disable it on GitHub unless you want both.

## Office TV

`/tv` is a read-only screen for the office TV: one fixed 16:9 page with no scrolling, always dark, updating live. It shows the latest moves, this week's counts, AI share of voice, who's moving and recent posts. A new critical or high move fills the screen for 12 seconds with a chime, and a new medium move shows a smaller card in the corner with a softer tick.

- **Launch** on the laptop driving the TV over HDMI, using Chrome full screen on the TV and with sound allowed to start without a click:
  `google-chrome --kiosk --autoplay-policy=no-user-gesture-required --window-position=<TV x offset>,0 "http://hpz2g9:1115/tv?token=<SENTINEL_TOKEN>"`
  The page stores the token on that browser and removes it from the address, so later launches can use plain `/tv`. Without `--kiosk`, press **F** or the on-screen button to go full screen. The cursor and buttons hide after 3 seconds without mouse movement.
- **Quiet hours:** no sound from 10:00 to 10:45 on Tuesdays and Wednesdays, by the laptop's clock. Change this with `?quiet=tue,wed@10:00-10:45;fri@16:00-17:00`, or turn it off with `?quiet=off`. Use `?sound=off` to silence the screen entirely.
- **Custom sounds:** put `critical.mp3`, `high.mp3` and/or `medium.mp3` in `web/public/kiosk-sounds/` and rebuild with `sh deploy/update.sh`. Any cue without a file uses the built-in tone.
- **What it announces:** only moves this screen hasn't shown before. It remembers them across reloads, and the first time it runs it treats everything already there as seen. The status at the top right shows "Live" with the age of the data, amber when collection has gaps, and red when the server stops answering.
- **Left running:** it keeps the display awake, reloads itself at 04:00 each day, and picks up new builds on its own.

## Removing it

```
sudo systemctl disable --now sentinel
sudo rm /etc/systemd/system/sentinel.service && sudo systemctl daemon-reload
tailscale serve --https=8443 off
```

The data in `/var/lib/sentinel` and the secrets in `/etc/sentinel` are left in place. Delete them by hand if you're sure.
