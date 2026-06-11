from django.apps import AppConfig

from . import __version__


class AdmMonitorAppConfig(AppConfig):
    name = "admmonitor"
    label = "admmonitor"
    verbose_name = f"ADM Monitor v{__version__}"
    default_auto_field = "django.db.models.BigAutoField"
