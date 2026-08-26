from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admmonitor", "0005_show_healthy_constellations"),
    ]

    operations = [
        migrations.AddField(
            model_name="admmonitorconfig",
            name="adm_alerts_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Report systems whose ADM falls below the ADM threshold.",
                verbose_name="Alert on ADM",
            ),
        ),
        migrations.AddField(
            model_name="admmonitorconfig",
            name="military_alerts_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Report systems whose military index falls below its threshold.",
                verbose_name="Alert on military index",
            ),
        ),
        migrations.AddField(
            model_name="admmonitorconfig",
            name="military_threshold",
            field=models.IntegerField(
                default=5,
                help_text="Systems with a military index strictly below this value are reported (index levels run 0 - 5).",
                verbose_name="Military index threshold",
            ),
        ),
        migrations.AddField(
            model_name="admmonitorconfig",
            name="industry_alerts_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Report systems whose industry index falls below its threshold.",
                verbose_name="Alert on industry index",
            ),
        ),
        migrations.AddField(
            model_name="admmonitorconfig",
            name="industry_threshold",
            field=models.IntegerField(
                default=5,
                help_text="Systems with an industry index strictly below this value are reported (index levels run 0 - 5).",
                verbose_name="Industry index threshold",
            ),
        ),
        migrations.AlterField(
            model_name="admmonitorconfig",
            name="threshold",
            field=models.FloatField(
                default=4.0,
                help_text="Systems with an ADM strictly below this value are reported (valid ADM range in EVE is 1.0 - 6.0).",
                verbose_name="ADM threshold",
            ),
        ),
        migrations.AddField(
            model_name="systemadmstatus",
            name="failed_checks",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Comma-separated keys of the criteria this system currently fails (adm, military, industry).",
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name="systemadmstatus",
            name="below_threshold",
            field=models.BooleanField(
                default=False,
                help_text="Set when the system fails at least one enabled alert criterion.",
                verbose_name="Failing",
            ),
        ),
    ]
