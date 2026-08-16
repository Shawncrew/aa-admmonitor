from datetime import time

from django.contrib.auth.models import Group
from django.db import models


class AdmMonitorConfig(models.Model):
    """Singleton configuration for the ADM monitor, edited via the admin panel."""

    enabled = models.BooleanField(
        default=True,
        help_text="Master switch. When disabled, no ESI polling or alerting happens.",
    )
    threshold = models.FloatField(
        default=4.0,
        help_text=(
            "Systems with an ADM strictly below this value are reported "
            "(valid ADM range in EVE is 1.0 - 6.0)."
        ),
    )
    alliance_ids = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Alliance IDs",
        help_text=(
            "Comma-separated EVE alliance IDs whose sovereignty systems should be "
            "monitored, e.g. '99003581, 1354830081'. Leave blank to monitor every "
            "sov nullsec system in the game (not recommended)."
        ),
    )

    discord_channel_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name="Discord channel ID",
        help_text=(
            "Channel the status board lives in. Enable Developer Mode in Discord, "
            "right-click the channel and 'Copy ID'. The bot must be able to read, "
            "write and manage messages in this channel."
        ),
    )
    discord_bot_token = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Discord bot token",
        help_text=(
            "Bot token used to purge and repost the status board. Leave blank to use "
            "the DISCORD_BOT_TOKEN setting from your Auth config. Without a token the "
            "monitor falls back to plain (append-only) alerts."
        ),
    )
    discord_guild_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name="Discord server (guild) ID",
        help_text=(
            "Server the channel belongs to, used to resolve Auth groups to Discord "
            "roles by name. Leave blank to use the DISCORD_GUILD_ID setting."
        ),
    )
    webhook_url = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name="Webhook URL (fallback)",
        help_text=(
            "Optional Discord webhook used when no bot token is available and "
            "allianceauth-discordbot is not installed."
        ),
    )

    status_board_enabled = models.BooleanField(
        default=True,
        help_text=(
            "Maintain a single up-to-date status board in the channel: existing "
            "messages are deleted and the current list of systems below the "
            "threshold, grouped by constellation, is reposted. Requires a bot token."
        ),
    )
    purge_all_messages = models.BooleanField(
        default=True,
        help_text=(
            "When reposting the board, delete every message in the channel. Turn this "
            "off to delete only the board messages this plugin posted, leaving other "
            "messages in the channel untouched."
        ),
    )
    mention_groups = models.BooleanField(
        default=True,
        help_text=(
            "Ping the Discord roles matching the Auth groups assigned to each "
            "constellation. The mentions are rendered right after the constellation "
            "name."
        ),
    )

    daily_report_enabled = models.BooleanField(
        default=True,
        verbose_name="Daily refresh enabled",
        help_text=(
            "Repost the board once a day even when nothing changed, so the roles get "
            "pinged again and the board stays near the bottom of the channel."
        ),
    )
    daily_report_time = models.TimeField(
        default=time(12, 0),
        verbose_name="Daily refresh time",
        help_text=(
            "Time of day (EVE time / UTC) of the daily repost. It goes out on the "
            "first monitor run at or after this time."
        ),
    )
    immediate_alerts_enabled = models.BooleanField(
        default=True,
        verbose_name="Repost on change",
        help_text=(
            "Repost the board (and re-ping the assigned groups) as soon as the set of "
            "systems below the threshold changes. With this off the board is only "
            "refreshed at the daily refresh time."
        ),
    )

    last_daily_report_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_board_signature = models.CharField(
        max_length=64, blank=True, default="", editable=False
    )

    class Meta:
        verbose_name = "ADM Monitor Configuration"
        verbose_name_plural = "ADM Monitor Configuration"

    def __str__(self) -> str:
        return "ADM Monitor Configuration"

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce singleton
        super().save(*args, **kwargs)

    @classmethod
    def get_config(cls):
        return cls.objects.first()

    def alliance_id_set(self) -> set:
        """Parse the comma-separated alliance ID filter into a set of ints."""
        result = set()
        for part in self.alliance_ids.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                result.add(int(part))
            except ValueError:
                pass
        return result


class MonitoredConstellation(models.Model):
    """A constellation holding at least one system claimed by a monitored alliance.

    Rows are created automatically as sovereignty data is refreshed; the group
    assignment is what admins edit here. Rows are kept even when the alliance
    loses every system in the constellation, so the assignment survives.
    """

    constellation_id = models.BigIntegerField(unique=True)
    name = models.CharField(max_length=100)
    region_name = models.CharField(max_length=100, blank=True, default="")
    groups = models.ManyToManyField(
        Group,
        blank=True,
        related_name="admmonitor_constellations",
        verbose_name="Alerted groups",
        help_text=(
            "Auth groups (usually corporations) responsible for this constellation. "
            "The matching Discord roles are pinged when a system here drops below "
            "the threshold."
        ),
    )
    extra_mentions = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "Optional raw mentions appended after the group pings, e.g. "
            "'<@&123456789012345678> @here'. Use this when a group's Discord role "
            "has a different name than the Auth group."
        ),
    )
    last_seen_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["region_name", "name"]
        verbose_name = "Monitored Constellation"
        verbose_name_plural = "Monitored Constellations"

    def __str__(self) -> str:
        if self.region_name:
            return f"{self.name} ({self.region_name})"
        return self.name


class SystemAdmStatus(models.Model):
    """Last known ADM and alert state for one monitored solar system."""

    system_id = models.BigIntegerField(unique=True)
    system_name = models.CharField(max_length=100)
    region_name = models.CharField(max_length=100, blank=True, default="")
    constellation = models.ForeignKey(
        MonitoredConstellation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="systems",
    )
    alliance_id = models.BigIntegerField(null=True, blank=True)
    alliance_name = models.CharField(max_length=255, blank=True, default="")

    adm = models.FloatField(verbose_name="ADM")
    military_level = models.IntegerField(null=True, blank=True)
    industrial_level = models.IntegerField(null=True, blank=True)
    strategic_level = models.IntegerField(null=True, blank=True)
    below_threshold = models.BooleanField(default=False)
    immediate_alert_sent = models.BooleanField(
        default=False,
        help_text=(
            "Set once an immediate alert went out for the current below-threshold "
            "episode. Resets when the system recovers above the threshold."
        ),
    )
    first_seen_below = models.DateTimeField(null=True, blank=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["adm", "system_name"]
        verbose_name = "System ADM Status"
        verbose_name_plural = "System ADM Statuses"

    def __str__(self) -> str:
        return f"{self.system_name} (ADM {self.adm:g})"


class StatusBoardMessage(models.Model):
    """A Discord message currently making up the status board.

    Tracked so the board can be cleaned up again even when purging is limited to
    this plugin's own messages.
    """

    channel_id = models.BigIntegerField()
    message_id = models.BigIntegerField(unique=True)
    position = models.IntegerField(default=0)
    posted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "Status Board Message"
        verbose_name_plural = "Status Board Messages"

    def __str__(self) -> str:
        return f"message {self.message_id} in channel {self.channel_id}"
