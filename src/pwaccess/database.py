"""The :class:`AccessDatabase` peewee backend."""

import logging
import os
import re

from peewee import (
    CSQ_PARENTHESES_NEVER,
    SQL,
    ColumnMetadata,
    Context,
    Database,
    ForeignKeyMetadata,
    IndexMetadata,
    OperationalError,
    ViewMetadata,
    __exception_wrapper__,
    fn,
)

from ._drivers import (
    create_database_file,
    detect_driver,
    normalize_path,
    read_adox_table_schema,
    require_driver,
)
from ._sql import rewrite_limit_to_top
from .exceptions import AccessNotSupportedError
from .types import (
    FIELD_TYPES,
    IDENTITY_TYPES,
    OPERATIONS,
    SIZED_CHAR_TYPES,
    SIZED_DECIMAL_TYPES,
)

try:
    import pyodbc
except ImportError:  # pragma: no cover
    pyodbc = None

__all__ = ['AccessContext', 'AccessDatabase']

logger = logging.getLogger('peewee')


class AccessContext(Context):
    """SQL-generation context bound to an :class:`AccessDatabase`."""


class AccessDatabase(Database):
    """
    peewee :class:`~peewee.Database` backend for Microsoft Access.

    Supports both ``.accdb`` (ACE) and ``.mdb`` (JET) files. If the target
    file does not exist it is created automatically, which requires
    ``pywin32``.

    :param database: Path to the ``.mdb`` or ``.accdb`` file.
    :param driver: Override the ODBC driver name. Auto-detected by default.
    :param password: Database password, sent as ``PWD`` in the connection
        string.
    :param kwargs: Further keyword arguments become additional
        ``KEY=VALUE`` pairs in the ODBC connection string, for example
        ``Exclusive='Yes'``. ``ExtendedAnsiSQL=1`` is sent by default and
        can be overridden here; see :meth:`_build_connection_string` for
        what depends on it.

    Usage::

        from peewee import *

        db = AccessDatabase(r'C:\\data\\app.accdb')

        class Person(Model):
            name = CharField(max_length=100)

            class Meta:
                database = db

        db.connect()
        db.create_tables([Person])

    .. note::
       Access is a single-writer file database. Concurrent writes from
       multiple threads or processes are not safe; keep ``thread_safe``
       at its default and serialize writes in your application.
    """

    context_class = AccessContext

    #: Class-attribute marker consulted by the SchemaManager patches.
    #: Checked by name rather than isinstance() so the check survives a
    #: module reload, where an instance of the pre-reload class is not an
    #: instance of the post-reload class.
    access_dialect = True

    field_types = FIELD_TYPES
    operations = OPERATIONS

    param = '?'
    quote = '[]'

    # -- Feature toggles consulted by peewee -----------------------------
    compound_select_parentheses = CSQ_PARENTHESES_NEVER
    for_update = False
    index_schema_prefix = False
    index_using_precedes_table = False
    limit_max = None            # Access uses TOP, not LIMIT
    nulls_ordering = False
    returning_clause = False
    safe_create_index = False   # no CREATE INDEX IF NOT EXISTS
    safe_drop_index = False     # no DROP INDEX IF EXISTS
    sequences = False
    truncate_table = False      # no TRUNCATE TABLE; DELETE is issued

    #: Connection-string keyword that puts the Access ODBC driver into
    #: ANSI-92 query mode. See :meth:`_build_connection_string`.
    _ANSI_92_KEYWORD = 'ExtendedAnsiSQL'

    #: peewee date-part names mapped to Access ``DatePart()`` interval codes.
    _DATE_PART_MAP = {
        'year': 'yyyy', 'quarter': 'q', 'month': 'm', 'week': 'ww',
        'day': 'd', 'weekday': 'w', 'hour': 'h', 'minute': 'n',
        'second': 's',
    }

    # -- Construction -----------------------------------------------------

    def init(self, database, driver=None, password=None, **kwargs):
        """Capture Access-specific options; defer the rest to peewee."""
        self._driver = driver
        self._password = password
        #: Per-table ADOX schema snapshots, keyed by table name. Populated
        #: lazily by _adox_schema() and dropped by close(), since a schema
        #: change between connections would otherwise go unnoticed.
        self._adox_cache = {}
        super().init(database, **kwargs)

    def _adox_schema(self, table, refresh=False):
        """
        Return the cached ADOX schema snapshot for *table*.

        See :func:`read_adox_table_schema` for why ADOX is needed at all.
        The snapshot is cached for the lifetime of the connection because
        each call opens a separate OLE DB connection to a single-writer
        file.

        :param table: Table to inspect.
        :param refresh: Discard any cached snapshot first.
        :returns: The dict described by :func:`read_adox_table_schema`.
        """
        cache = getattr(self, '_adox_cache', None)
        if cache is None:
            cache = self._adox_cache = {}
        if refresh:
            cache.pop(table, None)
        if table not in cache:
            cache[table] = read_adox_table_schema(
                normalize_path(self.database), table)
        return cache[table]

    def close(self):
        """Close the connection and drop the cached ADOX snapshots."""
        if getattr(self, '_adox_cache', None):
            self._adox_cache.clear()
        return super().close()

    # -- Connection -------------------------------------------------------

    def _build_connection_string(self, filepath, redact=False):
        """
        Assemble the ODBC connection string for *filepath*.

        ``ExtendedAnsiSQL=1`` is included by default, which puts the driver
        into ANSI-92 query mode. Without it the driver parses in ANSI-89
        mode, which has no grammar for a referential action: peewee emits
        ``ON DELETE CASCADE`` / ``ON DELETE SET NULL`` for
        ``ForeignKeyField(on_delete=...)``, and every such
        ``create_table()`` fails with *42000 Syntax error in CONSTRAINT
        clause*. The constraint name is not involved -- a ``FOREIGN KEY``
        carrying no action is accepted in either mode, named or bare. It
        is the action alone that ANSI-89 rejects.

        ``LIKE`` is *not* affected, contrary to what the ANSI-89/92
        difference suggests. The two modes are documented to spell the
        wildcards ``*``/``?`` and ``%``/``_`` respectively, but that split
        belongs to the Access UI and DAO. The ODBC driver takes ``%`` and
        ``_`` in both modes and treats ``*`` and ``?`` as literals in
        both, so peewee's ``.contains()``, ``.startswith()`` and
        ``.endswith()`` were already correct before this default and are
        unchanged by it. Verified against the ACE driver; see
        ``tests/test_live_ansi.py``.

        Pass ``ExtendedAnsiSQL=0`` (or any other value) as a keyword
        argument to override it; an explicit setting always wins.

        :param redact: Replace the password with ``***``. Set when the
            string is going somewhere a human will read -- an exception
            message, a log line -- rather than to the driver. A connection
            string embedded verbatim in a traceback puts the database
            password into every log aggregator and bug report that
            traceback reaches.
        """
        driver = self._driver or require_driver()
        parts = ['Driver={%s}' % driver, 'DBQ=%s' % filepath]
        if self._password:
            parts.append('PWD=%s' % ('***' if redact else self._password))

        # ODBC keywords are case-insensitive, so an override has to be
        # matched case-insensitively too. Repeating the keyword instead
        # would leave which of the two wins up to the driver.
        overridden = any(key.lower() == self._ANSI_92_KEYWORD.lower()
                         for key in self.connect_params)
        if not overridden:
            parts.append('%s=1' % self._ANSI_92_KEYWORD)

        for key, value in self.connect_params.items():
            parts.append('%s=%s' % (key, value))
        return ';'.join(parts)

    def _connect(self):
        if pyodbc is None:
            raise AccessNotSupportedError(
                'pyodbc is required by AccessDatabase.  '
                'Run:  pip install pyodbc')

        filepath = normalize_path(self.database)
        if not os.path.isfile(filepath):
            filepath = create_database_file(filepath)

        conn_str = self._build_connection_string(filepath)
        try:
            return pyodbc.connect(conn_str, autocommit=True)
        except Exception as exc:
            raise OperationalError(
                'Could not connect to the Access database.\n'
                '  File:              %s\n'
                '  Connection string: %s\n'
                '  Detected driver:   %s\n'
                '  Underlying error:  %s\n'
                'Run pwaccess.list_access_drivers() to inspect the installed '
                'ODBC drivers and confirm the bitness matches your Python.'
                % (filepath,
                   self._build_connection_string(filepath, redact=True),
                   detect_driver(), exc)) from exc

    def _set_server_version(self, conn):
        try:
            raw = conn.getinfo(18)          # SQL_DBMS_VER
            numbers = re.findall(r'\d+', str(raw))
            self.server_version = tuple(int(n) for n in numbers[:3])
        except Exception:
            self.server_version = (0, 0, 0)

    # -- SQL generation ---------------------------------------------------

    def get_context_options(self):
        """Add the dialect flag the patched generators look for."""
        options = super().get_context_options()
        options['access_dialect'] = True
        return options

    def execute_sql(self, sql, params=None, commit=None):
        """Rewrite LIMIT/OFFSET into TOP, then execute the statement."""
        sql, params = rewrite_limit_to_top(sql, params)

        # DDL invalidates the ADOX snapshots. Without this a migration
        # followed by get_columns() in the same connection answers from a
        # snapshot taken before the ALTER, reporting the old primary key,
        # foreign keys and nullability. Checked only when something is
        # actually cached, so the ordinary query path pays nothing.
        if self._adox_cache and \
                sql[:8].lstrip().upper().startswith(('ALTER', 'CREATE',
                                                     'DROP')):
            self._adox_cache.clear()

        logger.debug((sql, params))
        with __exception_wrapper__:
            cursor = self.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
        return cursor

    def last_insert_id(self, cursor, query_type=None):
        """
        Return the ``AUTOINCREMENT`` value from the last INSERT.

        pyodbc does not populate ``cursor.lastrowid`` for Access, so the
        value is read back with ``SELECT @@IDENTITY`` on the same cursor.
        """
        try:
            cursor.execute('SELECT @@IDENTITY')
            row = cursor.fetchone()
            if row is not None:
                return row[0]
        except Exception:
            pass
        return None

    def rows_affected(self, cursor):
        try:
            return cursor.rowcount
        except AttributeError:
            return 0

    # -- Constructs Access cannot express ---------------------------------

    def default_values_insert(self, ctx):
        raise AccessNotSupportedError(
            'Access does not support INSERT ... DEFAULT VALUES. Supply at '
            'least one explicit column value.')

    def conflict_statement(self, on_conflict, query):
        raise AccessNotSupportedError(
            'Access has no ON CONFLICT / upsert syntax. Use get_or_create(), '
            'or perform an explicit SELECT followed by INSERT or UPDATE.')

    def conflict_update(self, on_conflict, query):
        raise AccessNotSupportedError(
            'Access has no ON CONFLICT / upsert syntax. Use get_or_create(), '
            'or perform an explicit SELECT followed by INSERT or UPDATE.')

    def sequence_exists(self, seq):
        raise AccessNotSupportedError('Access does not support sequences.')

    # -- Transactions -----------------------------------------------------
    # Access has no BEGIN / COMMIT / ROLLBACK statements; transactions are
    # driven through the pyodbc connection's autocommit flag.

    def begin(self):
        if self.is_closed():
            self.connect()
        self._state.conn.autocommit = False

    def commit(self):
        with __exception_wrapper__:
            conn = self._state.conn
            try:
                conn.commit()
            finally:
                conn.autocommit = True

    def rollback(self):
        with __exception_wrapper__:
            conn = self._state.conn
            try:
                conn.rollback()
            finally:
                conn.autocommit = True

    def savepoint(self):
        raise AccessNotSupportedError(
            'Access does not support savepoints, so nested atomic() blocks '
            'are unavailable. Use a single top-level atomic() or '
            'transaction() block.')

    # -- Schema introspection ---------------------------------------------
    # Access exposes no information_schema, so the ODBC catalog functions
    # provided by pyodbc are used instead.

    def get_tables(self, schema=None):
        """Return the names of all user tables, excluding system tables."""
        cursor = self.connection().cursor()
        rows = cursor.tables(tableType='TABLE').fetchall()
        return [r.table_name for r in rows
                if not r.table_name.startswith('MSys')]

    def get_views(self, schema=None):
        cursor = self.connection().cursor()
        rows = cursor.tables(tableType='VIEW').fetchall()
        return [ViewMetadata(r.table_name, None) for r in rows]

    def get_columns(self, table, schema=None):
        """
        Describe every column of *table*.

        Beyond the six fields the ODBC catalog supplies directly, two more
        are reconstructed because peewee's reflection needs them:

        * ``full_type`` -- the parameterized type string, e.g.
          ``VARCHAR(255)``. ODBC reports the bare type name and the size
          separately; peewee parses them back out of a combined string in
          order to recover ``max_length`` / ``max_digits``.
        * ``identity`` -- whether the column is an AUTOINCREMENT. peewee
          uses this to decide whether a reflected primary key becomes an
          :class:`~peewee.AutoField` or a plain
          :class:`~peewee.IntegerField`.

        :returns: A list of :class:`~peewee.ColumnMetadata`.
        """
        cursor = self.connection().cursor()
        rows = cursor.columns(table=table).fetchall()
        primary_keys = set(self.get_primary_keys(table))

        # Autonumber columns are identified through ADOX where possible;
        # the type name is a sound fallback, since Access reports an
        # autonumber as COUNTER regardless.
        try:
            adox = self._adox_schema(table)
            autoincrement = set(adox['autoincrement'])
            nullable = dict(adox['nullable'])
        except Exception as exc:
            logger.debug('ADOX column lookup failed for %r (%s); falling '
                         'back to what ODBC reports.', table, exc)
            autoincrement = set()
            nullable = {}

        columns = []
        for row in rows:
            type_name = row.type_name
            base_type = str(type_name).split('(')[0].strip().upper()

            full_type = type_name
            size = getattr(row, 'column_size', None)
            if size and '(' not in str(type_name):
                if base_type in SIZED_CHAR_TYPES:
                    full_type = '%s(%s)' % (type_name, size)
                elif base_type in SIZED_DECIMAL_TYPES:
                    scale = getattr(row, 'decimal_digits', None) or 0
                    full_type = '%s(%s, %s)' % (type_name, size, scale)

            identity = (row.column_name in autoincrement or
                        base_type in IDENTITY_TYPES)

            # The Access ODBC driver reports every non-key column as
            # nullable, whether or not NOT NULL was applied -- verified by
            # inserting a NULL into a NOT NULL column, which Access
            # rejects while SQLColumns still says is_nullable='YES'. ADOX
            # is the only accurate source, so prefer it and fall back to
            # ODBC only when ADOX is unavailable.
            is_null = nullable.get(row.column_name, row.nullable == 1)

            columns.append(ColumnMetadata(
                row.column_name, type_name, is_null,
                row.column_name in primary_keys, table, row.column_def,
                full_type, identity))
        return columns

    def get_primary_keys(self, table, schema=None):
        """
        Return the primary-key column names of *table*.

        The Access ODBC driver does not implement ``SQLPrimaryKeys`` and
        answers IM001, so this almost always falls through to ADOX. The
        ODBC call is still attempted first, cheaply, in case a future
        driver grows the capability.

        Returning an empty list here is not harmless: peewee's reflection
        treats a table that has an ``id`` column but no declared primary
        key as having a composite key over *every* column, which then
        collides with the AutoField and raises "over-determined primary
        key". An empty result is therefore logged as a warning rather than
        passed off as a legitimate answer.

        :returns: Column names in index order; empty if genuinely none.
        """
        cursor = self.connection().cursor()
        try:
            rows = cursor.primaryKeys(table=table).fetchall()
        except Exception as exc:
            logger.debug('SQLPrimaryKeys unavailable for %r (%s); using '
                         'ADOX instead.', table, exc)
        else:
            if rows:
                return [r.column_name for r in rows]

        try:
            return list(self._adox_schema(table)['primary_keys'])
        except Exception as exc:
            logger.warning(
                'Could not determine the primary key of table %r. ODBC does '
                'not implement SQLPrimaryKeys and the ADOX fallback failed '
                '(%s). Reflection of this table will be incorrect. Install '
                'pywin32 if it is missing.', table, exc)
            return []

    def get_indexes(self, table, schema=None):
        cursor = self.connection().cursor()
        try:
            rows = cursor.statistics(table=table).fetchall()
        except Exception:
            return []

        columns = {}
        unique = set()
        for row in rows:
            if row.index_name is None:
                continue
            columns.setdefault(row.index_name, []).append(row.column_name)
            if row.non_unique == 0:
                unique.add(row.index_name)

        return [IndexMetadata(name, None, cols, name in unique, table)
                for name, cols in columns.items()]

    def get_foreign_keys(self, table, schema=None):
        """
        Return the foreign keys defined on *table*.

        Like ``SQLPrimaryKeys``, the Access ODBC driver does not implement
        ``SQLForeignKeys`` and answers IM001, so this normally falls
        through to ADOX, where foreign keys appear in ``Table.Keys`` with
        ``Type == 2`` (``adKeyForeign``).

        An empty result is consequential rather than benign: peewee's
        reflection has no other way to recognise a relationship, so a
        table whose foreign keys go unreported reflects with plain
        :class:`~peewee.IntegerField` columns where
        :class:`~peewee.ForeignKeyField` belongs. A failed lookup is
        therefore logged rather than silently flattened to ``[]``.

        :returns: A list of :class:`~peewee.ForeignKeyMetadata`.
        """
        cursor = self.connection().cursor()
        try:
            rows = cursor.foreignKeys(table=table).fetchall()
        except Exception as exc:
            logger.debug('SQLForeignKeys unavailable for %r (%s); using '
                         'ADOX instead.', table, exc)
        else:
            if rows:
                return [ForeignKeyMetadata(r.fkcolumn_name, r.pktable_name,
                                           r.pkcolumn_name, table)
                        for r in rows]

        try:
            foreign_keys = self._adox_schema(table)['foreign_keys']
        except Exception as exc:
            logger.warning(
                'Could not read the foreign keys of table %r. ODBC does not '
                'implement SQLForeignKeys and the ADOX fallback failed (%s). '
                'Reflected models will use IntegerField in place of '
                'ForeignKeyField.', table, exc)
            return []

        return [ForeignKeyMetadata(column, dest_table, dest_column, table)
                for column, dest_table, dest_column in foreign_keys]

    # -- Date and time helpers --------------------------------------------

    def extract_date(self, date_part, date_field):
        """
        Access uses ``DatePart('interval', date)`` rather than EXTRACT.

        The interval code is written into the statement as a literal
        rather than bound as a parameter. Jet documents the argument as a
        string expression and the ACE driver is unreliable at inferring a
        parameter's type in a scalar-function argument position, answering
        "Data type mismatch in criteria expression" instead. Inlining is
        safe here because the code comes from :attr:`_DATE_PART_MAP`, a
        fixed dict of nine values, never from the caller.

        A date part Access does not name falls back to a bound parameter,
        so an unexpected value cannot be interpolated into the SQL.
        """
        part = self._DATE_PART_MAP.get(str(date_part).lower())
        if part is None:
            return fn.DatePart(date_part, date_field, python_value=int)
        return fn.DatePart(SQL("'%s'" % part), date_field, python_value=int)

    def truncate_date(self, date_part, date_field):
        """
        Emulate ``date_trunc`` with ``DateSerial()``.

        Access supports truncation to year, month, or day only.
        """
        part = str(date_part).lower()
        if part == 'year':
            return fn.DateSerial(fn.Year(date_field), 1, 1)
        if part == 'month':
            return fn.DateSerial(fn.Year(date_field), fn.Month(date_field), 1)
        if part == 'day':
            return fn.DateSerial(fn.Year(date_field), fn.Month(date_field),
                                 fn.Day(date_field))
        raise AccessNotSupportedError(
            'Access can truncate dates to year, month, or day only; '
            'got %r.' % date_part)

    def to_timestamp(self, date_field):
        # 25569 is the number of days between the Access epoch (1899-12-30)
        # and the Unix epoch (1970-01-01).
        return (date_field - 25569) * 86400

    def from_timestamp(self, date_field):
        return fn.CDate(date_field / 86400.0 + 25569)

    def random(self):
        return fn.Rnd()

    # -- Miscellaneous ----------------------------------------------------

    def get_binary_type(self):
        return bytearray

    def __repr__(self):
        state = 'closed' if self.is_closed() else 'open'
        return '<AccessDatabase %r [%s]>' % (self.database, state)
