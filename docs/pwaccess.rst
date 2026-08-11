.. _pwaccess:

Microsoft Access
================

``peewee-access`` is a Microsoft Access (JET/ACE) backend for the `peewee
<http://docs.peewee-orm.com/>`_ ORM. It supports both ``.accdb`` (ACE) and
``.mdb`` (JET) files, creating the database file automatically when it does
not already exist.

Peewee has no ODBC support of its own, so this package supplies the
:py:class:`AccessDatabase` class and a set of SQL-generation adjustments for
Jet's dialect. Everything else about peewee is unchanged: models, queries,
transactions and the ``playhouse`` tooling all work as documented.

.. code-block:: python

    from peewee import *
    from pwaccess import AccessDatabase

    db = AccessDatabase(r'C:\data\myapp.accdb')

    class User(Model):
        username = TextField(unique=True)

        class Meta:
            database = db

    db.connect()
    db.create_tables([User])

    User.create(username='huey')
    for user in User.select():
        print(user.username)

.. note::
   This package is Windows-only. It depends on the Access ODBC driver and on
   ADOX via COM, neither of which exists on other platforms.

On this page

.. contents::
   :local:
   :depth: 2


Installation
------------

.. code-block:: console

    pip install peewee-access

Two dependencies are unconditional:

``pyodbc``
    The DB-API driver. Peewee ships no ODBC support, so every statement goes
    out through pyodbc.

``pywin32``
    Supplies the ADOX COM interface. ADOX is used both to create a database
    file that does not yet exist and to read schema metadata that the Access
    ODBC driver declines to report -- see :ref:`pwaccess-adox`.

You also need the **Microsoft Access Database Engine** installed. It ships
with Microsoft Office; if Office is absent, install the redistributable. The
bit-ness must match your Python interpreter: 64-bit Python needs the 64-bit
engine.

.. code-block:: python

    import pwaccess
    print(pwaccess.list_access_drivers())
    # ['Microsoft Access Driver (*.mdb, *.accdb)']

An empty list means no usable driver was found. See :ref:`pwaccess-drivers`.

.. warning::
   ``Microsoft.Jet.OLEDB.4.0`` -- the classic JET provider -- has no 64-bit
   build and never will. On 64-bit Python it is unavailable, so ACE is used
   for ``.mdb`` files as well as ``.accdb`` ones. ACE reads and writes the
   older format correctly, so this is transparent in normal use.


Connecting
----------

.. py:class:: AccessDatabase(database, driver=None, password=None, **kwargs)

    A peewee :py:class:`~peewee.Database` for Microsoft Access.

    :param str database: Path to the ``.mdb`` or ``.accdb`` file. Created
        automatically if it does not exist.
    :param str driver: Override the ODBC driver name. Auto-detected by
        default.
    :param str password: Database password, sent as ``PWD`` in the
        connection string.
    :param kwargs: Further keyword arguments become additional
        ``KEY=VALUE`` pairs in the ODBC connection string, for example
        ``Exclusive='Yes'``.

    .. code-block:: python

        db = AccessDatabase(r'C:\data\app.accdb')
        db = AccessDatabase(r'C:\data\legacy.mdb', password='secret')
        db = AccessDatabase(r'C:\data\app.accdb', Exclusive='Yes')

.. py:class:: PooledAccessDatabase(database, max_connections=20, stale_timeout=None, timeout=0, **kwargs)

    :py:class:`AccessDatabase` with connection pooling, composed from
    peewee's generic :py:class:`playhouse.pool.PooledDatabase` mixin.
    Accepts every argument :py:class:`AccessDatabase` does.

    :param int max_connections: Maximum simultaneous connections.
    :param int stale_timeout: Seconds after which an idle connection is
        discarded rather than reused.
    :param int timeout: Seconds to wait for a free connection.

    .. code-block:: python

        from pwaccess import PooledAccessDatabase
        db = PooledAccessDatabase(r'C:\data\app.accdb', max_connections=8)

    .. warning::
       Access is a single-writer file database. A large pool will not make
       it faster and may cause lock contention on the ``.laccdb`` file. Keep
       ``max_connections`` low and set a ``stale_timeout``, since a
       long-lived connection holds a lock for as long as it is open.

Database URLs
^^^^^^^^^^^^^

Four schemes are registered with :py:mod:`playhouse.db_url` on import:
``access``, ``msaccess``, ``access+pool`` and ``msaccess+pool``.

.. code-block:: python

    from playhouse.db_url import connect

    db = connect('access:///C:/data/app.accdb')
    db = connect('access+pool:///C:/data/app.accdb?max_connections=8')

Windows paths do not survive :py:func:`urllib.parse.urlparse` intact, so
three spellings are accepted and all yield the same path:

