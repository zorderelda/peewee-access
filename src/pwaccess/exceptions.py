"""Exception types raised by :mod:`pwaccess`."""

from peewee import ImproperlyConfigured, NotSupportedError

__all__ = [
    'AccessConfigurationError',
    'AccessNotSupportedError',
    'DriverNotFoundError',
    'FileCreationError',
]


class AccessConfigurationError(ImproperlyConfigured):
    """Base class for pwaccess setup and environment problems."""


class DriverNotFoundError(AccessConfigurationError):
    """No suitable Microsoft Access ODBC driver is installed."""


class FileCreationError(AccessConfigurationError):
    """A new ``.accdb`` / ``.mdb`` file could not be created."""


class AccessNotSupportedError(NotSupportedError):
    """The requested SQL construct has no Microsoft Access equivalent."""
