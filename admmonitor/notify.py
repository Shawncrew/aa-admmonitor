"""Discord delivery for ADM monitor alerts.

Preferred path is allianceauth-discordbot (channel ID), with a plain Discord
webhook as fallback. Both produce a single embed per message; long system
lists are split across multiple messages.
"""

import logging

import requests
from django.apps import apps as django_apps

logger = logging.getLogger(__name__)

COLOR_DANGER = 0xE74C3C
COLOR_WARNING = 0xF1C40F
COLOR_OK = 0x2ECC71
COLOR_INFO = 0x3498DB

FOOTER_TEXT = "aa-admmonitor"
MAX_DESCRIPTION = 3500  # stay safely below Discord's 4096 embed description limit


def send_alert(config, title: str, lines: list, color: int) -> bool:
    """Send one or more embeds containing the given lines. Returns True if all sent."""
    if not lines:
        lines = ["*Nothing to report.*"]

    chunks = []
    current = []
    current_len = 0
    for line in lines:
        if current and current_len + len(line) + 1 > MAX_DESCRIPTION:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))

    all_sent = True
    total = len(chunks)
    for index, description in enumerate(chunks):
        chunk_title = title if total == 1 else f"{title} ({index + 1}/{total})"
        all_sent = _send_embed(config, chunk_title, description, color) and all_sent
    return all_sent


def _send_embed(config, title: str, description: str, color: int) -> bool:
    if config.discord_channel_id and django_apps.is_installed("aadiscordbot"):
        try:
            _send_via_bot(config.discord_channel_id, title, description, color)
            return True
        except Exception:
            logger.exception(
                "Sending via allianceauth-discordbot failed, trying webhook fallback"
            )
    if config.webhook_url:
        try:
            _send_via_webhook(config.webhook_url, title, description, color)
            return True
        except Exception:
            logger.exception("Sending via Discord webhook failed")
            return False
    logger.error(
        "No usable Discord destination: set a channel ID (with allianceauth-discordbot "
        "installed) and/or a webhook URL in the ADM Monitor configuration."
    )
    return False


def _send_via_bot(channel_id: int, title: str, description: str, color: int):
    from aadiscordbot.tasks import send_message
    from discord import Embed

    embed = Embed(title=title, description=description, colour=color)
    embed.set_footer(text=FOOTER_TEXT)
    send_message(channel_id=channel_id, embed=embed)


def _send_via_webhook(url: str, title: str, description: str, color: int):
    payload = {
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
                "footer": {"text": FOOTER_TEXT},
            }
        ]
    }
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