==================================  =====================================
URL                                 Resulting path
==================================  =====================================
``access:///C:/data/app.accdb``     ``C:/data/app.accdb`` (canonical)
``access://C:/data/app.accdb``      ``C:/data/app.accdb``
``access:///C|/data/app.accdb``     ``C:/data/app.accdb``
``access:///share/app.accdb``       ``//server/share/app.accdb`` (UNC,
with ``host=server``                when the authority is more than one
                                    character)
==================================  =====================================


.. _pwaccess-drivers:

Driver discovery
----------------

.. py:function:: detect_driver()

    Return the name of the best available Access ODBC driver, or ``None``.

.. py:function:: require_driver()

    Return the best available driver, raising
    :py:exc:`DriverNotFoundError` if there is none.

.. py:function:: list_access_drivers()

    Return a list of every installed Access ODBC driver name. Useful for
    diagnostics.

.. py:function:: iter_access_drivers()

    Iterate installed Access ODBC driver names.

.. py:function:: adox_providers()

    Return the ADOX provider strings that will be tried, in order.

.. py:function:: adox_provider(path)

    Return the ADOX provider chosen for *path*.

.. py:function:: create_database_file(path)

    Create an empty database file at *path* using ADOX. Called
    automatically on first connection when the file is absent.

    :raises FileCreationError: If no provider could create the file.

.. py:function:: normalize_path(path)

    Normalize a database path for use in a connection string.


What Access cannot do
---------------------

Jet is a considerably smaller SQL dialect than SQLite, let alone Postgres.
Where a construct simply does not exist, this package raises
:py:exc:`AccessNotSupportedError` with guidance rather than emitting SQL
that fails obscurely at the driver.

===========================  ==========================================
Feature                      Status
===========================  ==========================================
``INSERT ... ON CONFLICT``   Not supported. Use ``get_or_create()``, or
                             an explicit SELECT then INSERT or UPDATE.
                             For a key/value store, see
                             :py:class:`AccessKeyValue`.
``OFFSET``                   Not supported. See :py:func:`paginate`.
Savepoints                   Not supported, so ``atomic()`` blocks cannot
                             nest. Use one top-level ``atomic()``.
Sequences                    Not supported; Access uses ``AUTOINCREMENT``.
``TRUNCATE TABLE``           Not supported; ``DELETE`` is issued instead.
``FULL OUTER JOIN``          Not supported by Jet.
``INTERSECT`` / ``EXCEPT``   Not supported by Jet. ``UNION`` works.
``BigIntegerField``          Maps to a 32-bit Access type. Values beyond
``BigAutoField``             2^31-1 will not round-trip.
Multi-row ``VALUES``         Handled transparently. ``insert_many()``
                             executes one statement per row inside a
                             single transaction, so it is correct but
                             costs one round trip per row.
===========================  ==========================================

Schema differences
^^^^^^^^^^^^^^^^^^

Several adjustments are applied automatically during DDL generation:

* ``NOT NULL`` is omitted for ``BIT``, ``MEMO``, ``LONGBINARY`` and
  ``AUTOINCREMENT`` columns, which Access rejects it on.
* An indexed or unique :py:class:`~peewee.TextField` is emitted as
  ``TEXT(255)`` rather than ``MEMO``, because Access cannot index a MEMO
  column. A plain ``TextField`` remains ``MEMO``.
* Precision arguments are stripped from ``CURRENCY``.
* ``IF NOT EXISTS`` and ``IF EXISTS`` are suppressed and the existence check
  is performed in Python, since Jet has neither.
* Every identifier is bracket-quoted, so reserved words such as ``key``,
  ``value``, ``date`` and ``end`` are safe as column names.

Joins
^^^^^

Access does not accept the flat join spelling every other dialect uses.
Each additional join must be parenthesised against everything to its left,
and this is handled automatically:

.. code-block:: sql

    -- Generated for a three-table join:
    FROM ([remark] INNER JOIN [article] ON ...) INNER JOIN [author] ON ...

Inner joins, left outer joins, mixed join kinds and four-table joins are all
supported.

``LIMIT`` and paging
^^^^^^^^^^^^^^^^^^^^

``LIMIT n`` is rewritten to ``SELECT TOP n``. Access will not accept a
parameter marker inside ``TOP``, so the value is inlined.

A non-zero ``OFFSET`` raises :py:exc:`AccessNotSupportedError`. Prefer
keyset pagination where you can:

.. code-block:: python

    query = (Post
             .select()
             .where(Post.id > last_seen_id)
             .order_by(Post.id)
             .limit(20))

When you need numbered pages, use :py:func:`paginate`.


Transactions
------------

Transactions work through pyodbc's autocommit flag and behave normally:

.. code-block:: python

    with db.atomic():
        User.create(username='huey')
        User.create(username='mickey')

