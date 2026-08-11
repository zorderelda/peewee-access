"""
Integration with peewee's ORM utilities (``playhouse``).

Most of what peewee's *ORM Utilities* page documents is database-agnostic
and needs no adaptation. This module supplies the parts that do:

======================  =====================================================
Utility                 Status on Access
======================  =====================================================
``shortcuts``           ``model_to_dict``, ``dict_to_model`` and
                        ``update_model_from_dict`` operate on instances in
                        Python and emit no SQL. Work as-is.
``hybrid``              Hybrid attributes build expressions that flow through
                        the ordinary SQL generation, so the Access patches
                        apply. Works as-is.
``signals``             Pure ``Model`` mixin. Works as-is.
``fields``              ``CompressedField`` and ``PickleField`` both extend
                        ``BlobField`` and map to ``LONGBINARY``, for which
                        ``NOT NULL`` is already suppressed. Work as-is.
``dataset``             Wired by :func:`~pwaccess.tools.register_tooling`.
``pydantic_utils``      ``to_pydantic`` reads field classes rather than the
                        database. Works against reflected Access models.
``kv``                  **Adapted.** See :class:`AccessKeyValue`.
``flask_utils``         **Adapted.** ``FlaskDB`` accepts an ``access://``
                        URL as-is. For paging, see :func:`paginate` and
                        :class:`AccessPaginatedQuery`.
======================  =====================================================

Everything above that works unchanged is deliberately not wrapped: a
passthrough subclass would add a name to learn without adding behaviour.

Flask is not a dependency of pwaccess. :func:`paginate` carries the whole
of the paging logic and imports nothing from Flask;
:class:`AccessPaginatedQuery` is a thin adapter that supplies the page
number and the 404, and is only defined when Flask is installed.
"""

from peewee import Expression

from .exceptions import AccessConfigurationError, AccessNotSupportedError

try:
    from playhouse.kv import KeyValue
except ImportError:  # pragma: no cover - playhouse ships with peewee
    KeyValue = None

try:
    from playhouse.flask_utils import PaginatedQuery
except ImportError:  # pragma: no cover - Flask is an optional dependency
    PaginatedQuery = None

__all__ = ['AccessKeyValue', 'AccessPaginatedQuery', 'paginate']


# ---------------------------------------------------------------------------
# Key/value store
# ---------------------------------------------------------------------------


