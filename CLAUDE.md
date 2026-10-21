# Sentinel

Work on this repository is tracked in Subroutine: project `sentinel` in the `projects` workspace. The `.subroutine` file at the repository root points the Subroutine tools at it.

On hpz2g9 Sentinel runs as the `sentinel` systemd service; `deploy/README.md` is the runbook. Keep it to one `sentinel serve` process (the scheduler and job registry are in memory), with data in `/var/lib/sentinel` and secrets in `/etc/sentinel/sentinel.env`, both off the CIFS share the checkout lives on. Build the dashboard with `sh deploy/update.sh`: plain `npm ci` fails on the share.