Nested ``atomic()`` blocks are **not** supported, because Jet has no
savepoints. A nested block raises :py:exc:`AccessNotSupportedError` rather
than silently flattening into the outer transaction, which would make a
rollback of the inner block roll back the outer one too.


Database tooling
----------------

Everything on peewee's `Database Tooling
<http://docs.peewee-orm.com/en/latest/peewee/db_tools.html>`_ page is wired
up automatically when :py:mod:`pwaccess` is imported.

Reflection
^^^^^^^^^^

.. py:class:: AccessMetadata(database)

    Reflection metadata for Access, translating the ODBC type names the
    driver reports into peewee field classes.
    :py:func:`~playhouse.reflection.generate_models`, ``pwiz`` and
    :py:class:`~playhouse.dataset.DataSet` all rely on it.

    .. code-block:: python

        from playhouse.reflection import generate_models

        models = generate_models(db)
        User = models['user']

``pwiz``
^^^^^^^^

.. code-block:: console

    python -m pwaccess -e access C:/data/app.accdb

The generated module carries ``from pwaccess import AccessDatabase`` at the
top, so it runs without editing.

Migrations
^^^^^^^^^^

.. py:class:: AccessMigrator(database)

    Returned automatically by
    :py:meth:`~playhouse.migrate.SchemaMigrator.from_database` for an
    Access database. Adapts DDL to Jet: ``ALTER TABLE t ALTER COLUMN c
    TYPE`` omits the ``TYPE`` keyword, ``DROP INDEX`` takes the
    ``DROP INDEX name ON table`` form, and ``DROP COLUMN`` carries no
    ``CASCADE``.

    These operations raise :py:exc:`AccessNotSupportedError`, with guidance
    on what to do instead: ``rename_column``, ``rename_table``,
    ``add_not_null``, ``drop_not_null``, ``add_column_default`` and
    ``drop_column_default``.

    .. code-block:: python

        from playhouse.migrate import migrate, SchemaMigrator

        migrator = SchemaMigrator.from_database(db)
        migrate(migrator.add_column('user', 'nickname', TextField(null=True)))

    .. note::
       Access DDL is not transactional. A failed multi-step migration
       leaves the earlier steps applied, so take a copy of the file first.


ORM utilities
-------------

Most of peewee's `ORM Utilities
<http://docs.peewee-orm.com/en/latest/peewee/orm_utils.html>`_ work against
Access with no adaptation at all, because they operate on model instances
rather than emitting dialect-specific SQL:

======================  ===================================================
Utility                 Status
======================  ===================================================
``shortcuts``           Works unchanged, including
                        ``resolve_multimodel_query`` -- Jet supports
                        ``UNION``.
``hybrid``              Works unchanged. Hybrid expressions compose with
                        the ``TOP`` rewrite.
``signals``             Works unchanged.
``fields``              Works unchanged. ``CompressedField`` and
                        ``PickleField`` map to ``LONGBINARY``.
``dataset``             Works unchanged.
``pydantic_utils``      Works unchanged against reflected Access models.
``kv``                  **Adapted.** See :py:class:`AccessKeyValue`.
``flask_utils``         **Adapted.** See :py:func:`paginate`.
======================  ===================================================

Key/value store
^^^^^^^^^^^^^^^

.. py:class:: AccessKeyValue(key_field=None, value_field=None, ordered=False, database=None, table_name='keyvalue')

    A :py:class:`playhouse.kv.KeyValue` store backed by an Access database.

    The base class writes through an upsert, which Jet has not got, so every
    write raises. This subclass replaces both write paths with an
    UPDATE-then-INSERT inside a transaction. Reads, deletion, ``keys()``,
    ``values()``, ``items()``, ``pop()`` and ``clear()`` are inherited
    unchanged.

    :param key_field: Field for the key. Defaults to
        ``CharField(max_length=255, primary_key=True)``, stored as
        ``TEXT(255)``. Must have ``primary_key=True``.
    :param value_field: Field for the value. Defaults to
        :py:class:`~playhouse.fields.PickleField`, stored as
        ``LONGBINARY``.
    :param bool ordered: Return keys in sorted order when iterating.
    :param database: An :py:class:`AccessDatabase`. **Required.**
    :param str table_name: Name of the underlying table.
    :raises AccessConfigurationError: If no database is supplied.

    .. code-block:: python

        from pwaccess import AccessDatabase, AccessKeyValue

        db = AccessDatabase(r'C:\data\app.accdb')
        settings = AccessKeyValue(database=db)

        settings['theme'] = 'dark'
        settings.update(retries=3, timeout=30)

        settings['theme']       # 'dark'
        dict(settings)          # {'theme': 'dark', 'retries': 3, ...}

        del settings[settings.key > 'r']

    .. note::
       Unlike :py:class:`~playhouse.kv.KeyValue`, there is no default
       database. The base class quietly falls back to in-memory SQLite,
       which would be a surprising thing to receive from this package.

