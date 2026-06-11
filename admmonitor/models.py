from datetime import time

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
            "Channel the alerts are sent to via allianceauth-discordbot. "
            "Enable Developer Mode in Discord, right-click the channel and 'Copy ID'. "
            "The bot must be able to see and write in this channel."
        ),
    )
    webhook_url = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name="Webhook URL (fallback)",
        help_text=(
            "Optional Discord webhook used when allianceauth-discordbot is not "
            "installed or sending via the bot fails."
        ),
    )

    daily_report_enabled = models.BooleanField(
        default=True,
        help_text="Send a daily report listing all systems below the threshold.",
    )
    daily_report_time = models.TimeField(
        default=time(12, 0),
        help_text=(
            "Time of day (EVE time / UTC) the daily report is sent. The report goes "
            "out on the first monitor run at or after this time."
        ),
    )
    immediate_alerts_enabled = models.BooleanField(
        default=True,
        help_text=(
            "Alert as soon as a system newly drops below the threshold. Each system "
            "alerts only once; it can alert again only after recovering to or above "
            "the threshold and dropping below it again."
        ),
    )

    last_daily_report_at = models.DateTimeField(
        null=True, blank=True, editable=False
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


class SystemAdmStatus(models.Model):
    """Last known ADM and alert state for one monitored solar system."""

    system_id = models.BigIntegerField(unique=True)
    system_name = models.CharField(max_length=100)
    region_name = models.CharField(max_length=100, blank=True, default="")
    alliance_id = models.BigIntegerField(null=True, blank=True)
    alliance_name = models.CharField(max_length=255, blank=True, default="")

    adm = models.FloatField(verbose_name="ADM")
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