if KeyValue is not None:

    class AccessKeyValue(KeyValue):
        """
        A :class:`playhouse.kv.KeyValue` store backed by an Access database.

        The base class writes through an upsert -- ``insert().on_conflict()``
        for a single key, ``insert_many().on_conflict()`` for a bulk update.
        Jet implements neither, and
        :class:`~pwaccess.exceptions.AccessNotSupportedError` is raised on
        every write. This subclass replaces both write paths with an
        UPDATE-then-INSERT performed inside a transaction, so the dictionary
        interface behaves as documented.

        Read paths, deletion, ``keys()``, ``values()``, ``items()``,
        ``pop()`` and ``clear()`` are inherited unchanged: they compile to
        plain SELECT, UPDATE and DELETE, which Access handles.

        Unlike the base class there is no default database. ``KeyValue()``
        with no arguments silently opens an in-memory SQLite database, which
        would be a confusing thing to get from a package named pwaccess.

        Usage::

            from pwaccess import AccessDatabase, AccessKeyValue

            db = AccessDatabase(r'C:\\data\\app.accdb')
            settings = AccessKeyValue(database=db)

            settings['theme'] = 'dark'
            settings.update(retries=3, timeout=30)

            settings['theme']            # 'dark'
            dict(settings)               # {'theme': 'dark', 'retries': 3, ...}

            del settings[settings.key > 'r']

        :param key_field: Field for the key. Defaults to a
            ``CharField(max_length=255, primary_key=True)``, which Jet stores
            as ``TEXT(255)``. Must have ``primary_key=True``.
        :param value_field: Field for the value. Defaults to ``PickleField``,
            which maps to ``LONGBINARY``.
        :param ordered: Return keys in sorted order when iterating.
        :param database: An :class:`~pwaccess.database.AccessDatabase`.
            Required.
        :param table_name: Name of the underlying table.
        :raises AccessConfigurationError: If no database is supplied.

        .. note::
           The default column names ``key`` and ``value`` are both reserved
           words in Jet. They are safe here only because the Access SQL
           generator bracket-quotes every identifier.
        """

        def __init__(self, key_field=None, value_field=None, ordered=False,
                     database=None, table_name='keyvalue'):
            if database is None:
                raise AccessConfigurationError(
                    'AccessKeyValue requires a database. Pass an '
                    'AccessDatabase instance, e.g. '
                    'AccessKeyValue(database='
                    "AccessDatabase(r'C:\\app.accdb')). "
                    'The base playhouse KeyValue defaults to in-memory '
                    'SQLite, which is not a useful default here.')

            super().__init__(key_field=key_field, value_field=value_field,
                             ordered=ordered, database=database,
                             table_name=table_name)

            # KeyValue.__init__ picks its write strategy by sniffing for
            # Postgres or SQLite >= 3.24 and *binds the choice onto the
            # instance* as self.upsert / self.update. Access matches neither
            # test, so it lands on the ON CONFLICT implementations, and an
            # instance attribute shadows anything defined on this subclass.
            # Overriding update() as a method therefore has no effect: the
            # rebinding below is what actually takes hold.
            self.upsert = self._access_upsert
            self.update = self._access_update

        def _write_one(self, key, value):
            """
            Set one key, inserting it only if the UPDATE matched nothing.

            :param key: The key to write.
            :param value: The value to store.
            :returns: ``True`` if a row was inserted, ``False`` if updated.
            """
            rows = (self.model
                    .update(value=value)
                    .where(self.key == key)
                    .execute())
            if rows:
                return False
            self.model.insert(key=key, value=value).execute()
            return True

        def _access_upsert(self, key, value):
            """
            Replacement for ``KeyValue._upsert``, without ON CONFLICT.

            Bound to ``self.upsert`` in :meth:`__init__`.

            :param key: The key to write.
            :param value: The value to store.
            """
            with self._database.atomic():
                self._write_one(key, value)

        def _access_update(self, __data=None, **mapping):
            """
            Replacement for ``KeyValue._update``, without ON CONFLICT.

            The base implementation issues one multi-row INSERT carrying an
            ON CONFLICT clause. Jet has no upsert, so each pair is written
            individually. All writes share one transaction, so a failure
            part-way leaves the store as it was.

            Bound to ``self.update`` in :meth:`__init__`.

            :param __data: An optional mapping of pairs to write.
            :param mapping: Pairs given as keyword arguments.
            :returns: The number of pairs written. The base class returns a
                driver rowcount here, which Jet does not report meaningfully
                for a multi-row write.
            """
            if __data is not None:
                mapping.update(__data)
            if not mapping:
                return 0
            with self._database.atomic():
                for key, value in mapping.items():
                    self._write_one(key, value)
            return len(mapping)

        def __setitem__(self, expr, value):
            """
            Set the value for a key, or for every key matching an expression.

            :param expr: A single key, or a peewee ``Expression``.
            :param value: The value to store.
            """
            if isinstance(expr, Expression):
                # A bulk UPDATE over matching rows; no upsert involved, and
                # keys that do not exist are simply not matched.
                self.model.update(value=value).where(expr).execute()
            else:
                self._access_upsert(expr, value)