Pagination
^^^^^^^^^^

.. py:function:: paginate(query, page, paginate_by)

    Return one page of *query* without using ``OFFSET``.

    Fetches ``offset + paginate_by`` rows with a single ``TOP`` and
    discards the leading rows in Python.

    :param query: A peewee ``ModelSelect``.
    :param int page: The 1-based page number.
    :param int paginate_by: Rows per page.
    :returns: A list of model instances. Page one returns a limited query
        instead, which iterates identically but defers execution.
    :raises ValueError: If *page* or *paginate_by* is below one.
    :raises AccessNotSupportedError: When paging past the first page of a
        query with no ``ORDER BY``.

    .. code-block:: python

        from pwaccess import paginate

        rows = paginate(Post.select().order_by(Post.id), page=3,
                        paginate_by=10)

    Paging an unordered query raises rather than guessing. Without an
    ``ORDER BY``, Jet's row order is undefined, so page boundaries are not
    stable between requests and a record may appear on two pages or on
    none.

    .. warning::
       Page *p* transfers ``p * paginate_by`` rows from the database.
       Paging deep into a large table is therefore slow, and keyset
       pagination is the better answer whenever page numbers are not a hard
       requirement.

    The nested-``TOP``-with-reversed-sort trick is deliberately not used.
    It is only correct when the ordering is a *total* order: rows that tie
    can swap between the two passes, so pages silently duplicate and drop
    records.

.. py:class:: AccessPaginatedQuery(query_or_model, paginate_by, page_var='page', page=None, check_bounds=False)

    A :py:class:`playhouse.flask_utils.PaginatedQuery` that works on
    Access. Overrides only ``get_object_list()``, delegating to
    :py:func:`paginate`; page numbering, bounds checking and the 404 are
    inherited. The caveats on :py:func:`paginate` apply in full.

    .. code-block:: python

        from playhouse.flask_utils import object_list
        from pwaccess import AccessPaginatedQuery

        @app.route('/posts/')
        def post_list():
            return object_list(
                'post_list.html',
                query=Post.select().order_by(Post.id),
                paginate_by=10,
                paginated_query_class=AccessPaginatedQuery)

    .. note::
       Flask is not a dependency of this package. Constructing
       :py:class:`AccessPaginatedQuery` without Flask installed raises
       :py:exc:`AccessConfigurationError`. :py:func:`paginate` needs no web
       framework.


.. _pwaccess-adox:

Why ADOX is required
--------------------

The Access ODBC driver answers ``IM001`` -- *driver not capable* -- for
several catalog functions. A backend that treats that as "no results" will
report a table with no primary key, no foreign keys, and every column
nullable, and those wrong answers surface far from their cause. ADOX is
therefore the authoritative source for:

* **Primary keys.** ``SQLPrimaryKeys`` answers ``IM001``. Treating that as
  an empty result produces an *over-determined primary key* error several
  layers downstream.
* **Foreign keys.** ``SQLForeignKeys`` answers ``IM001``, which makes
  reflection emit :py:class:`~peewee.IntegerField` where a
  :py:class:`~peewee.ForeignKeyField` belongs.
* **Nullability.** ODBC reports every non-key column as nullable regardless
  of the actual constraint.
* **Autoincrement.** Needed to distinguish ``AutoField`` from a plain
  ``IntegerField``.

.. note::
   ``MSysObjects``, the system catalog, is not readable by default: it
   exists in every Access database but ACE denies ``SELECT`` on it unless
   permission has been granted explicitly. Nothing in this package depends
   on reading it.


Exceptions
----------

.. py:exception:: AccessNotSupportedError

    Raised for SQL constructs Jet cannot express. Carries guidance on what
    to use instead.

.. py:exception:: DriverNotFoundError

    Raised when no Access ODBC driver is installed, or none matching the
    interpreter's bit-ness.

.. py:exception:: FileCreationError

    Raised when a database file could not be created via ADOX.

.. py:exception:: AccessConfigurationError

    Raised for configuration mistakes, such as omitting the required
    ``database`` argument to :py:class:`AccessKeyValue`.


Other exports
-------------

.. py:function:: is_installed()

    Report whether the peewee SQL-generation patches are installed. They
    are applied on import.

.. py:function:: uninstall()

    Remove the peewee patches, restoring the original methods.

.. py:function:: register_tooling()

    Wire up reflection, migrations, ``db_url`` and ``pwiz``. Called on
    import; idempotent.

.. py:function:: tooling_registered()

    Report whether :py:func:`register_tooling` has run.

.. py:data:: FIELD_TYPES

    Mapping of peewee field types to Access column types.

.. py:data:: OPERATIONS

    Mapping of peewee operations to their Jet spellings.