"""Exceptions shared by the whole app."""

from __future__ import annotations



class PyDMError(Exception):
    """A non-retryable, user-facing download error."""


class RetryableError(Exception):
    """A transient error; the chunk worker will retry."""
