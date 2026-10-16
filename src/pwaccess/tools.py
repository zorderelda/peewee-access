"""
Integration with peewee's database tooling (``playhouse``).

Everything documented on peewee's *Database Tooling* page is supported:

===================  ========================================================
Tool                 How it works with Access
===================  ========================================================
``db_url``           ``connect('access:///C:/data/app.accdb')`` and
                     ``'access+pool:///...'``, registered through peewee's
                     own ``register_database()`` API.
``pool``             :class:`~pwaccess.pool.PooledAccessDatabase`.
``migrate``          :class:`AccessMigrator`, returned automatically by
                     ``SchemaMigrator.from_database(db)``.
``reflection``       :class:`AccessMetadata`; ``generate_models(db)`` and
                     ``Introspector.from_database`` work out of the box.
``pwiz``             ``python -m pwaccess -e access C:/data/app.accdb``.
``dataset``          Works once reflection, migrate and db_url are wired,
                     which importing :mod:`pwaccess` does.
``test_utils``       ``count_queries`` hooks the peewee logger and is
                     database-agnostic; no adaptation needed.
``signals``          Pure ``Model`` mixin; database-agnostic, works as-is.
===================  ========================================================

:func:`register_tooling` performs the wiring and is idempotent. It is
called by ``pwaccess/__init__.py`` on import.
"""

import copy
import logging
import re

from peewee import CharField, Entity, ForeignKeyField, Proxy

from .database import AccessDatabase
from .exceptions import AccessNotSupportedError
from .pool import PooledAccessDatabase
from .types import ACCESS_COLUMN_MAP

try:
    from playhouse.migrate import SchemaMigrator, operation
    from playhouse.reflection import Introspector, Metadata, UnknownField
except ImportError:  # pragma: no cover - playhouse ships with peewee
    SchemaMigrator = operation = None
    Introspector = Metadata = UnknownField = None

__all__ = [
    'IGNORED_URL_PARAMS',
    'AccessMetadata',
    'AccessMigrator',
    'access_url_connect',
    'access_pool_url_connect',
    'access_url_to_path',
    'register_tooling',
    'tooling_registered',
]

logger = logging.getLogger('peewee')



# ---------------------------------------------------------------------------
# Reflection
# ---------------------------------------------------------------------------



if Metadata is not None:

    class AccessMetadata(Metadata):
        """
        Reflection metadata for Microsoft Access.

        Translates the ODBC type names reported by the Access driver into
        peewee field classes, which is what
        :func:`playhouse.reflection.generate_models`, ``pwiz`` and
        :class:`playhouse.dataset.DataSet` all rely on.

        Usage::

            from playhouse.reflection import generate_models

            db = AccessDatabase(r'C:\\data\\app.accdb')
            models = generate_models(db)
            User = models['user']
        """

        column_map = ACCESS_COLUMN_MAP

        #: e.g. VARCHAR(255), DECIMAL(10, 5)
        re_varchar = r'^\s*(?:n)?(?:var)?char\s*\(\s*\d+\s*\)\s*$'

        #: Emitted by pwiz at the top of the generated module. Without it
        #: the generated code refers to AccessDatabase while importing only
        #: ``from peewee import *``, and will not run.
        extension_import = 'from pwaccess import AccessDatabase'

        def __init__(self, database):
            super().__init__(database)
            #: Tells pwiz to emit :attr:`extension_import`.
            self.requires_extension = True

        def _map_col(self, column_type):
            """
            Return the peewee field class for one ODBC type name.

            :param column_type: The driver's ``type_name``, which may carry
                a precision suffix such as ``VARCHAR(50)``.
            :returns: A peewee ``Field`` subclass, or
                :class:`~playhouse.reflection.UnknownField` when the type is
                not recognised.
            """
            raw = (column_type or '').lower().strip()
            if raw in self.column_map:
                return self.column_map[raw]
            if re.search(self.re_varchar, raw):
                return CharField
            # Strip any "(precision, scale)" suffix and retry.
            stripped = re.sub(r'\(.*\)', '', raw).strip()
            return self.column_map.get(stripped, UnknownField)

        def get_column_types(self, table, schema=None):
            """
            Map every column of *table* onto a peewee field class.

            :returns: A 2-tuple of ``({column_name: field_class}, {})``. The
                second element carries extra field parameters for backends
                that need them; Access needs none.
            """
            column_types = {}
            for column in self.database.get_columns(table, schema):
                column_types[column.name] = self._map_col(column.data_type)
            return column_types, {}

