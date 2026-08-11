"""
Targeted patches to peewee's SQL generation for Microsoft Access.

Access departs from ANSI SQL in ways peewee has no hook for, so a small
number of peewee methods are wrapped. Every wrapper is **gated on the
Access dialect flag** carried in the SQL-generation context, and delegates
to the original implementation for any other database. Installing these
patches is therefore safe in a process that also talks to SQLite,
PostgreSQL, MySQL, or any other peewee backend.

The patches are applied once, by :func:`install`, which
``pwaccess/__init__.py`` calls on import. Repeated calls are no-ops, so
module reloads cannot produce nested wrappers.
"""

import copy
from collections.abc import Mapping

from peewee import (
    SQL,
    Entity,
    Field,
    Insert,
    Join,
    NodeList,
    SchemaManager,
    SelectQuery,
)

from .types import NO_MODIFIERS, NO_NOT_NULL

__all__ = ['install', 'is_installed', 'uninstall']


_INSTALLED = False

#: Originals, captured at install time so the wrappers can delegate.
_original_field_ddl = None
_original_create_table = None
_original_drop_table = None
_original_join_sql = None
_original_insert_execute = None


def _is_access(ctx):
    """Return True when *ctx* is generating SQL for an Access database."""
    return ctx is not None and bool(ctx.state.access_dialect)


def _access_field_ddl(self, ctx):
    """Emit an Access-compatible column definition."""
    if not _is_access(ctx):
        return _original_field_ddl(self, ctx)

    column_type = ctx.state.field_types.get(self.field_type, self.field_type)

    # A MEMO column cannot participate in an index, so an indexed or unique
    # TextField has to become a bounded TEXT column instead.
    if column_type == 'MEMO' and (self.unique or self.index or
                                  self.primary_key):
        column_type = 'TEXT(255)'

    base_type = column_type.split('(')[0].strip().upper()

    modifiers = self.get_modifiers()
    if base_type in NO_MODIFIERS or '(' in column_type:
        modifiers = None

    if column_type and modifiers:
        data_type = SQL('%s(%s)'
                        % (column_type,
                           ', '.join(str(m) for m in modifiers)))
    else:
        data_type = SQL(column_type)

    accum = [Entity(self.column_name), data_type]

    if not self.null and base_type not in NO_NOT_NULL:
        accum.append(SQL('NOT NULL'))
    if self.primary_key:
        accum.append(SQL('PRIMARY KEY'))
    if self.constraints:
        accum.extend(self.constraints)

    return NodeList(accum)


def _access_create_table(self, safe=True, **options):
    """Drop ``IF NOT EXISTS`` from ``CREATE TABLE`` for Access."""

    if getattr(self.database, 'access_dialect', False):
        safe = False
    return _original_create_table(self, safe=safe, **options)


def _access_drop_table(self, safe=True, **options):
    """Drop ``IF EXISTS`` from ``DROP TABLE`` for Access."""

    if getattr(self.database, 'access_dialect', False):
        safe = False
    return _original_drop_table(self, safe=safe, **options)


def _access_join_sql(self, ctx):
    """Emit Access-style nested-parenthesis joins."""
    if not _is_access(ctx):
        return _original_join_sql(self, ctx)

    if isinstance(self.lhs, Join):
        ctx.literal('(')
        ctx.sql(self.lhs)
        ctx.literal(')')
    else:
        ctx.sql(self.lhs)

    ctx.literal(' %s ' % self.join_type).sql(self.rhs)
    if self._on is not None:
        ctx.literal(' ON ').sql(self._on)
    return ctx


def _access_insert_execute(self, database):
    """
    Execute a multi-row ``INSERT`` as a series of single-row statements.

    Jet accepts exactly one ``VALUES`` tuple per ``INSERT``. peewee's
    ``insert_many()`` emits ``VALUES (?),(?),...``, which the driver
    rejects with its generic parse error -- *Missing semicolon (;) at end
    of SQL statement* -- giving no hint as to the real cause.

    Each row is executed as its own statement, produced by shallow-copying
    the query and replacing ``_insert`` with a single-row list. That keeps
    every sub-statement on peewee's ordinary MULTI code path rather than
    rebuilding the query by hand.

    All the statements share one transaction, so a failure part-way leaves
    the table as it was. Access has no savepoints, so ``atomic()`` is
    entered only when no transaction is already open; nesting one would
    raise.

    Note that this is a correctness fix, not a performance one: *n* rows
    means *n* round trips to the driver.

    :returns: For a rowcount query, the total across all statements.
        Otherwise the id of the last row inserted, matching what peewee
        returns for a single-row insert.
    """
    if not getattr(database, 'access_dialect', False):
        return _original_insert_execute(self, database)

    rows = self._insert

    # Anything that is not a sequence of rows -- a single mapping, an
    # INSERT ... SELECT, or raw SQL -- is already valid Jet.
    if rows is None or isinstance(rows, (Mapping, SelectQuery, SQL)):
        return _original_insert_execute(self, database)

    rows = list(rows)
    if len(rows) <= 1:
        # One row still generates a single VALUES tuple, so let peewee
        # handle it. Reassigned because the original may have been a
        # generator, which listing above has now exhausted.
        self._insert = rows
        return _original_insert_execute(self, database)

    def _insert_each():
        """Run one statement per row, returning peewee's usual result."""
        result = None
        total = 0
        for row in rows:
            single = copy.copy(self)
            single._insert = [row]
            result = _original_insert_execute(single, database)
            if self._as_rowcount:
                total += result or 0
        return total if self._as_rowcount else result

    if database.in_transaction():
        return _insert_each()

    with database.atomic():
        return _insert_each()


