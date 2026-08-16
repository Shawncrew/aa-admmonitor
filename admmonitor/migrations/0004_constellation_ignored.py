from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admmonitor", "0003_constellation_assignments"),
    ]

    operations = [
        migrations.AddField(
            model_name="monitoredconstellation",
            name="ignored",
            field=models.BooleanField(
                default=False,
                help_text="Exclude this constellation from all reporting. Its systems are still tracked and visible in System ADM Statuses, but they never appear on the status board and never trigger an alert, however low their ADM.",
                verbose_name="Ignored",
            ),
        ),
    ]