else:                                                # pragma: no cover
    AccessMetadata = None


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

if SchemaMigrator is not None:

    def _base_operation(name):
        """
        The undecorated body of a ``SchemaMigrator`` operation.

        ``@operation`` wraps every migrator method in a shim that defers
        the call as an ``Operation``. Through peewee 4.3 the shim accepted
        ``with_context=True`` to run the body at once instead. peewee 4.4
        removed that flag and has ``Operation.run()`` call the body itself,
        so ``with_context`` is now stored as an ordinary keyword that the
        body rejects when the migration finally runs. Both shims are built
        with :func:`functools.wraps`, which leaves the body reachable as
        ``__wrapped__`` -- the one spelling that holds across the supported
        peewee range.
        """
        return getattr(SchemaMigrator, name).__wrapped__

    class AccessMigrator(SchemaMigrator):
        """
        Schema migrator for Microsoft Access.

        Returned automatically by
        ``playhouse.migrate.SchemaMigrator.from_database(db)`` once this
        module has been imported, so the usual idiom works unchanged::

            from playhouse.migrate import migrate, SchemaMigrator

            migrator = SchemaMigrator.from_database(db)
            migrate(
                migrator.add_column('tweet', 'flags', IntegerField(null=True)),
                migrator.drop_index('tweet', 'idx_tweet_content'),
            )

        Jet SQL diverges from the ANSI DDL peewee emits in four ways, all
        handled here:

        * ``ALTER COLUMN`` takes no ``TYPE`` keyword.
        * ``DROP INDEX`` requires the table: ``DROP INDEX i ON t``.
        * ``DROP COLUMN`` does not accept ``CASCADE``.
        * DDL is not transactional, so a failed multi-step migration leaves
          the schema partly changed. Take a copy of the file first.

        Five operations have no Jet SQL equivalent at all and raise
        :class:`AccessNotSupportedError` with guidance:
        :meth:`rename_column`, :meth:`rename_table`, :meth:`add_not_null`,
        :meth:`drop_not_null` and column defaults. All of these are DAO or
        ADOX operations in Access, not SQL ones.
        """

        #: Jet has no transactional DDL; a failed migration is not rolled
        #: back. playhouse.migrate consults this before wrapping the
        #: operations in a transaction.
        transactional_ddl = False

        explicit_create_foreign_key = True

        #: Access has no schemas. peewee 4.5 consults this when ``schema=``
        #: is passed to the constructor and refuses with a ValueError.
        supports_schema = False

        def alter_column_type(self, table, column, field, cast=None):
            """
            Change a column's data type.

            Jet spells this ``ALTER TABLE t ALTER COLUMN c LONG`` -- with no
            ``TYPE`` keyword, and with any ``NOT NULL`` restated inline
            because Access has no separate ``SET NOT NULL``.

            The *cast* check happens here rather than inside the deferred
            operation so that an unsupported call fails at the point it is
            written, not later when ``migrate()`` runs it.

            :param cast: Not supported; Access has no ``USING`` clause.
            :raises AccessNotSupportedError: If *cast* is given.
            :returns: A deferred ``Operation``.
            """
            if cast is not None:
                raise AccessNotSupportedError(
                    'Access has no USING clause, so alter_column_type() '
                    'cannot cast. Add a new column, copy the values across '
                    'with an UPDATE, then drop the original.')
            return self._alter_column_type(table, column, field)

        @operation
        def _alter_column_type(self, table, column, field):
            """Emit the Jet ``ALTER COLUMN`` for :meth:`alter_column_type`."""
            ctx = self.make_context()
            ctx = (self
                   ._alter_column(ctx, table, column)
                   .literal(' ')
                   .sql(field.ddl_datatype(ctx)))
            if not field.null:
                ctx = ctx.literal(' NOT NULL')
            return ctx

        @operation
        def drop_column(self, table, column_name, cascade=True):
            """
            Drop a column. *cascade* is ignored; Jet has no ``CASCADE``.
            """
            return _base_operation('drop_column')(
                self, table, column_name, cascade=False)

        @operation
        def drop_index(self, table, index_name):
            """
            Drop an index.

            Jet requires the table name: ``DROP INDEX i ON t``, where every
            other backend accepts a bare ``DROP INDEX i``.
            """
            return (self
                    .make_context()
                    .literal('DROP INDEX ')
                    .sql(Entity(index_name))
                    .literal(' ON ')
                    .sql(Entity(table)))

        @operation
        def add_column(self, table, column_name, field, allow_not_null=False):
            """
            Add a column.

            A nullable field is handed straight to the base implementation.
            A non-null field cannot be, because the base finishes with
            ``add_not_null()``, which Access cannot express and which this
            class raises on -- so the non-null path is reproduced here
            minus that final step. The column is created, back-filled with
            its default, and left nullable as far as the engine is
            concerned.

            Every other guarantee the base implementation makes is kept:
            the missing-default and unbound-foreign-key checks still raise,
            and a foreign key still gets its constraint. Dropping those
            along with ``add_not_null()`` would turn a required column with
            no default into a silent ``UPDATE ... SET col = NULL``, and a
            required foreign key into an unconstrained integer column.

            :param allow_not_null: Emit ``ADD COLUMN ... NOT NULL`` as a
                single statement with no back-fill, exactly as peewee 4.4
                and later do for every backend. The statement is valid Jet
                DDL; on a table that already holds rows it is the engine,
                not this class, that decides whether to accept it. Needs
                peewee 4.4 or later.
            :raises ValueError: If *field* is non-null with no default, or
                is a foreign key with no target field.
            """
            if allow_not_null:
                return _base_operation('add_column')(
                    self, table, column_name, field, allow_not_null=True)

            if field.null:
                return _base_operation('add_column')(
                    self, table, column_name, field)

            if field.default is None:
                raise ValueError('%s is not null but has no default'
                                 % column_name)

            is_foreign_key = isinstance(field, ForeignKeyField)
            if is_foreign_key and not field.rel_field:
                raise ValueError('Foreign keys must specify a `field`.')

            logger.warning(
                'Access cannot add a NOT NULL constraint to an existing '
                'column. Column %r on table %r will be created and '
                'populated with its default, but will remain nullable.',
                column_name, table)

            field = copy.copy(field)
            default, field.null = field.default, True
            operations = [self.alter_add_column(table, column_name, field)]
            field.default = default
            operations.append(self.apply_default(table, column_name, field))

            if is_foreign_key and self.explicit_create_foreign_key:
                operations.append(self.add_foreign_key_constraint(
                    table, column_name,
                    field.rel_model._meta.table_name,
                    field.rel_field.column_name,
                    field.on_delete, field.on_update))

            if field.index or field.unique:
                operations.append(self.add_index(
                    table, (column_name,), field.unique,
                    getattr(field, 'index_type', None)))

            return operations

        # -- Operations Jet SQL cannot express -----------------------------

        def rename_column(self, table, old_name, new_name):
            """:raises AccessNotSupportedError: Always."""
            raise AccessNotSupportedError(
                'Jet SQL cannot rename a column. Add the new column, copy '
                'the values with an UPDATE, then drop the old one -- or '
                'rename it through DAO/ADOX in Access itself.')

        def rename_table(self, old_name, new_name):
            """:raises AccessNotSupportedError: Always."""
            raise AccessNotSupportedError(
                'Jet SQL cannot rename a table. Use SELECT ... INTO to copy '
                'it under the new name and DROP TABLE the original, or '
                'rename it through DAO/ADOX.')

        def add_not_null(self, table, column):
            """:raises AccessNotSupportedError: Always."""
            raise AccessNotSupportedError(
                'Access cannot add a NOT NULL constraint to an existing '
                'column. Recreate the table with the constraint in place, '
                'or use alter_column_type() with a non-null field.')

        def drop_not_null(self, table, column):
            """:raises AccessNotSupportedError: Always."""
            raise AccessNotSupportedError(
                'Access cannot drop a NOT NULL constraint from an existing '
                'column. Use alter_column_type() with a nullable field '
                'instead.')

        def add_column_default(self, table, column, default):
            """:raises AccessNotSupportedError: Always."""
            raise AccessNotSupportedError(
                'Column defaults are a DAO/ADOX property in Access, not a '
                'SQL one, and cannot be set through Jet SQL. Apply the '
                'default in your peewee field definition instead.')

        def drop_column_default(self, table, column):
            """:raises AccessNotSupportedError: Always."""
            raise AccessNotSupportedError(
                'Column defaults are a DAO/ADOX property in Access, not a '
                'SQL one, and cannot be dropped through Jet SQL.')

