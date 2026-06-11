# AA ADM Monitor

An [Alliance Auth](https://gitlab.com/allianceauth/allianceauth) plugin that monitors the
**ADM (Activity Defense Multiplier)** of your alliance's sovereignty systems via ESI and
alerts a Discord channel when systems drop below a configurable threshold.

## Features

- **Daily report** at a configurable time (EVE time / UTC) listing every monitored system
  below the configured ADM threshold, with its current ADM, the military / industrial /
  strategic index levels, region and owning alliance.
- **Immediate alerts** (toggleable) the moment a system *newly* drops below the threshold.
  Each system alerts **only once** per episode — it can alert again only after recovering
  to/above the threshold and dropping below it again.
- Delivery through your existing **[allianceauth-discordbot](https://github.com/Solar-Helix-Independent-Transport/allianceauth-discordbot)**
  (just a channel ID), with an optional plain **Discord webhook** as fallback — no extra bot needed.
- All configuration lives in the **Alliance Auth admin panel** (`/admin/` → ADM Monitor).
- Monitor one or more alliances (comma-separated alliance IDs); systems are picked up and
  dropped automatically as sovereignty changes.
- Admin actions: *Send test message*, *Run ADM check now*, *Send daily report now*, and a
  browsable per-system status table.
- Uses only **public ESI** endpoints — no ESI tokens or scopes required.

> **Military / industrial / strategic indices:** the new ESI sovereignty endpoint
> (`GetSovereigntySystems`) exposes the full development block per claimed system —
> `activity_defense_multiplier` (the ADM) plus `military_level`, `industrial_level` and
> `strategic_level` — all of which are included in the alerts and the status table.

## How it works

A single Celery task runs on a schedule you define (every 15 minutes recommended). Each run it:

1. Pulls the sovereignty systems list from ESI (`GetSovereigntySystems`) and keeps the
   systems claimed by your configured alliance(s), reading the ADM and the
   military/industrial/strategic levels from each claim's development block.
2. Updates the per-system state table, resolving system/region/alliance names once via ESI.
3. If **immediate alerts** are on, sends one alert covering all systems that newly dropped
   below the threshold and marks them as alerted. A system recovering to/above the
   threshold resets its alert flag.
4. If the configured **daily report time** (UTC) has passed and today's report hasn't been
   sent yet, sends the daily report.

On the very first run after installation, systems already below the threshold are treated as
baseline and do **not** trigger immediate alerts (the daily report covers them).

---

## Installation (aa-docker / dockerized Alliance Auth)

These steps assume the standard [aa-docker](https://gitlab.com/allianceauth/allianceauth/-/tree/master/docker)
layout at `/opt/allianceauth/aa-docker` with your config in `conf/`.

### 1. Add the package

Append to `conf/requirements.txt`:

```
aa-admmonitor @ git+https://github.com/Shawncrew/aa-admmonitor.git@v0.1.2
```

(Pin a tag for reproducible builds; use `@master` to track the latest.)

### 2. Register the app and the schedule

Edit `conf/local.py`:

```python
# Add the app
INSTALLED_APPS += ["admmonitor"]

# Run the ADM monitor every 15 minutes.
# 'crontab' is already imported at the top of the aa-docker local.py;
# if not, add: from celery.schedules import crontab
CELERYBEAT_SCHEDULE["admmonitor_run"] = {
    "task": "admmonitor.tasks.run_admmonitor",
    "schedule": crontab(minute="*/15"),
}
```

The daily report is sent on the **first run at/after the configured time**, so with a
15-minute schedule it arrives within 15 minutes of the configured time. Use
`crontab(minute="*/5")` if you want tighter timing.

### 3. Rebuild and restart the stack

```bash
cd /opt/allianceauth/aa-docker
docker compose build
docker compose --env-file=.env up -d
```

### 4. Run migrations

```bash
docker compose exec allianceauth_gunicorn bash -c \
  "python /home/allianceauth/myauth/manage.py migrate admmonitor"
```

(Or open a shell with `docker compose exec allianceauth_gunicorn bash` and run `auth migrate`.)

### 5. Restart the workers and beat

The workers and beat need the new code and schedule:

```bash
docker compose restart allianceauth_worker_beat
docker compose restart $(docker compose ps --services | grep worker)
```

(A plain `docker compose --env-file=.env up -d` after the build typically recreates them
already — the restart is just to be sure.)

### 6. Configure in the admin panel

Open your Auth site → **Admin** → **ADM Monitor** → **ADM Monitor Configuration** → *Add*:

| Setting | Description |
|---|---|
| **Enabled** | Master switch for the whole monitor. |
| **Threshold** | Systems with ADM strictly below this value are reported (e.g. `4.0`). |
| **Alliance IDs** | Comma-separated alliance IDs to monitor, e.g. `99003581`. Find yours on [zKillboard](https://zkillboard.com/) or via `https://esi.evetech.net/latest/search/` — it's the number in your alliance's zkill/dotlan URL. Leave blank to monitor *all* sov systems in the game (not recommended). |
| **Discord channel ID** | Target channel for alerts, sent via allianceauth-discordbot. Enable Developer Mode in Discord, right-click the channel → *Copy ID*. The bot must have permission to post there. |
| **Webhook URL (fallback)** | Optional. Used if the bot path is unavailable/fails. Channel settings → Integrations → Webhooks. |
| **Immediate alerts enabled** | Toggle for instant alerts on new threshold crossings. |
| **Daily report enabled** | Toggle for the daily summary. |
| **Daily report time** | Time of day in **EVE time (UTC)** for the daily report. |

### 7. Test it

On the configuration list page, tick the config and use the admin actions:

- **Send test message to Discord** — verifies delivery end-to-end.
- **Run ADM check now** — queues an immediate ESI refresh; then check
  **System ADM Statuses** in the admin to see the data.
- **Send daily report now** — sends the report immediately.

Worker logs if something misbehaves:

```bash
docker compose logs -f --tail=100 allianceauth_worker
```

### Notes for this setup

- Your stack already runs the `aadiscordbot` queue worker (`allianceauth_worker_pingbot`),
  so bot delivery works out of the box — no extra Celery routing needed.
- All containers are built from the same image, so the plugin (and its admin pages, tasks)
  is available everywhere after one `docker compose build`.

---

## Installation (bare metal / venv)

```bash
pip install git+https://github.com/Shawncrew/aa-admmonitor.git@v0.1.2
```

Then add `admmonitor` to `INSTALLED_APPS`, add the `CELERYBEAT_SCHEDULE` entry shown above
to your `local.py`, run `python manage.py migrate admmonitor`, and restart Auth, the
workers and beat.

## Upgrading

Bump the tag in `conf/requirements.txt`, then:

```bash
docker compose build
docker compose --env-file=.env up -d
docker compose exec allianceauth_gunicorn bash -c \
  "python /home/allianceauth/myauth/manage.py migrate admmonitor"
```

## FAQ

**Where do the numbers come from?**
ESI's sovereignty systems endpoint (`GetSovereigntySystems`): each alliance claim carries a
development block with `activity_defense_multiplier` (the ADM) and the
military/industrial/strategic index levels.

**Why didn't I get an immediate alert for a system that's been low for weeks?**
Immediate alerts only fire on *new* drops below the threshold. Long-standing low systems
appear in the daily report. Use the *Reset immediate-alert state* admin action on a system
if you want it to alert again without recovering first.

**What timezone is the daily report time?**
UTC, i.e. EVE time.

**Does this need an ESI token?**
No. All endpoints used are public.

## License

MIT
