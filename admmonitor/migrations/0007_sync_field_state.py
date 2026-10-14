"""Sync help_text / verbose_name / related_name changes that had no migration.

State-only: none of these alter the database schema.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admmonitor", "0006_alert_criteria"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.AlterField(
            model_name="admmonitorconfig",
            name="immediate_alerts_enabled",
            field=models.BooleanField(default=True, help_text="Repost the board (and re-ping the assigned groups) as soon as the set of failing systems changes. With this off the board is only refreshed at the daily refresh time.", verbose_name="Repost on change"),
        ),
        migrations.AlterField(
            model_name="admmonitorconfig",
            name="show_healthy_constellations",
            field=models.BooleanField(default=False, help_text="Also list the constellations where every system passes every enabled criterion, ticked off at the bottom of the board. Their groups are named in plain text and are never pinged.", verbose_name="Show healthy constellations"),
        ),
        migrations.AlterField(
            model_name="admmonitorconfig",
            name="status_board_enabled",
            field=models.BooleanField(default=True, help_text="Maintain a single up-to-date status board in the channel: existing messages are deleted and the current list of systems failing an enabled criterion, grouped by constellation, is reposted. Requires a bot token."),
        ),
        migrations.AlterField(
            model_name="monitoredconstellation",
            name="groups",
            field=models.ManyToManyField(blank=True, help_text="Auth groups (usually corporations) responsible for this constellation. The matching Discord roles are pinged when a system here fails an enabled alert criterion.", related_name="admmonitor_constellations", to="auth.group", verbose_name="Alerted groups"),
        ),
    ]