else:  # pragma: no cover

    class AccessKeyValue(object):
        """Raises at construction when playhouse.kv is unavailable."""

        def __init__(self, *args, **kwargs):
            raise AccessConfigurationError(
                'playhouse.kv could not be imported. It ships inside '
                'peewee, so reinstall peewee to use AccessKeyValue.')


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def paginate(query, page, paginate_by):
    """
    Return one page of a query without using ``OFFSET``.

    Jet has no OFFSET, so peewee's ``paginate()`` raises
    :class:`~pwaccess.exceptions.AccessNotSupportedError` for every page
    after the first. This fetches ``offset + paginate_by`` rows with a
    single ``TOP`` and discards the leading ``offset`` of them in Python.

    The obvious alternative -- nesting ``TOP`` inside a reversed ``TOP`` --
    is deliberately not used. That trick is only correct when the ordering
    is a *total* order: rows that tie can swap between the two passes, so
    pages silently duplicate and drop records. Jet also gives no guarantee
    about where NULLs land when a sort is reversed, and the dialect reports
    ``nulls_ordering = False`` for exactly that reason.

    The cost is that page *p* transfers ``p * paginate_by`` rows rather than
    ``paginate_by``. Deep paging over a large table is therefore slow. When
    page *numbers* are not a hard requirement, keyset pagination is better::

        Post.select().where(Post.id > last_seen).order_by(Post.id).limit(n)

    Paging an unordered query raises rather than guessing. Without an ORDER
    BY, Jet's row order is undefined, so page boundaries are not stable
    between requests and a record may appear on two pages or on none.

    Usage::

        from pwaccess import paginate

        rows = paginate(Post.select().order_by(Post.id), page=3,
                        paginate_by=10)

    :param query: A peewee ``ModelSelect``.
    :param page: The 1-based page number.
    :param paginate_by: Rows per page.
    :returns: A list of model instances. Page one returns a limited query
        rather than a list, which iterates identically but defers execution.
    :raises ValueError: If *page* or *paginate_by* is less than one.
    :raises AccessNotSupportedError: When paging past the first page of a
        query that carries no ORDER BY.
    """
    if paginate_by < 1:
        raise ValueError('paginate_by must be at least 1, got %r'
                         % (paginate_by,))
    if page < 1:
        raise ValueError('page numbers are 1-based, got %r' % (page,))

    offset = (page - 1) * paginate_by

    # Page one needs no offset, so the ordinary TOP rewrite covers it and
    # the query is returned unevaluated.
    if offset == 0:
        return query.limit(paginate_by)

    # A missing ORDER BY makes page boundaries meaningless. If peewee ever
    # renames this attribute, getattr yields None and every paged query
    # raises loudly -- the safe direction in which to fail.
    if not getattr(query, '_order_by', None):
        raise AccessNotSupportedError(
            'Paging past the first page requires an ORDER BY on Access. '
            'Row order is otherwise undefined, so a record may appear on '
            'two pages or on none.\n'
            'Add an ordering, for example\n'
            '    Post.select().order_by(Post.id)')

    return list(query.limit(offset + paginate_by))[offset:]


if PaginatedQuery is not None:

    class AccessPaginatedQuery(PaginatedQuery):
        """
        A :class:`playhouse.flask_utils.PaginatedQuery` that works on Access.

        The base class pages with ``LIMIT`` and ``OFFSET``, so every page
        after the first raises on Access. This subclass overrides only
        :meth:`get_object_list`, delegating the arithmetic to
        :func:`paginate`; page numbering, bounds checking and the 404 are
        inherited unchanged.

        Read :func:`paginate` for the performance and ordering caveats --
        they apply in full here.

        Usage with ``object_list`` is a drop-in replacement::

            from playhouse.flask_utils import object_list
            from pwaccess import AccessPaginatedQuery

            @app.route('/posts/')
            def post_list():
                return object_list(
                    'post_list.html',
                    query=Post.select().order_by(Post.id),
                    paginate_by=10,
                    paginated_query_class=AccessPaginatedQuery)

        :raises AccessNotSupportedError: When paging past the first page of
            a query that carries no ORDER BY.
        """

        def get_object_list(self):
            """
            Return the rows for the current page.

            :returns: A list of model instances, or a limited query for page
                one. Both iterate identically in a template.
            """
            if self.check_bounds and self.get_page() > self.get_page_count():
                from flask import abort
                abort(404)
            return paginate(self.query, self.get_page(), self.paginate_by)

else:  # pragma: no cover

    class AccessPaginatedQuery(object):
        """Raises at construction when playhouse.flask_utils is unavailable."""

        def __init__(self, *args, **kwargs):
            raise AccessConfigurationError(
                'playhouse.flask_utils could not be imported. It requires '
                'Flask, which pwaccess does not depend on. Install Flask to '
                'use AccessPaginatedQuery, or call pwaccess.paginate() '
                'directly, which needs no web framework.')
