"""Performance-report error type (Milestone M3.3)."""

from __future__ import annotations


class PerfReportError(Exception):
    """Raised for a malformed performance-report request (bad scope, etc.)."""
