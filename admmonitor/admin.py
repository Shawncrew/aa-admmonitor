from django.contrib import admin, messages
from django.db.models import Count, Min, Q
from django.http import HttpResponseRedirect
from django.urls import reverse

from . import discordapi, tasks
from .models import (
    AdmMonitorConfig,
    MonitoredConstellation,
    StatusBoardMessage,
    SystemAdmStatus,
)
from .notify import COLOR_INFO, send_alert


@admin.register(AdmMonitorConfig)
class AdmMonitorConfigAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "enabled",
        "criteria_summary",
        "status_board_enabled",
        "immediate_alerts_enabled",
        "daily_report_enabled",
        "daily_report_time",
        "last_daily_report_at",
    )
    readonly_fields = ("last_daily_report_at", "board_status")
    fieldsets = (
        ("General", {"fields": ("enabled", "alliance_ids")}),
        (
            "Alert criteria",
            {
                "fields": (
                    ("adm_alerts_enabled", "threshold"),
                    ("military_alerts_enabled", "military_threshold"),
                    ("industry_alerts_enabled", "industry_threshold"),
                ),
                "description": (
                    "Enable any combination. A system is reported when it fails "
                    "<b>any</b> enabled criterion — they are OR'd, not AND'd. "
                    "With none enabled, nothing is ever reported."
                ),
            },
        ),
        (
            "Discord delivery",
            {
                "fields": (
                    "discord_channel_id",
                    "discord_bot_token",
                    "discord_guild_id",
                    "webhook_url",
                )
            },
        ),
        (
            "Status board",
            {
                "fields": (
                    "status_board_enabled",
                    "purge_all_messages",
                    "mention_groups",
                    "show_healthy_constellations",
                    "board_status",
                ),
                "description": (
                    "The status board keeps a single, current list of systems below "
                    "the threshold in the channel, grouped by constellation, instead "
                    "of posting a new alert every time. Assign the groups to ping "
                    "under <b>Monitored Constellations</b>."
                ),
            },
        ),
        (
            "Refresh schedule",
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
    actions = ("send_test_message", "run_check_now", "refresh_board_now")
    change_form_template = "admin/admmonitor/admmonitorconfig/change_form.html"

    def has_add_permission(self, request):
        return not AdmMonitorConfig.objects.exists()

    def _maybe_run_check(self, request, obj):
        """Handle the 'Save and run ADM check now' button on the config form."""
        if "_run_check" not in request.POST:
            return None
        tasks.run_admmonitor.delay()
        self.message_user(
            request,
            "Configuration saved and an ADM check was queued. Refresh in a moment "
            "to see the updated System ADM Statuses and Monitored Constellations.",
            messages.SUCCESS,
        )
        # Always land on the change page: after an add, the add view is no longer
        # reachable (the config is a singleton).
        return HttpResponseRedirect(
            reverse("admin:admmonitor_admmonitorconfig_change", args=[obj.pk])
        )

    def response_change(self, request, obj):
        return self._maybe_run_check(request, obj) or super().response_change(
            request, obj
        )

    def response_add(self, request, obj, post_url_continue=None):
        return self._maybe_run_check(request, obj) or super().response_add(
            request, obj, post_url_continue
        )

    @admin.display(description="Alert criteria")
    def criteria_summary(self, obj):
        return obj.criteria_description()

    @admin.display(description="Board status")
    def board_status(self, obj):
        if obj is None or not obj.pk:
            return "—"
        if not obj.status_board_enabled:
            return "Disabled — falling back to append-only alerts."
        if not obj.discord_channel_id:
            return "⚠️ No Discord channel ID set."
        if not discordapi.bot_token(obj):
            return (
                "⚠️ No bot token here and no DISCORD_BOT_TOKEN setting — "
                "falling back to append-only alerts."
            )
        count = StatusBoardMessage.objects.filter(
            channel_id=obj.discord_channel_id
        ).count()
        return f"✅ Active — currently {count} message(s) posted."

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
            request,
            "ADM check queued — see System ADM Statuses shortly.",
            messages.SUCCESS,
        )

    @admin.action(description="Repost status board now")
    def refresh_board_now(self, request, queryset):
        tasks.refresh_board_task.delay(force=True)
        self.message_user(request, "Status board repost queued.", messages.SUCCESS)


@admin.register(MonitoredConstellation)
class MonitoredConstellationAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "region_name",
        "ignored",
        "assigned_groups",
        "system_count",
        "systems_below",
        "lowest_adm",
        "extra_mentions",
    )
    list_editable = ("ignored",)
    list_filter = ("ignored", "region_name", "groups")
    search_fields = ("name", "region_name", "groups__name")
    filter_horizontal = ("groups",)
    ordering = ("region_name", "name")
    readonly_fields = ("constellation_id", "name", "region_name", "last_seen_at")
    fields = (
        "constellation_id",
        "name",
        "region_name",
        "ignored",
        "groups",
        "extra_mentions",
        "last_seen_at",
    )
    actions = ("ignore_constellations", "unignore_constellations")

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .prefetch_related("groups")
            .annotate(
                _system_count=Count("systems", distinct=True),
                _below_count=Count(
                    "systems", filter=Q(systems__below_threshold=True), distinct=True
                ),
                _lowest_adm=Min("systems__adm"),
            )
        )

    def has_add_permission(self, request):
        # Rows appear automatically as sovereignty data is refreshed.
        return False

    @admin.display(description="Alerted groups")
    def assigned_groups(self, obj):
        names = [group.name for group in obj.groups.all()]
        return ", ".join(names) if names else "— none —"

    @admin.display(description="Systems", ordering="_system_count")
    def system_count(self, obj):
        return obj._system_count

    @admin.display(description="Below threshold", ordering="_below_count")
    def systems_below(self, obj):
        return obj._below_count

    @admin.display(description="Lowest ADM", ordering="_lowest_adm")
    def lowest_adm(self, obj):
        return f"{obj._lowest_adm:.1f}" if obj._lowest_adm is not None else "—"

    @admin.action(description="Ignore selected (stop reporting them)")
    def ignore_constellations(self, request, queryset):
        updated = queryset.update(ignored=True)
        self.message_user(
            request,
            f"Now ignoring {updated} constellation(s). They drop off the status "
            "board on the next check.",
            messages.SUCCESS,
        )

    @admin.action(description="Stop ignoring selected (resume reporting)")
    def unignore_constellations(self, request, queryset):
        updated = queryset.update(ignored=False)
        self.message_user(
            request,
            f"Resumed reporting for {updated} constellation(s).",
            messages.SUCCESS,
        )


@admin.register(SystemAdmStatus)
class SystemAdmStatusAdmin(admin.ModelAdmin):
    list_display = (
        "system_name",
        "constellation",
        "region_name",
        "alliance_name",
        "adm",
        "military_level",
        "industrial_level",
        "strategic_level",
        "below_threshold",
        "failed_checks",
        "first_seen_below",
        "last_updated",
    )
    list_filter = (
        "below_threshold",
        "failed_checks",
        "constellation__ignored",
        "region_name",
        "constellation",
    )
    search_fields = ("system_name", "alliance_name", "constellation__name")
    ordering = ("adm", "system_name")
    list_select_related = ("constellation",)
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
