"""The dashboard: a page of local information for the TV (weather, trains, traffic, news and sport).

Each source has a pure ``parse_*`` function, tested against data shaped like
the real service's, and a small amount of fetching code in ``service.py``.
"""

from .service import DashboardService
from .settings import DashboardError, DashboardSettings, DashboardStore

__all__ = ["DashboardError", "DashboardService", "DashboardSettings", "DashboardStore"]