else:                                                # pragma: no cover
    AccessMigrator = None


# ---------------------------------------------------------------------------
# db_url
# ---------------------------------------------------------------------------

def access_url_to_path(database, host=None):
    """
    Recover a Windows path from the pieces urlparse() produced.

    ``playhouse.db_url`` hands the class a ``database`` (the URL path with
    its leading slash removed) and, if the URL had an authority component, a
    ``host``. Windows paths do not survive that intact, so the canonical
    spelling puts the whole path in the path component::

        access:///C:/data/app.accdb        ->  C:/data/app.accdb

    Two lenient spellings are also accepted, because they are the ones
    people type by mistake::

        access://C:/data/app.accdb         ->  C:/data/app.accdb
        access:///C|/data/app.accdb        ->  C:/data/app.accdb

    In the two-slash form urlparse() takes ``C:`` for an authority and
    lower-cases it, so the drive letter is re-cased here. A multi-character
    host is treated as a UNC server name.

    :param database: The ``database`` value db_url extracted from the path.
    :param host: The ``host`` value db_url extracted from the authority, if
        any.
    :returns: A path string suitable for :class:`AccessDatabase`.
    """
    database = database or ''
    if host:
        if len(host) == 1 and host.isalpha():
            # access://C:/data/app.accdb -- host is really a drive letter.
            return '%s:/%s' % (host.upper(), database)
        # access://server/share/app.accdb -- host is a UNC server.
        return '//%s/%s' % (host, database)

    # access:///C|/data/app.accdb -- the legacy bar-for-colon spelling.
    if len(database) > 1 and database[1] == '|' and database[0].isalpha():
        return database[0].upper() + ':' + database[2:]

    return database


