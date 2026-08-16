"""Minimal Discord REST client used to maintain the status board.

allianceauth-discordbot can only *send* messages, so purging the channel and
resolving Auth groups to Discord roles is done with plain REST calls using a bot
token. The token is taken from the plugin config, falling back to the
DISCORD_BOT_TOKEN setting that the Auth Discord service already uses.
"""

import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

API_BASE = "https://discord.com/api/v10"
TIMEOUT = 30
MAX_RETRIES = 3

# Messages older than 14 days cannot be bulk-deleted; they need one call each.
BULK_DELETE_MIN = 2
BULK_DELETE_MAX = 100


class DiscordError(Exception):
    """Any non-recoverable failure talking to the Discord API."""


def bot_token(config) -> str:
    return config.discord_bot_token or getattr(settings, "DISCORD_BOT_TOKEN", "") or ""


def guild_id(config):
    return config.discord_guild_id or getattr(settings, "DISCORD_GUILD_ID", None)


def _request(method: str, path: str, token: str, **kwargs):
    """Call the Discord API, honouring 429 rate limits."""
    url = f"{API_BASE}{path}"
    headers = {
        "Authorization": f"Bot {token}",
        "User-Agent": "aa-admmonitor (https://github.com/Shawncrew/aa-admmonitor)",
    }
    for attempt in range(MAX_RETRIES):
        response = requests.request(
            method, url, headers=headers, timeout=TIMEOUT, **kwargs
        )
        if response.status_code == 429:
            retry_after = 1.0
            try:
                retry_after = float(response.json().get("retry_after", 1.0))
            except ValueError:
                pass
            # Cap the wait so a bad bucket cannot stall the whole Celery task.
            time.sleep(min(retry_after, 10.0))
            continue
        if response.status_code >= 400:
            raise DiscordError(
                f"{method} {path} failed with HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()
    raise DiscordError(f"{method} {path} still rate limited after {MAX_RETRIES} tries")


def get_channel_messages(channel_id: int, token: str, before=None) -> list:
    """One page of messages, newest first (Discord caps a page at 100).

    Pass the ID of the last entry as `before` to walk further back.
    """
    params = {"limit": 100}
    if before:
        params["before"] = before
    return _request(
        "GET", f"/channels/{channel_id}/messages", token, params=params
    ) or []


def delete_message(channel_id: int, message_id: int, token: str):
    try:
        _request("DELETE", f"/channels/{channel_id}/messages/{message_id}", token)
    except DiscordError as exc:
        # Already gone (someone deleted it by hand) is not worth failing over.
        logger.debug("Could not delete message %s: %s", message_id, exc)


def bulk_delete_messages(channel_id: int, message_ids: list, token: str):
    """Delete the given messages, using the bulk endpoint where possible."""
    ids = [str(mid) for mid in message_ids]
    while len(ids) >= BULK_DELETE_MIN:
        chunk, ids = ids[:BULK_DELETE_MAX], ids[BULK_DELETE_MAX:]
        try:
            _request(
                "POST",
                f"/channels/{channel_id}/messages/bulk-delete",
                token,
                json={"messages": chunk},
            )
        except DiscordError as exc:
            # Bulk delete rejects the whole batch if any message is >14 days old.
            logger.debug("Bulk delete failed (%s), falling back to single deletes", exc)
            for message_id in chunk:
                delete_message(channel_id, message_id, token)
    for message_id in ids:
        delete_message(channel_id, message_id, token)


def create_message(
    channel_id: int, token: str, content: str, allowed_mentions: dict = None
) -> int:
    """Post a plain-text message and return its ID."""
    payload = {"content": content}
    if allowed_mentions is not None:
        payload["allowed_mentions"] = allowed_mentions
    result = _request("POST", f"/channels/{channel_id}/messages", token, json=payload)
    return int(result["id"])


def get_guild_roles(guild: int, token: str) -> dict:
    """Map lower-cased role name -> role ID for the guild."""
    roles = _request("GET", f"/guilds/{guild}/roles", token) or []
    return {role["name"].strip().lower(): int(role["id"]) for role in roles}


def get_bot_user_id(token: str) -> int:
    return int(_request("GET", "/users/@me", token)["id"])
