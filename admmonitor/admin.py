from django.contrib import admin, messages

from . import tasks
from .models import AdmMonitorConfig, SystemAdmStatus
from .notify import COLOR_INFO, send_alert


@admin.register(AdmMonitorConfig)
class AdmMonitorConfigAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "enabled",
        "threshold",
        "immediate_alerts_enabled",
        "daily_report_enabled",
        "daily_report_time",
        "last_daily_report_at",
    )
    readonly_fields = ("last_daily_report_at",)
    fieldsets = (
        ("General", {"fields": ("enabled", "threshold", "alliance_ids")}),
        ("Discord delivery", {"fields": ("discord_channel_id", "webhook_url")}),
        (
            "Alerting",
            {
                "fields": (
                    "immediate_alerts_enabled",
                    "daily_report_enabled",
                    "daily_report_time",
                    "last_daily_report_at",
                )
            },
        ),
    )
    actions = ("send_test_message", "run_check_now", "send_daily_report_now")

    def has_add_permission(self, request):
        return not AdmMonitorConfig.objects.exists()

    @admin.action(description="Send test message to Discord")
    def send_test_message(self, request, queryset):
        config = queryset.first()
        ok = send_alert(
            config,
            "🔔 ADM Monitor test message",
            ["If you can read this, the Discord delivery is working."],
            COLOR_INFO,
        )
        if ok:
            self.message_user(request, "Test message sent.", messages.SUCCESS)
        else:
            self.message_user(
                request,
                "Test message could not be sent — check the channel ID / webhook URL "
                "and the worker logs.",
                messages.ERROR,
            )

    @admin.action(description="Run ADM check now")
    def run_check_now(self, request, queryset):
        tasks.run_admmonitor.delay()
        self.message_user(
            request, "ADM check queued — see System ADM Statuses shortly.",
            messages.SUCCESS,
        )

    @admin.action(description="Send daily report now")
    def send_daily_report_now(self, request, queryset):
        tasks.send_daily_report_task.delay()
        self.message_user(request, "Daily report queued.", messages.SUCCESS)


@admin.register(SystemAdmStatus)
class SystemAdmStatusAdmin(admin.ModelAdmin):
    list_display = (
        "system_name",
        "region_name",
        "alliance_name",
        "adm",
        "military_level",
        "industrial_level",
        "strategic_level",
        "below_threshold",
        "immediate_alert_sent",
        "first_seen_below",
        "last_updated",
    )
    list_filter = ("below_threshold", "immediate_alert_sent", "region_name")
    search_fields = ("system_name", "alliance_name")
    ordering = ("adm", "system_name")
    actions = ("reset_alert_state",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.action(description="Reset immediate-alert state (system will alert again)")
    def reset_alert_state(self, request, queryset):
        updated = queryset.update(immediate_alert_sent=False)
        self.message_user(
            request, f"Reset alert state for {updated} system(s).", messages.SUCCESS
        )
