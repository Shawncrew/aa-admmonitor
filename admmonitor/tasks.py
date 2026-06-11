"""Celery tasks for the ADM monitor.

A single periodic task (`run_admmonitor`, scheduled via CELERYBEAT_SCHEDULE in
local.py) refreshes ADM data from ESI, fires immediate alerts for systems that
newly dropped below the threshold, and sends the daily report once the
configured time of day (UTC) has passed.
"""

import logging
from datetime import datetime, timedelta, timezone as dt_timezone

from celery import shared_task
from django.utils import timezone

from .models import AdmMonitorConfig, SystemAdmStatus
from .notify import COLOR_DANGER, COLOR_OK, COLOR_WARNING, send_alert
from .providers import esi

logger = logging.getLogger(__name__)

NAMES_CHUNK_SIZE = 500


@shared_task(time_limit=900)
def run_admmonitor():
    """Main periodic task: refresh ADM data, then handle alerting."""
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

    if config.immediate_alerts_enabled:
        send_immediate_alerts(config)
    if config.daily_report_enabled:
        check_daily_report(config)


@shared_task(time_limit=300)
def send_daily_report_task():
    """Send the daily report immediately (used by the admin action)."""
    config = AdmMonitorConfig.get_config()
    if config is None:
        return
    if send_daily_report(config):
        config.last_daily_report_at = timezone.now()
        config.save(update_fields=["last_daily_report_at"])


def update_adm_data(config: AdmMonitorConfig):
    """Fetch sov structures from ESI and update per-system ADM state."""
    structures = esi.client.Sovereignty.get_sovereignty_structures().results()
    allowed_alliances = config.alliance_id_set()

    adm_by_system = {}
    owner_by_system = {}
    for structure in structures:
        alliance_id = structure.get("alliance_id")
        if allowed_alliances and alliance_id not in allowed_alliances:
            continue
        system_id = structure["solar_system_id"]
        # The ADM is the 'vulnerability_occupancy_level'; absent means 1.0.
        adm = structure.get("vulnerability_occupancy_level") or 1.0
        if system_id not in adm_by_system or adm > adm_by_system[system_id]:
            adm_by_system[system_id] = adm
        owner_by_system[system_id] = alliance_id

    if allowed_alliances and not adm_by_system:
        logger.warning(
            "No sovereignty structures matched the configured alliance IDs %s",
            sorted(allowed_alliances),
        )

    existing = {row.system_id: row for row in SystemAdmStatus.objects.all()}
    is_first_run = not existing

    # Drop systems that left scope (sov lost or filter changed).
    stale_ids = set(existing) - set(adm_by_system)
    if stale_ids:
        SystemAdmStatus.objects.filter(system_id__in=stale_ids).delete()
        logger.info("Removed %d system(s) no longer in scope", len(stale_ids))

    # Resolve names for new systems and for all owner alliances (cheap, few IDs).
    new_system_ids = set(adm_by_system) - set(existing)
    ids_to_resolve = list(new_system_ids) + [
        aid for aid in set(owner_by_system.values()) if aid
    ]
    names = resolve_names(ids_to_resolve)

    now = timezone.now()
    threshold = config.threshold
    for system_id, adm in adm_by_system.items():
        row = existing.get(system_id)
        if row is None:
            row = SystemAdmStatus(
                system_id=system_id,
                system_name=names.get(system_id, str(system_id)),
                region_name=lookup_region_name(system_id),
            )
        alliance_id = owner_by_system.get(system_id)
        row.alliance_id = alliance_id
        if alliance_id and alliance_id in names:
            row.alliance_name = names[alliance_id]

        row.adm = adm
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

    logger.info(
        "ADM data updated: %d system(s) monitored, %d below threshold %g",
        len(adm_by_system),
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


def check_daily_report(config: AdmMonitorConfig):
    """Send the daily report on the first run at/after the configured UTC time."""
    now = timezone.now().astimezone(dt_timezone.utc)
    scheduled_today = datetime.combine(
        now.date(), config.daily_report_time, tzinfo=dt_timezone.utc
    )
    last_due = (
        scheduled_today if now >= scheduled_today else scheduled_today - timedelta(days=1)
    )
    if config.last_daily_report_at and config.last_daily_report_at >= last_due:
        return  # already sent for the current cycle

    if send_daily_report(config):
        config.last_daily_report_at = now
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
            results = esi.client.Universe.post_universe_names(ids=chunk).results()
        except Exception:
            logger.exception("Failed to resolve names for IDs %s", chunk)
            continue
        for entry in results:
            names[entry["id"]] = entry["name"]
    return names


def lookup_region_name(system_id: int) -> str:
    """Resolve a system's region name (system -> constellation -> region)."""
    try:
        system = esi.client.Universe.get_universe_systems_system_id(
            system_id=system_id
        ).results()
        constellation = esi.client.Universe.get_universe_constellations_constellation_id(
            constellation_id=system["constellation_id"]
        ).results()
        region = esi.client.Universe.get_universe_regions_region_id(
            region_id=constellation["region_id"]
        ).results()
        return region["name"]
    except Exception:
        logger.warning("Could not resolve region for system %s", system_id)
        return ""
