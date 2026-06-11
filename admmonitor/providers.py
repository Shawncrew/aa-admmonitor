from esi.openapi_clients import ESIClientProvider

from . import __version__

esi = ESIClientProvider(
    compatibility_date="2026-05-19",
    ua_appname="aa-admmonitor",
    ua_version=__version__,
    ua_url="https://github.com/Shawncrew/aa-admmonitor",
    # Only load the spec tags this app actually uses.
    tags=["Sovereignty", "Universe"],
)
