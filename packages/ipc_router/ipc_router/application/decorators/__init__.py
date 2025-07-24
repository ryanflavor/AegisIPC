"""Application decorators."""

from .idempotent import idempotent_handler

__all__ = ["idempotent_handler"]