def install():
    """
    Apply the Access SQL-generation patches to peewee.

    Called automatically when :mod:`pwaccess` is imported. Safe to call
    repeatedly; subsequent calls do nothing.

    :returns: ``True`` if the patches were applied by this call, ``False``
        if they were already in place.
    """
    global _INSTALLED
    global _original_field_ddl, _original_create_table
    global _original_drop_table, _original_join_sql
    global _original_insert_execute

    if _INSTALLED:
        return False

    # A module reload re-executes this module in the same namespace: the
    # ``_original_* = None`` initializers above clobber the captured
    # originals while the wrappers remain installed on peewee's classes.
    # Detect that via the marker stamped on every wrapper and recover the
    # true originals from the ``_pwaccess_original`` attribute each wrapper
    # carries -- never capture an already-patched method as "original",
    # which would delegate to None or recurse.
    if getattr(Field.ddl, '_pwaccess_patch', False):
        _original_field_ddl = Field.ddl._pwaccess_original
        _original_create_table = \
            SchemaManager._create_table._pwaccess_original
        _original_drop_table = SchemaManager._drop_table._pwaccess_original
        _original_join_sql = Join.__sql__._pwaccess_original
        _original_insert_execute = Insert._execute._pwaccess_original

        # Re-point the class attributes at THIS module's wrappers so their
        # global lookups resolve against the freshly executed namespace.
        for wrapper, original in (
                (_access_field_ddl, _original_field_ddl),
                (_access_create_table, _original_create_table),
                (_access_drop_table, _original_drop_table),
                (_access_join_sql, _original_join_sql),
                (_access_insert_execute, _original_insert_execute)):
            wrapper._pwaccess_patch = True
            wrapper._pwaccess_original = original
        Field.ddl = _access_field_ddl
        SchemaManager._create_table = _access_create_table
        SchemaManager._drop_table = _access_drop_table
        Join.__sql__ = _access_join_sql
        Insert._execute = _access_insert_execute

        _INSTALLED = True
        return False

    _original_field_ddl = Field.ddl
    _original_create_table = SchemaManager._create_table
    _original_drop_table = SchemaManager._drop_table
    _original_join_sql = Join.__sql__
    _original_insert_execute = Insert._execute

    for wrapper, original in (
            (_access_field_ddl, _original_field_ddl),
            (_access_create_table, _original_create_table),
            (_access_drop_table, _original_drop_table),
            (_access_join_sql, _original_join_sql),
            (_access_insert_execute, _original_insert_execute)):
        wrapper._pwaccess_patch = True
        wrapper._pwaccess_original = original

    Field.ddl = _access_field_ddl
    SchemaManager._create_table = _access_create_table
    SchemaManager._drop_table = _access_drop_table
    Join.__sql__ = _access_join_sql
    Insert._execute = _access_insert_execute

    _INSTALLED = True
    return True


def is_installed():
    """Return whether the peewee patches are currently applied."""
    return _INSTALLED


def uninstall():
    """
    Restore peewee's original methods.

    Provided for tests and for applications that need to unload the
    backend cleanly. Not normally required.

    :returns: ``True`` if the patches were removed, ``False`` if they were
        not installed.
    """
    global _INSTALLED

    if not _INSTALLED:
        return False

    # Prefer the originals stashed on the live wrappers: after a module
    # reload this module's globals are fresh, but the wrappers installed on
    # peewee's classes still carry the true originals.
    Field.ddl = getattr(Field.ddl, '_pwaccess_original',
                        _original_field_ddl)
    SchemaManager._create_table = getattr(
        SchemaManager._create_table, '_pwaccess_original',
        _original_create_table)
    SchemaManager._drop_table = getattr(
        SchemaManager._drop_table, '_pwaccess_original',
        _original_drop_table)
    Join.__sql__ = getattr(Join.__sql__, '_pwaccess_original',
                           _original_join_sql)
    Insert._execute = getattr(Insert._execute, '_pwaccess_original',
                              _original_insert_execute)

    _INSTALLED = False
    return True
