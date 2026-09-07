"""Errors raised by the persistent recorder (Milestone M2.2)."""

from __future__ import annotations


class RecorderError(Exception):
    """Misuse of the recorder: a naive datetime, a non-``Decimal`` monetary
    value, an empty identifier, or a database whose schema version does not
    match this build. Kept separate from the domain / adapter / livebook error
    families — the recorder is an independent component.
    """
