"""
core/request_context.py
=======================
Request-scoped context helpers (async-safe).
"""

from __future__ import annotations

from contextvars import ContextVar

_user_role: ContextVar[str | None] = ContextVar("user_role", default=None)


def set_user_role(role: str | None) -> None:
    _user_role.set(role)


def get_user_role() -> str | None:
    return _user_role.get()
