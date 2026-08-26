from datetime import time

from django.contrib.auth.models import Group
from django.db import models
from django.db.models import Q


class AdmMonitorConfig(models.Model):
    """Singleton configuration for the ADM monitor, edited via the admin panel."""

    enabled = models.BooleanField(
        default=True,
        help_text="Master switch. When disabled, no ESI polling or alerting happens.",
    )
    adm_alerts_enabled = models.BooleanField(
        default=True,
        verbose_name="Alert on ADM",
        help_text="Report systems whose ADM falls below the ADM threshold.",
    )
    threshold = models.FloatField(
        default=4.0,
        verbose_name="ADM threshold",
        help_text=(
            "Systems with an ADM strictly below this value are reported "
            "(valid ADM range in EVE is 1.0 - 6.0)."
        ),
    )
    military_alerts_enabled = models.BooleanField(
        default=False,
        verbose_name="Alert on military index",
        help_text="Report systems whose military index falls below its threshold.",
    )
    military_threshold = models.IntegerField(
        default=5,
        verbose_name="Military index threshold",
        help_text=(
            "Systems with a military index strictly below this value are reported "
            "(index levels run 0 - 5)."
        ),
    )
    industry_alerts_enabled = models.BooleanField(
        default=False,
        verbose_name="Alert on industry index",
        help_text="Report systems whose industry index falls below its threshold.",
    )
    industry_threshold = models.IntegerField(
        default=5,
        verbose_name="Industry index threshold",
        help_text=(
            "Systems with an industry index strictly below this value are reported "
            "(index levels run 0 - 5)."
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
            "messages are deleted and the current list of systems failing an "
            "enabled criterion, grouped by constellation, is reposted. Requires a "
            "bot token."
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
    show_healthy_constellations = models.BooleanField(
        default=False,
        verbose_name="Show healthy constellations",
        help_text=(
            "Also list the constellations where every system passes every "
            "enabled criterion, ticked off at the bottom of the board. Their groups "
            "are named in plain text and are never pinged."
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
            "failing systems changes. With this off the board is only "
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

    def active_criteria(self) -> list:
        """The enabled alert criteria as ``(key, label, threshold)`` tuples."""
        criteria = []
        if self.adm_alerts_enabled:
            criteria.append(("adm", "ADM", self.threshold))
        if self.military_alerts_enabled:
            criteria.append(("military", "Military", self.military_threshold))
        if self.industry_alerts_enabled:
            criteria.append(("industry", "Industry", self.industry_threshold))
        return criteria

    def criteria_description(self) -> str:
        """Human-readable summary of what currently triggers an alert."""
        criteria = self.active_criteria()
        if not criteria:
            return "nothing — no alert criteria are enabled"
        return " or ".join(f"{label} < {value:g}" for _key, label, value in criteria)

    def evaluate(self, adm, military_level, industrial_level) -> list:
        """Which enabled criteria a system fails. An empty list means healthy.

        A metric ESI did not report (None) is treated as unknown and never
        counts as a failure, so a gap in the data cannot manufacture an alert.
        """
        failed = []
        if self.adm_alerts_enabled and adm is not None and adm < self.threshold:
            failed.append("adm")
        if (
            self.military_alerts_enabled
            and military_level is not None
            and military_level < self.military_threshold
        ):
            failed.append("military")
        if (
            self.industry_alerts_enabled
            and industrial_level is not None
            and industrial_level < self.industry_threshold
        ):
            failed.append("industry")
        return failed

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
            "The matching Discord roles are pinged when a system here fails an "
            "enabled alert criterion."
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
    ignored = models.BooleanField(
        default=False,
        verbose_name="Ignored",
        help_text=(
            "Exclude this constellation from all reporting. Its systems are still "
            "tracked and visible in System ADM Statuses, but they never appear on "
            "the status board and never trigger an alert, however low their ADM."
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
    below_threshold = models.BooleanField(
        default=False,
        verbose_name="Failing",
        help_text="Set when the system fails at least one enabled alert criterion.",
    )
    failed_checks = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text=(
            "Comma-separated keys of the criteria this system currently fails "
            "(adm, military, industry)."
        ),
    )
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

    def failed_list(self) -> list:
        return [key for key in self.failed_checks.split(",") if key]

    @classmethod
    def reportable_below(cls):
        """Systems failing an enabled criterion that should actually be reported.

        Excludes constellations flagged as ignored. Systems whose constellation
        could not be resolved are kept — they show up under 'Unassigned systems'
        rather than silently disappearing.
        """
        return cls.objects.filter(below_threshold=True).filter(
            Q(constellation__isnull=True) | Q(constellation__ignored=False)
        )


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
