import datetime

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("admmonitor", "0002_development_indices"),
    ]

    operations = [
        migrations.CreateModel(
            name="MonitoredConstellation",
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
                ("constellation_id", models.BigIntegerField(unique=True)),
                ("name", models.CharField(max_length=100)),
                (
                    "region_name",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                (
                    "extra_mentions",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Optional raw mentions appended after the group pings, e.g. '<@&123456789012345678> @here'. Use this when a group's Discord role has a different name than the Auth group.",
                        max_length=255,
                    ),
                ),
                (
                    "last_seen_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "groups",
                    models.ManyToManyField(
                        blank=True,
                        help_text="Auth groups (usually corporations) responsible for this constellation. The matching Discord roles are pinged when a system here drops below the threshold.",
                        related_name="admmonitor_constellations",
                        to="auth.group",
                        verbose_name="Alerted groups",
                    ),
                ),
            ],
            options={
                "verbose_name": "Monitored Constellation",
                "verbose_name_plural": "Monitored Constellations",
                "ordering": ["region_name", "name"],
            },
        ),
        migrations.CreateModel(
            name="StatusBoardMessage",
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
                ("channel_id", models.BigIntegerField()),
                ("message_id", models.BigIntegerField(unique=True)),
                ("position", models.IntegerField(default=0)),
                ("posted_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Status Board Message",
                "verbose_name_plural": "Status Board Messages",
                "ordering": ["position", "id"],
            },
        ),
        migrations.AddField(
            model_name="systemadmstatus",
            name="constellation",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="systems",
                to="admmonitor.monitoredconstellation",
            ),
        ),
        migrations.AddField(
            model_name="admmonitorconfig",
            name="discord_bot_token",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Bot token used to purge and repost the status board. Leave blank to use the DISCORD_BOT_TOKEN setting from your Auth config. Without a token the monitor falls back to plain (append-only) alerts.",
                max_length=255,
                verbose_name="Discord bot token",
            ),
        ),
        migrations.AddField(
            model_name="admmonitorconfig",
            name="discord_guild_id",
            field=models.BigIntegerField(
                blank=True,
                help_text="Server the channel belongs to, used to resolve Auth groups to Discord roles by name. Leave blank to use the DISCORD_GUILD_ID setting.",
                null=True,
                verbose_name="Discord server (guild) ID",
            ),
        ),
        migrations.AddField(
            model_name="admmonitorconfig",
            name="status_board_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Maintain a single up-to-date status board in the channel: existing messages are deleted and the current list of systems below the threshold, grouped by constellation, is reposted. Requires a bot token.",
            ),
        ),
        migrations.AddField(
            model_name="admmonitorconfig",
            name="purge_all_messages",
            field=models.BooleanField(
                default=True,
                help_text="When reposting the board, delete every message in the channel. Turn this off to delete only the board messages this plugin posted, leaving other messages in the channel untouched.",
            ),
        ),
        migrations.AddField(
            model_name="admmonitorconfig",
            name="mention_groups",
            field=models.BooleanField(
                default=True,
                help_text="Ping the Discord roles matching the Auth groups assigned to each constellation. The mentions are rendered right after the constellation name.",
            ),
        ),
        migrations.AddField(
            model_name="admmonitorconfig",
            name="last_board_signature",
            field=models.CharField(
                blank=True, default="", editable=False, max_length=64
            ),
        ),
        migrations.AlterField(
            model_name="admmonitorconfig",
            name="discord_channel_id",
            field=models.BigIntegerField(
                blank=True,
                help_text="Channel the status board lives in. Enable Developer Mode in Discord, right-click the channel and 'Copy ID'. The bot must be able to read, write and manage messages in this channel.",
                null=True,
                verbose_name="Discord channel ID",
            ),
        ),
        migrations.AlterField(
            model_name="admmonitorconfig",
            name="webhook_url",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional Discord webhook used when no bot token is available and allianceauth-discordbot is not installed.",
                max_length=500,
                verbose_name="Webhook URL (fallback)",
            ),
        ),
        migrations.AlterField(
            model_name="admmonitorconfig",
            name="daily_report_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Repost the board once a day even when nothing changed, so the roles get pinged again and the board stays near the bottom of the channel.",
                verbose_name="Daily refresh enabled",
            ),
        ),
        migrations.AlterField(
            model_name="admmonitorconfig",
            name="daily_report_time",
            field=models.TimeField(
                default=datetime.time(12, 0),
                help_text="Time of day (EVE time / UTC) of the daily repost. It goes out on the first monitor run at or after this time.",
                verbose_name="Daily refresh time",
            ),
        ),
        migrations.AlterField(
            model_name="admmonitorconfig",
            name="immediate_alerts_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Repost the board (and re-ping the assigned groups) as soon as the set of systems below the threshold changes. With this off the board is only refreshed at the daily refresh time.",
                verbose_name="Repost on change",
            ),
        ),
    ]
