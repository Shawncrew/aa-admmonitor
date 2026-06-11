import datetime

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AdmMonitorConfig",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "enabled",
                    models.BooleanField(
                        default=True,
                        help_text="Master switch. When disabled, no ESI polling or alerting happens.",
                    ),
                ),
                (
                    "threshold",
                    models.FloatField(
                        default=4.0,
                        help_text="Systems with an ADM strictly below this value are reported (valid ADM range in EVE is 1.0 - 6.0).",
                    ),
                ),
                (
                    "alliance_ids",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Comma-separated EVE alliance IDs whose sovereignty systems should be monitored, e.g. '99003581, 1354830081'. Leave blank to monitor every sov nullsec system in the game (not recommended).",
                        max_length=255,
                        verbose_name="Alliance IDs",
                    ),
                ),
                (
                    "discord_channel_id",
                    models.BigIntegerField(
                        blank=True,
                        help_text="Channel the alerts are sent to via allianceauth-discordbot. Enable Developer Mode in Discord, right-click the channel and 'Copy ID'. The bot must be able to see and write in this channel.",
                        null=True,
                        verbose_name="Discord channel ID",
                    ),
                ),
                (
                    "webhook_url",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Optional Discord webhook used when allianceauth-discordbot is not installed or sending via the bot fails.",
                        max_length=500,
                        verbose_name="Webhook URL (fallback)",
                    ),
                ),
                (
                    "daily_report_enabled",
                    models.BooleanField(
                        default=True,
                        help_text="Send a daily report listing all systems below the threshold.",
                    ),
                ),
                (
                    "daily_report_time",
                    models.TimeField(
                        default=datetime.time(12, 0),
                        help_text="Time of day (EVE time / UTC) the daily report is sent. The report goes out on the first monitor run at or after this time.",
                    ),
                ),
                (
                    "immediate_alerts_enabled",
                    models.BooleanField(
                        default=True,
                        help_text="Alert as soon as a system newly drops below the threshold. Each system alerts only once; it can alert again only after recovering to or above the threshold and dropping below it again.",
                    ),
                ),
                (
                    "last_daily_report_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
            ],
            options={
                "verbose_name": "ADM Monitor Configuration",
                "verbose_name_plural": "ADM Monitor Configuration",
            },
        ),
        migrations.CreateModel(
            name="SystemAdmStatus",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("system_id", models.BigIntegerField(unique=True)),
                ("system_name", models.CharField(max_length=100)),
                (
                    "region_name",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                ("alliance_id", models.BigIntegerField(blank=True, null=True)),
                (
                    "alliance_name",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("adm", models.FloatField(verbose_name="ADM")),
                ("below_threshold", models.BooleanField(default=False)),
                (
                    "immediate_alert_sent",
                    models.BooleanField(
                        default=False,
                        help_text="Set once an immediate alert went out for the current below-threshold episode. Resets when the system recovers above the threshold.",
                    ),
                ),
                ("first_seen_below", models.DateTimeField(blank=True, null=True)),
                ("last_updated", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["adm", "system_name"],
                "verbose_name": "System ADM Status",
                "verbose_name_plural": "System ADM Statuses",
            },
        ),
    ]
