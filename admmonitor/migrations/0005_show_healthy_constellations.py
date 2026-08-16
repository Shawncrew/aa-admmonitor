from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admmonitor", "0004_constellation_ignored"),
    ]

    operations = [
        migrations.AddField(
            model_name="admmonitorconfig",
            name="show_healthy_constellations",
            field=models.BooleanField(
                default=False,
                help_text="Also list the constellations where every system is at or above the threshold, ticked off at the bottom of the board. Their assigned groups are named in plain text and are never pinged.",
                verbose_name="Show healthy constellations",
            ),
        ),
    ]
