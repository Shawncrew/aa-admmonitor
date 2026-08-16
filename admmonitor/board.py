"""Rendering and publishing of the Discord status board.

The board is a set of plain-text messages listing every monitored system
currently below the ADM threshold, grouped by constellation, with the Discord
roles of the Auth groups assigned to that constellation pinged right after the
constellation name.

Publishing purges the channel first, so the board is always the only thing in it
and always reflects the current state instead of a trail of stale alerts.
"""

import hashlib
import logging
import re
from collections import defaultdict

from django.utils import timezone

from . import discordapi
from .models import MonitoredConstellation, StatusBoardMessage, SystemAdmStatus

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 1900  # Discord's limit is 2000; leave room for the wrapper
MAX_PURGE_PAGES = 10  # up to 1000 messages per run
ROLE_MENTION_RE = re.compile(r"<@&(\d+)>")


def board_signature(config) -> tuple:
    """Hash the state the board displays, plus the rows it was built from.

    Computed straight from the database so an unchanged board can be detected
    without calling Discord at all. Group assignments are part of the hash, so
    reassigning a constellation also triggers a repost.
    """
    below = list(
        SystemAdmStatus.objects.filter(below_threshold=True)
        .select_related("constellation")
        .order_by("adm", "system_name")
    )
    assignments = {
        constellation.pk: (
            sorted(group.pk for group in constellation.groups.all()),
            constellation.extra_mentions,
        )
        for constellation in MonitoredConstellation.objects.filter(systems__in=below)
        .distinct()
        .prefetch_related("groups")
    }
    parts = [f"threshold={config.threshold:g}", f"mentions={config.mention_groups}"]
    parts += [
        f"{row.system_id}:{row.adm:.2f}:{row.constellation_id}"
        f":{assignments.get(row.constellation_id, '')}"
        for row in below
    ]
    signature = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return below, signature


def build_board(config, below: list) -> tuple:
    """Render the board into ``(messages, role_ids, allow_everyone)``."""
    mention_map, role_ids, allow_everyone = _mentions_by_constellation(config, below)

    stamp = int(timezone.now().timestamp())
    header = (
        f"## 🛡️ ADM Status Board\n"
        f"Systems below ADM **{config.threshold:g}** · updated <t:{stamp}:f>"
    )

    if not below:
        body = ["✅ All monitored systems are at or above the threshold. o7"]
    else:
        body = _constellation_blocks(below, mention_map)

    return _split_messages(header, body), role_ids, allow_everyone


def _constellation_blocks(below: list, mention_map: dict) -> list:
    """One text block per constellation, ordered by its worst ADM."""
    by_constellation = defaultdict(list)
    for row in below:
        by_constellation[row.constellation].append(row)

    def sort_key(item):
        constellation, rows = item
        return (min(row.adm for row in rows), str(constellation or "zz"))

    blocks = []
    for constellation, rows in sorted(by_constellation.items(), key=sort_key):
        if constellation is None:
            heading = "**Unassigned systems**"
        else:
            region = f" · {constellation.region_name}" if constellation.region_name else ""
            heading = f"**{constellation.name}**{region}"
        mentions = mention_map.get(
            constellation.constellation_id if constellation else None, ""
        )
        if mentions:
            heading = f"{heading} {mentions}"
        lines = [heading]
        lines += [f"> {_format_system_line(row)}" for row in rows]
        blocks.append("\n".join(lines))
    return blocks


def _format_system_line(row: SystemAdmStatus) -> str:
    line = f"**{row.system_name}** — ADM **{row.adm:.1f}**"
    if row.military_level is not None:
        line += (
            f" · Mil {row.military_level}"
            f" / Ind {row.industrial_level}"
            f" / Str {row.strategic_level}"
        )
    if row.alliance_name:
        line += f" — {row.alliance_name}"
    return line


