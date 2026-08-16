# AA ADM Monitor

An [Alliance Auth](https://gitlab.com/allianceauth/allianceauth) plugin that monitors the
**ADM (Activity Defense Multiplier)** of your alliance's sovereignty systems via ESI and
keeps a live **status board** in a Discord channel listing every system below a
configurable threshold, grouped by constellation and pinging the groups responsible for it.

## Features

- **Status board instead of alert spam.** The plugin purges the channel and reposts a
  single current picture of every system below the threshold, **grouped by constellation**.
  There is never a trail of stale alerts to scroll through — what's in the channel *is* the
  current state.
- **Constellation → group assignments.** Every constellation holding at least one system
  claimed by a monitored alliance shows up automatically in the admin. Assign any number of
  Auth **groups** (usually corporations) to each constellation; a group can own several
  constellations and a constellation can have several groups.
- **Targeted pings.** The Discord roles of the assigned groups are mentioned **right after
  the constellation name**, so each corp sees its own constellations highlighted.
- **Quiet when nothing changes.** The board is only reposted when the set of systems below
  the threshold actually changes (plus one daily refresh, so the board stays near the bottom
  of the channel).
- **Ignore constellations** you don't care about (staging, rentals) — still tracked in the
  admin, never reported.
- Per-system detail: current ADM plus the military / industrial / strategic index levels,
  region and owning alliance.
- Monitor one or more alliances (comma-separated alliance IDs); systems and constellations
  are picked up and dropped automatically as sovereignty changes — group assignments survive.
- All configuration lives in the **Alliance Auth admin panel** (`/admin/` → ADM Monitor).
- Uses only **public ESI** endpoints — no ESI tokens or scopes required.
- Falls back to the older append-only embed alerts (via allianceauth-discordbot or a
  webhook) if no Discord bot token is available.

### What the board looks like

```
## 🛡️ ADM Status Board
Systems below ADM 4.0 · updated 16 August 2026 14:15

**KVN-36** · Fountain @Corp Alpha @Corp Bravo
> **Y-2ANO** — ADM 2.4 · Mil 3 / Ind 1 / Str 2 — My Alliance
> **4-07MU** — ADM 3.1 · Mil 4 / Ind 2 / Str 2 — My Alliance

**B-7DFU** · Delve @Corp Charlie
> **319-3D** — ADM 3.6 · Mil 4 / Ind 3 / Str 1 — My Alliance
```

Constellations are ordered by their worst system, so the most urgent block is at the top.

## How it works

A single Celery task runs on a schedule you define (every 15 minutes recommended). Each run it:

1. Pulls the sovereignty systems list from ESI (`GetSovereigntySystems`) and keeps the
   systems claimed by your configured alliance(s), reading the ADM and the
   military/industrial/strategic levels from each claim's development block.
2. Updates the per-system state table. For systems it hasn't seen before it resolves
   system → constellation → region once via ESI and creates the constellation row that you
   then assign groups to.
3. Renders the board and compares it with what's currently posted. If it changed (or the
   daily refresh is due), it **deletes the messages in the channel** and posts the new board,
   pinging the roles of the groups assigned to each affected constellation.

### How groups become Discord pings

Auth groups are matched to Discord roles **by name**, which is how Auth's own Discord
service names the roles it manages — an Auth group `Corp Alpha` pings the Discord role
`Corp Alpha`. If a role is named differently, put the raw mention in the constellation's
**Extra mentions** field (e.g. `<@&123456789012345678>`, or `@here`); it is appended after
the group pings. Unmatched groups are logged as a warning and skipped rather than failing
the run.

> **Note on re-pinging:** because the board is deleted and reposted, every constellation
> that currently has a system below the threshold is pinged again on each repost — not just
> the constellation that changed. Reposts only happen when the content actually changes, so
> a steady state is silent. If you want even fewer pings, turn *Repost on change* off and
> leave only the daily refresh.

---

## Installation (aa-docker / dockerized Alliance Auth)

