"""Celery tasks for the ADM monitor.

A single periodic task (`run_admmonitor`, scheduled via CELERYBEAT_SCHEDULE in
local.py) refreshes ADM data from ESI and keeps the Discord status board in
sync: the channel is purged and the current list of systems below the threshold,
grouped by constellation and pinging the groups assigned to each constellation,
is reposted whenever it changes.

When no Discord bot token is available the monitor falls back to the older
append-only alerts (immediate alert + daily report embeds).
"""

import logging
from datetime import datetime, timedelta, timezone as dt_timezone

from celery import shared_task
from django.utils import timezone

from . import board, discordapi
from .models import AdmMonitorConfig, MonitoredConstellation, SystemAdmStatus
from .notify import COLOR_DANGER, COLOR_OK, COLOR_WARNING, send_alert
from .providers import esi

logger = logging.getLogger(__name__)

NAMES_CHUNK_SIZE = 500


def _get(obj, key, default=None):
    """Field access that works for both pydantic models and plain dicts."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


@shared_task(time_limit=900)
def run_admmonitor():
    """Main periodic task: refresh ADM data, then update the board / alerts."""
    config = AdmMonitorConfig.get_config()
    if config is None or not config.enabled:
        logger.debug("ADM monitor is not configured or disabled, skipping run")
        return

    try:
        update_adm_data(config)
    except Exception:
        # Keep last known data and retry on the next scheduled run.
        logger.exception("Failed to update ADM data from ESI, skipping this run")
        return

    if _board_available(config):
        refresh_status_board(config)
        return

    if config.immediate_alerts_enabled:
        send_immediate_alerts(config)
    if config.daily_report_enabled:
        check_daily_report(config)


@shared_task(time_limit=300)
def refresh_board_task(force: bool = True):
    """Repost the status board immediately (used by the admin action)."""
    config = AdmMonitorConfig.get_config()
    if config is None:
        return
    if _board_available(config):
        board.publish_board(config, force=force)
    else:
        send_daily_report_task()


@shared_task(time_limit=300)
def send_daily_report_task():
    """Send the legacy daily report immediately (fallback delivery)."""
    config = AdmMonitorConfig.get_config()
    if config is None:
        return
    if send_daily_report(config):
        config.last_daily_report_at = timezone.now()
        config.save(update_fields=["last_daily_report_at"])


def _board_available(config) -> bool:
    return bool(
        config.status_board_enabled
        and config.discord_channel_id
        and discordapi.bot_token(config)
    )


def refresh_status_board(config: AdmMonitorConfig):
    """Repost the board when it changed, or when the daily refresh is due."""
    force = config.daily_report_enabled and _daily_refresh_due(config)
    if not force and not config.immediate_alerts_enabled:
        return
    if board.publish_board(config, force=force) and force:
        config.last_daily_report_at = timezone.now()
        config.save(update_fields=["last_daily_report_at"])


def update_adm_data(config: AdmMonitorConfig):
    """Fetch sovereignty data from ESI and update per-system ADM state."""
    # use_etag=False: with ETags enabled the client raises HTTPNotModified on
    # unchanged data; we always want the payload (served from cache when fresh).
    data = esi.client.Sovereignty.GetSovereigntySystems().result(use_etag=False)
    allowed_alliances = config.alliance_id_set()

    # Keep alliance-claimed systems matching the filter. Each entry's 'claim'
    # is a union of faction / alliance / unclaimed shapes; only the alliance
    # shape carries the development indices (ADM, military/industrial/strategic).
    info_by_system = {}
    for entry in _get(data, "solar_systems") or []:
        claim = _get(entry, "claim")
        # aiopenapi3 wraps the faction/alliance/unclaimed union in a RootModel;
        # the actual variant object sits under '.root'.
        claim = _get(claim, "root", claim)
        alliance_claim = _get(claim, "alliance") if claim is not None else None
        if alliance_claim is None:
            continue
        alliance_id = _get(alliance_claim, "alliance_id")
        if allowed_alliances and alliance_id not in allowed_alliances:
            continue
        development = _get(alliance_claim, "development")
        info_by_system[_get(entry, "solar_system_id")] = {
            "alliance_id": alliance_id,
            "adm": _get(development, "activity_defense_multiplier", 1.0),
            "military_level": _get(development, "military_level"),
            "industrial_level": _get(development, "industrial_level"),
            "strategic_level": _get(development, "strategic_level"),
        }

    if allowed_alliances and not info_by_system:
        logger.warning(
            "No sovereignty systems matched the configured alliance IDs %s",
            sorted(allowed_alliances),
        )

    existing = {row.system_id: row for row in SystemAdmStatus.objects.all()}
    is_first_run = not existing

    # Drop systems that left scope (sov lost or filter changed). Their
    # constellations are kept so the group assignments survive.
    stale_ids = set(existing) - set(info_by_system)
    if stale_ids:
        SystemAdmStatus.objects.filter(system_id__in=stale_ids).delete()
        logger.info("Removed %d system(s) no longer in scope", len(stale_ids))

    # Resolve names for new systems and for all owner alliances (cheap, few IDs).
    new_system_ids = set(info_by_system) - set(existing)
    ids_to_resolve = list(new_system_ids) + [
        info["alliance_id"] for info in info_by_system.values() if info["alliance_id"]
    ]
    names = resolve_names(ids_to_resolve)

    now = timezone.now()
    threshold = config.threshold
    seen_constellations = set()
    for system_id, info in info_by_system.items():
        row = existing.get(system_id)
        if row is None:
            row = SystemAdmStatus(
                system_id=system_id,
                system_name=names.get(system_id, str(system_id)),
            )
        # Also backfills rows created before constellations were tracked.
        if row.constellation_id is None:
            constellation = resolve_constellation(system_id)
            if constellation is not None:
                row.constellation = constellation
                row.region_name = constellation.region_name
        if row.constellation_id is not None:
            seen_constellations.add(row.constellation_id)

        alliance_id = info["alliance_id"]
        row.alliance_id = alliance_id
        if alliance_id and alliance_id in names:
            row.alliance_name = names[alliance_id]

        adm = info["adm"]
        row.adm = adm
        row.military_level = info["military_level"]
        row.industrial_level = info["industrial_level"]
        row.strategic_level = info["strategic_level"]
        was_below = row.below_threshold
        is_below = adm < threshold
        if is_below and not was_below:
            row.below_threshold = True
            row.first_seen_below = now
            # On the very first run after install treat the current state as
            # baseline so a fresh install doesn't blast alerts for systems
            # that have been below the threshold for a long time already.
            if is_first_run:
                row.immediate_alert_sent = True
        elif not is_below and was_below:
            # Recovered: allow a future immediate alert again.
            row.below_threshold = False
            row.immediate_alert_sent = False
            row.first_seen_below = None
        row.save()

    if seen_constellations:
        MonitoredConstellation.objects.filter(pk__in=seen_constellations).update(
            last_seen_at=now
        )

    logger.info(
        "ADM data updated: %d system(s) in %d constellation(s), %d below threshold %g",
        len(info_by_system),
        len(seen_constellations),
        SystemAdmStatus.objects.filter(below_threshold=True).count(),
        threshold,
    )


def send_immediate_alerts(config: AdmMonitorConfig):
    """Alert once for every system that newly dropped below the threshold."""
    pending = list(
        SystemAdmStatus.objects.filter(
            below_threshold=True, immediate_alert_sent=False
        ).order_by("adm", "system_name")
    )
    if not pending:
        return

    show_alliance = len(config.alliance_id_set()) != 1
    lines = [format_system_line(row, show_alliance) for row in pending]
    title = (
        f"⚠️ ADM Alert — {len(pending)} system(s) dropped below {config.threshold:g}"
    )
    if send_alert(config, title, lines, COLOR_DANGER):
        SystemAdmStatus.objects.filter(pk__in=[row.pk for row in pending]).update(
            immediate_alert_sent=True
        )
        logger.info("Immediate alert sent for %d system(s)", len(pending))
    else:
        logger.error("Immediate alert could not be sent, will retry next run")


def _daily_refresh_due(config: AdmMonitorConfig) -> bool:
    """True on the first run at/after the configured UTC time each day."""
    now = timezone.now().astimezone(dt_timezone.utc)
    scheduled_today = datetime.combine(
        now.date(), config.daily_report_time, tzinfo=dt_timezone.utc
    )
    last_due = (
        scheduled_today
        if now >= scheduled_today
        else scheduled_today - timedelta(days=1)
    )
    return not (
        config.last_daily_report_at and config.last_daily_report_at >= last_due
    )


def check_daily_report(config: AdmMonitorConfig):
    """Send the legacy daily report on the first run at/after the configured time."""
    if not _daily_refresh_due(config):
        return  # already sent for the current cycle

    if send_daily_report(config):
        config.last_daily_report_at = timezone.now()
        config.save(update_fields=["last_daily_report_at"])
        logger.info("Daily ADM report sent")
    else:
        logger.error("Daily ADM report could not be sent, will retry next run")


def send_daily_report(config: AdmMonitorConfig) -> bool:
    below = list(
        SystemAdmStatus.objects.filter(below_threshold=True).order_by(
            "adm", "system_name"
        )
    )
    if below:
        show_alliance = len(config.alliance_id_set()) != 1
        lines = [format_system_line(row, show_alliance) for row in below]
        title = (
            f"📊 Daily ADM Report — {len(below)} system(s) below {config.threshold:g}"
        )
        return send_alert(config, title, lines, COLOR_WARNING)

    title = f"📊 Daily ADM Report — all systems at or above {config.threshold:g}"
    lines = ["All monitored systems are at or above the configured ADM threshold. o7"]
    return send_alert(config, title, lines, COLOR_OK)


def format_system_line(row: SystemAdmStatus, show_alliance: bool) -> str:
    region = f" ({row.region_name})" if row.region_name else ""
    line = f"**{row.system_name}**{region} — ADM **{row.adm:.1f}**"
    if row.military_level is not None:
        line += (
            f" · Mil {row.military_level}"
            f" / Ind {row.industrial_level}"
            f" / Str {row.strategic_level}"
        )
    if show_alliance and row.alliance_name:
        line += f" — {row.alliance_name}"
    return line


def resolve_names(ids: list) -> dict:
    """Resolve EVE IDs (systems, alliances, ...) to names via ESI."""
    ids = sorted(set(ids))
    names = {}
    for offset in range(0, len(ids), NAMES_CHUNK_SIZE):
        chunk = ids[offset : offset + NAMES_CHUNK_SIZE]
        try:
            results = esi.client.Universe.PostUniverseNames(body=chunk).result(
                use_etag=False
            )
        except Exception:
            logger.exception("Failed to resolve names for IDs %s", chunk)
            continue
        for entry in results:
            names[_get(entry, "id")] = _get(entry, "name")
    return names


def resolve_constellation(system_id: int):
    """Get (creating if needed) the MonitoredConstellation a system sits in.

    Walks system -> constellation -> region in ESI. Only called for systems that
    are new (or predate constellation tracking), so this stays cheap.
    """
    try:
        system = esi.client.Universe.GetUniverseSystemsSystemId(
            system_id=system_id
        ).result(use_etag=False)
        constellation_id = _get(system, "constellation_id")
        constellation = esi.client.Universe.GetUniverseConstellationsConstellationId(
            constellation_id=constellation_id
        ).result(use_etag=False)
        region = esi.client.Universe.GetUniverseRegionsRegionId(
            region_id=_get(constellation, "region_id")
        ).result(use_etag=False)
    except Exception:
        logger.warning("Could not resolve constellation for system %s", system_id)
        return None

    row, _created = MonitoredConstellation.objects.get_or_create(
        constellation_id=constellation_id,
        defaults={
            "name": _get(constellation, "name", str(constellation_id)),
            "region_name": _get(region, "name", ""),
        },
    )
    return row
