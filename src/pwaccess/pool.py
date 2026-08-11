"""Connection pooling for the Access backend."""

import pyodbc
from peewee import ImproperlyConfigured

from .database import AccessDatabase

try:
    from playhouse.pool import PooledDatabase as _PooledDatabase
except ImportError:  # pragma: no cover - playhouse ships with peewee
    _PooledDatabase = None

__all__ = ['PooledAccessDatabase']



if _PooledDatabase is not None:
    class PooledAccessDatabase(_PooledDatabase, AccessDatabase):
        """
        An :class:`~pwaccess.database.AccessDatabase` with connection pooling.

        Accepts every argument :class:`~pwaccess.database.AccessDatabase` does,
        plus the pool parameters below.

        :param max_connections: Maximum simultaneous connections. Defaults to
            20, but a much lower number is appropriate for Access; see the
            module-level warning.
        :param stale_timeout: Seconds after which an idle connection is
            discarded rather than reused. Recommended for Access, where a
            long-lived connection holds a lock on the ``.laccdb`` file.
        :param timeout: Seconds to wait for a free connection before raising
            ``MaxConnectionsExceeded``. ``0`` waits forever.
        """

        def _is_closed(self, conn):
            """
            Report whether a pooled connection has gone dead.

            pyodbc exposes no ``ping``, and ``Connection.closed`` is not
            available on the Access driver, so liveness must be probed.

            The probe deliberately avoids SQL. An earlier version issued
            ``SELECT TOP 1 1 FROM MSysObjects`` on the reasoning that the
            system table exists in every Access database -- but existing is
            not the same as being readable, and ACE denies SELECT on the
            system catalogue unless the user has explicitly granted it. The
            query therefore raised on every healthy connection, the handler
            reported it closed, and pooling silently degraded to opening a
            fresh connection every time.

            ``getinfo`` asks the driver about itself over the connection
            handle. It reads no table, needs no permission, and raises only
            when the handle is genuinely unusable.
            """
            try:
                conn.getinfo(pyodbc.SQL_DATA_SOURCE_READ_ONLY)
            except pyodbc.Error:
                return True
            return False
else:
    class PooledAccessDatabase(object):
        """Raises at construction when playhouse.pool is unavailable."""

        def __init__(self, *args, **kwargs):
            raise ImproperlyConfigured(
                'playhouse.pool could not be imported. It ships inside '
                'peewee, so reinstall peewee to use PooledAccessDatabase.')