These steps assume the standard [aa-docker](https://gitlab.com/allianceauth/allianceauth/-/tree/master/docker)
layout at `/opt/allianceauth/aa-docker` with your config in `conf/`.

### 1. Add the package

Append to `conf/requirements.txt`:

```
aa-admmonitor @ git+https://github.com/Shawncrew/aa-admmonitor.git@v0.2.0
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

### 5. Restart the workers and beat

```bash
docker compose restart allianceauth_worker_beat
docker compose restart $(docker compose ps --services | grep worker)
```

### 6. Give the bot the right channel permissions

The status board needs a **bot token** (it has to delete messages, which webhooks and
allianceauth-discordbot cannot do). If you already run Auth's Discord service or
allianceauth-discordbot, `DISCORD_BOT_TOKEN` and `DISCORD_GUILD_ID` are already in your
`local.py` and the plugin picks them up automatically — otherwise set them in the plugin
config.

In Discord, the bot needs these permissions **in the board channel**:

| Permission | Why |
|---|---|
| View Channel | read the channel |
| Send Messages | post the board |
| Manage Messages | delete the previous board |
| Mention @everyone, @here and All Roles | ping roles that aren't set "mentionable" |

Give the channel its own dedicated home — with *Purge all messages* on (the default) the
plugin removes **everything** in it on each repost.

### 7. Configure in the admin panel

Open your Auth site → **Admin** → **ADM Monitor** → **ADM Monitor Configuration** → *Add*:

| Setting | Description |
|---|---|
| **Enabled** | Master switch for the whole monitor. |
| **Threshold** | Systems with ADM strictly below this value are reported (e.g. `4.0`). |
| **Alliance IDs** | Comma-separated alliance IDs to monitor, e.g. `99003581`. Leave blank to monitor *all* sov systems in the game (not recommended). |
| **Discord channel ID** | Channel the board lives in. Developer Mode → right-click the channel → *Copy ID*. |
| **Discord bot token** | Leave blank to use the `DISCORD_BOT_TOKEN` setting. |
| **Discord server (guild) ID** | Leave blank to use the `DISCORD_GUILD_ID` setting. Used to resolve groups to roles. |
| **Webhook URL (fallback)** | Optional, only used for the append-only fallback mode. |
| **Status board enabled** | Purge-and-repost mode. Off = the old append-only alerts. |
| **Purge all messages** | On: delete *every* message in the channel on repost. Off: delete only the board messages this plugin posted. |
| **Mention groups** | Ping the roles of the groups assigned to each constellation. |
| **Repost on change** | Repost (and re-ping) as soon as the list of below-threshold systems changes. |
| **Daily refresh enabled / time** | Repost once a day even when nothing changed, at this time in **EVE time (UTC)**. |

### 8. Assign constellations to groups

Run **ADM Monitor Configuration → Run ADM check now** once. The plugin then populates
**Admin → ADM Monitor → Monitored Constellations** with every constellation holding at
least one of your systems, showing the system count, how many are below the threshold and
the lowest ADM in it.

Open a constellation and pick its **Alerted groups** (the Auth groups to ping). Add
**Extra mentions** if a group's Discord role has a different name. Constellations without a
group still appear on the board — just without a ping.

**Ignoring a constellation.** Tick **Ignored** to drop a constellation out of reporting
entirely — staging systems, rentals, anything you don't want cluttering the board. Its
systems are still polled and still visible in *System ADM Statuses*, but they never appear
on the board and never trigger an alert, however low the ADM gets. The flag is editable
straight from the constellation list (or in bulk via the *Ignore selected* /
*Stop ignoring selected* actions), and the board is reposted without them on the next check.

### 9. Test it

On the configuration page itself there is a **Save and run ADM check now** button
below the save row. It saves your edits first, then queues the check — so a threshold or
channel you just changed is already in effect when it runs.

For the rest, on the configuration *list* page tick the config and use the admin actions:

- **Send test message to Discord** — verifies delivery end-to-end.
- **Run ADM check now** — queues an immediate ESI refresh and board update.
- **Repost status board now** — forces a purge + repost regardless of changes.

Worker logs if something misbehaves:

```bash
docker compose logs -f --tail=100 allianceauth_worker
```

---

## Installation (bare metal / venv)

```bash
pip install git+https://github.com/Shawncrew/aa-admmonitor.git@v0.2.0
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

### Upgrading from 0.1.x

Existing system rows are backfilled with their constellation on the next run (one extra ESI
lookup per system, once). Set the bot token / guild ID if they aren't already in `local.py`,
give the bot *Manage Messages* in the board channel, then assign your constellations to
groups. Until you do, the board posts with no pings — nothing breaks.

## FAQ

**Where do the numbers come from?**
ESI's sovereignty systems endpoint (`GetSovereigntySystems`): each alliance claim carries a
development block with `activity_defense_multiplier` (the ADM) and the
military/industrial/strategic index levels.

**Why is my group not being pinged?**
The Discord role must have the same name as the Auth group. Check the worker log for
`No Discord role named '...'`, and use the constellation's **Extra mentions** field for
roles that don't match by name.

**Can I keep other messages in the board channel?**
Yes — turn *Purge all messages* off. The plugin then only deletes the board messages it
posted itself (tracked in the DB), leaving everything else alone.

**What if I don't want to give the plugin a bot token?**
Turn *Status board enabled* off. The plugin falls back to the 0.1.x behaviour: append-only
embeds through allianceauth-discordbot or a webhook, with no purging and no group pings.

**What timezone is the daily refresh time?**
UTC, i.e. EVE time.

**Does this need an ESI token?**
No. All endpoints used are public.

## License

MIT
