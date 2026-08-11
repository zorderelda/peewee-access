peewee-access
=============

A Microsoft Access (JET/ACE) backend for the `peewee
<http://docs.peewee-orm.com/>`_ ORM, supporting both ``.accdb`` and
``.mdb`` files.

Peewee has no ODBC support of its own. This package supplies an
:py:class:`~pwaccess.AccessDatabase` class, a set of SQL-generation
adjustments for Jet's dialect, and integration with the ``playhouse``
tooling. Everything else about peewee is unchanged.

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

.. code-block:: console

    pip install peewee-access

.. note::
   Windows only. Requires the Microsoft Access Database Engine, matching
   your interpreter's bit-ness, plus ``pyodbc`` and ``pywin32``.

Contents
--------

.. toctree::
   :maxdepth: 2

   pwaccess

What works
----------

Models, queries, joins, transactions, schema creation, reflection,
migrations, ``pwiz``, ``DataSet``, connection pooling, database URLs,
signals, hybrid attributes and pydantic schema generation all work as
peewee documents them.

Where Jet cannot express something -- upserts, ``OFFSET``, savepoints,
``FULL OUTER JOIN`` -- an
:py:exc:`~pwaccess.AccessNotSupportedError` is raised with guidance on
what to do instead, rather than emitting SQL that fails obscurely at the
driver. See :ref:`pwaccess` for the full list.

Indices
-------

* :ref:`genindex`
* :ref:`search`