from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admmonitor", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemadmstatus",
            name="military_level",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="systemadmstatus",
            name="industrial_level",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="systemadmstatus",
            name="strategic_level",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
