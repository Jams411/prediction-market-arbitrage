"""Errors raised by the replay adapter (Milestone M2.3)."""

from __future__ import annotations


class ReplayError(Exception):
    """The replay database is unreadable, has an unexpected schema version, the
    requested session is missing, or a stored row cannot be reconstructed into a
    domain / livebook object. Kept separate from ``RecorderError`` — replay is a
    read-only consumer of what the recorder wrote.
    """
