"""Dashboard error type (Milestone M3.1)."""

from __future__ import annotations


class DashboardError(Exception):
    """Raised for a malformed dashboard input (e.g. a naive ``now``)."""