#: Connection parameters ``playhouse.db_url`` produces that an Access file
#: database cannot use. See :func:`_drop_unusable_params`.
IGNORED_URL_PARAMS = ('user', 'port')


def _drop_unusable_params(kwargs):
    """
    Discard the db_url parameters Access has no use for.

    ``playhouse.db_url.connect()`` builds one keyword dict from the URL and
    from any ``**connect_params`` the caller passes, then hands the whole
    thing to whichever class is registered for the scheme. That dict is
    shaped for a network database: ``database``, ``user``, ``password``,
    ``host``, ``port``. Access is a file, so ``user`` and ``port`` are
    meaningless to it -- but every unrecognized keyword becomes a
    ``KEY=VALUE`` pair in the ODBC connection string, which is how
    ``connect('access:///C:/app.accdb', user='jeff')`` ended up sending
    ``;user=jeff`` to the driver.

    Dropping them keeps the factories substitutable for any other db_url
    backend: code that builds one parameter dict and connects several
    databases with it works against Access without special-casing.

    ``host`` is not dropped -- :func:`access_url_to_path` needs it to
    recover a drive letter or UNC server -- and neither is ``password``,
    which Access sends as ``PWD``.

    :param kwargs: The keyword dict db_url assembled. Not modified.
    :returns: A copy with :data:`IGNORED_URL_PARAMS` removed.
    """
    ignored = {key: kwargs[key] for key in IGNORED_URL_PARAMS
               if key in kwargs}
    if not ignored:
        return kwargs

    # Debug rather than a warning: a caller reusing one parameter dict
    # across backends is doing something reasonable, and this is the
    # expected outcome rather than a mistake worth interrupting them over.
    logger.debug('Ignoring db_url parameters an Access file database has no '
                 'use for: %s.',
                 ', '.join(sorted(ignored)))
    return {key: value for key, value in kwargs.items()
            if key not in ignored}