def _mentions_by_constellation(config, below: list) -> tuple:
    """Build ``{constellation_id: "<@&1> <@&2>"}`` for the constellations shown.

    Auth groups are matched to Discord roles by name (which is how the Auth
    Discord service names them); `extra_mentions` covers anything that does not
    match. Returns the mention strings plus the role IDs and @everyone/@here
    flag needed for the message's allowed_mentions.
    """
    constellation_ids = {
        row.constellation.constellation_id for row in below if row.constellation
    }
    if not constellation_ids:
        return {}, [], False

    roles_by_name = {}
    if config.mention_groups:
        guild = discordapi.guild_id(config)
        token = discordapi.bot_token(config)
        if guild and token:
            try:
                roles_by_name = discordapi.get_guild_roles(guild, token)
            except discordapi.DiscordError:
                logger.exception(
                    "Could not fetch Discord roles; posting the board without group "
                    "mentions"
                )
        else:
            logger.warning(
                "Group mentions are enabled but no Discord guild ID / bot token is "
                "configured; posting the board without group mentions"
            )

    mention_map = {}
    role_ids = set()
    allow_everyone = False
    constellations = MonitoredConstellation.objects.filter(
        constellation_id__in=constellation_ids
    ).prefetch_related("groups")
    for constellation in constellations:
        mentions = []
        if config.mention_groups:
            for group in constellation.groups.all():
                role_id = roles_by_name.get(group.name.strip().lower())
                if role_id is None:
                    logger.warning(
                        "No Discord role named '%s' for constellation %s; use "
                        "'extra mentions' to point at the right role",
                        group.name,
                        constellation.name,
                    )
                    continue
                mentions.append(f"<@&{role_id}>")
                role_ids.add(role_id)
        extra = constellation.extra_mentions.strip()
        if extra:
            mentions.append(extra)
            role_ids.update(int(rid) for rid in ROLE_MENTION_RE.findall(extra))
            if "@everyone" in extra or "@here" in extra:
                allow_everyone = True
        if mentions:
            mention_map[constellation.constellation_id] = " ".join(mentions)
    return mention_map, sorted(role_ids), allow_everyone


def _split_messages(header: str, blocks: list) -> list:
    """Pack the blocks into as few messages as possible without splitting a block."""
    messages = []
    current = [header]
    current_len = len(header)
    # Reserve room for the header so an oversized block never strands it in a
    # message of its own.
    block_cap = MAX_MESSAGE_LENGTH - len(header) - 20
    for block in blocks:
        if len(block) > block_cap:
            block = block[:block_cap].rstrip() + "\n> … (truncated)"
        if current_len + len(block) + 2 > MAX_MESSAGE_LENGTH:
            messages.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(block)
        current_len += len(block) + 2
    if current:
        messages.append("\n\n".join(current))
    return messages


def publish_board(config, force: bool = False) -> bool:
    """Purge the channel and repost the board. Returns True if it was reposted.

    Returns False (without touching the channel) when the content is unchanged
    and `force` is not set, so an unchanged board never re-pings anyone.
    """
    token = discordapi.bot_token(config)
    if not token or not config.discord_channel_id:
        logger.error(
            "The status board needs a Discord bot token and channel ID; configure "
            "them in the ADM Monitor configuration."
        )
        return False

    below, signature = board_signature(config)
    if not force and signature == config.last_board_signature:
        logger.debug("ADM status board unchanged, leaving the channel alone")
        return False

    messages, role_ids, allow_everyone = build_board(config, below)
    channel_id = config.discord_channel_id
    try:
        _purge_channel(config, channel_id, token)
    except discordapi.DiscordError:
        logger.exception("Could not purge the status board channel, reposting anyway")

    allowed_mentions = {
        "parse": ["everyone"] if allow_everyone else [],
        "roles": [str(rid) for rid in role_ids[:100]],
        "users": [],
    }

    posted = []
    for position, content in enumerate(messages):
        try:
            message_id = discordapi.create_message(
                channel_id, token, content, allowed_mentions
            )
        except discordapi.DiscordError:
            logger.exception("Failed to post part %d of the status board", position + 1)
            break
        posted.append(
            StatusBoardMessage(
                channel_id=channel_id, message_id=message_id, position=position
            )
        )
    if not posted:
        return False

    StatusBoardMessage.objects.bulk_create(posted)
    config.last_board_signature = signature
    config.save(update_fields=["last_board_signature"])
    logger.info("ADM status board reposted as %d message(s)", len(posted))
    return True


def _purge_channel(config, channel_id: int, token: str):
    """Remove the previous board — either the whole channel or just our messages."""
    if config.purge_all_messages:
        message_ids = []
        before = None
        for _ in range(MAX_PURGE_PAGES):
            page = discordapi.get_channel_messages(channel_id, token, before=before)
            if not page:
                break
            message_ids += [entry["id"] for entry in page]
            before = page[-1]["id"]
            if len(page) < 100:
                break
    else:
        message_ids = list(
            StatusBoardMessage.objects.filter(channel_id=channel_id).values_list(
                "message_id", flat=True
            )
        )

    if message_ids:
        discordapi.bulk_delete_messages(channel_id, message_ids, token)
    StatusBoardMessage.objects.filter(channel_id=channel_id).delete()