def access_url_connect(database=None, host=None, **kwargs):
    """
    Factory registered with ``playhouse.db_url`` for the ``access`` scheme.

    Accepts the full parameter set db_url hands a registered class and
    ignores the ones a file database cannot use; see
    :func:`_drop_unusable_params`.

    :returns: A configured :class:`AccessDatabase`.
    """
    return AccessDatabase(access_url_to_path(database, host),
                          **_drop_unusable_params(kwargs))


def access_pool_url_connect(database=None, host=None, **kwargs):
    """
    Factory registered with ``playhouse.db_url`` for ``access+pool``.

    Accepts the full parameter set db_url hands a registered class and
    ignores the ones a file database cannot use; see
    :func:`_drop_unusable_params`.

    :returns: A configured :class:`PooledAccessDatabase`.
    """
    return PooledAccessDatabase(access_url_to_path(database, host),
                                **_drop_unusable_params(kwargs))


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

_TOOLING_REGISTERED = False


def register_tooling():
    """
    Teach playhouse's tooling about Access.

    Performs four pieces of wiring:

    * ``Introspector.from_database()`` returns an Access-aware introspector.
    * ``SchemaMigrator.from_database()`` returns an :class:`AccessMigrator`.
    * ``playhouse.db_url`` gains the ``access``, ``msaccess`` and
      ``access+pool`` schemes.
    * ``pwiz`` accepts ``-e access``.

    Called automatically on import. Idempotent: the wrappers carry a
    ``_pwaccess_patch`` marker, so a module reload re-uses the originals
    rather than wrapping the wrappers.

    Unlike the package build, the db_url registration here is deliberately
    *not* wrapped in a try/except. A silent failure there is what makes
    ``connect('access:///...')`` raise "Unrecognized or unsupported scheme"
    with no explanation of why.

    :returns: ``True`` if this call did the work, ``False`` if it was
        already done.
    """
    global _TOOLING_REGISTERED
    if _TOOLING_REGISTERED:
        return False

    if Introspector is not None and \
            not getattr(Introspector.from_database, '_pwaccess_patch', False):
        _original_introspector = Introspector.from_database.__func__

        def _access_introspector(cls, database, schema=None):
            """Dispatch Access databases to :class:`AccessMetadata`."""
            if getattr(database, 'access_dialect', False):
                return cls(AccessMetadata(database), schema=schema)
            return _original_introspector(cls, database, schema=schema)

        _access_introspector._pwaccess_patch = True
        _access_introspector._pwaccess_original = _original_introspector
        Introspector.from_database = classmethod(_access_introspector)

    if SchemaMigrator is not None and \
            not getattr(SchemaMigrator.from_database, '_pwaccess_patch',
                        False):
        _original_migrator = SchemaMigrator.from_database.__func__

        def _access_migrator(cls, database, schema=None):
            """
            Dispatch Access databases to :class:`AccessMigrator`.

            Mirrors the signature peewee 4.4 gave the original: it sees
            through an initialised ``Proxy`` and takes ``schema=``, which
            ``playhouse.migrations.Runner`` always passes. *schema* is only
            forwarded when given, so the older two-argument original still
            works.
            """
            target = database.obj if isinstance(database, Proxy) else database
            if getattr(target, 'access_dialect', False):
                if schema is not None:
                    raise AccessNotSupportedError(
                        'Access has no schemas; call '
                        'SchemaMigrator.from_database() without schema= '
                        'for an Access database.')
                return AccessMigrator(target)
            if schema is None:
                return _original_migrator(cls, database)
            return _original_migrator(cls, database, schema=schema)

        _access_migrator._pwaccess_patch = True
        _access_migrator._pwaccess_original = _original_migrator
        SchemaMigrator.from_database = classmethod(_access_migrator)

    from playhouse.db_url import register_database
    register_database(access_url_connect, 'access', 'msaccess')
    register_database(access_pool_url_connect, 'access+pool',
                      'msaccess+pool')

    try:
        import pwiz
    except ImportError:                              # pragma: no cover
        pass
    else:
        pwiz.DATABASE_ALIASES[AccessDatabase] = ['access', 'msaccess']
        pwiz.DATABASE_MAP['access'] = AccessDatabase
        pwiz.DATABASE_MAP['msaccess'] = AccessDatabase

    _TOOLING_REGISTERED = True
    return True


def tooling_registered():
    """Report whether :func:`register_tooling` has run."""
    return _TOOLING_REGISTERED
