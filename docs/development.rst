.. _pwaccess-development:

Development
===========

Running the tests
-----------------

.. code-block:: console

    pip install -e ".[test]"
    python -m pytest

The suite is in two halves. Most of it exercises SQL generation, URL
parsing, packaging invariants and the peewee patches, none of which need a
database: those tests run on any platform, including the Linux runners CI
uses. The rest talk to a real ``.accdb`` or ``.mdb`` file and are marked,
so they skip on a machine without the Microsoft Access Database Engine.

===========================  ===============================================
Command                      Runs
===========================  ===============================================
``pytest``                   Everything available on this machine
``pytest -m "not driver"``   The driver-free half only
``pytest -m driver``         The live half only
``pytest --require-driver``  Everything, failing rather than skipping
===========================  ===============================================

Two markers select the live tests:

``driver``
    Needs a working Access ODBC driver.

``adox``
    Additionally needs ADOX over COM, which is how the package reads the
    schema metadata ODBC will not report. See :ref:`pwaccess-adox`.

.. _pwaccess-require-driver:

``--require-driver``
--------------------

``--require-driver`` turns a skipped live test into an error. Run it before
tagging a release:

.. code-block:: console

    python -m pytest --require-driver

Without this flag, a machine whose driver is missing or temporarily unwell
reports a clean, green, entirely honest-looking pass having touched no
database at all -- and a release tagged from that run has been validated by
nothing.

This is not hypothetical. Version 1.0.2 was tagged from a run in which all
79 live tests were absent.

The same flag is what makes the ``windows live driver`` CI job meaningful:
without it, a job whose driver install silently failed would skip every
live test and still report green.

When live tests are skipped, the run ends with a ``live coverage`` summary
naming the count and the reason, so an ordinary run cannot quietly imply
coverage it did not have.

How availability is decided
---------------------------

Both prerequisites are probed rather than assumed, once per session and
only when a marked test is actually about to run.

The ``driver`` check calls :py:func:`detect_driver`. The ``adox`` check
creates a database file through raw COM, because importing ``win32com`` is
not evidence that ACE works: it has been observed answering
``REGDB_E_CLASSNOTREG`` on a machine where the provider is correctly
registered, the DLL present and the bit-ness right. Under an import-only
check that transient fault produced dozens of errors at file creation
instead of one clear skip naming the real cause.

The probe deliberately does **not** go through
:py:func:`create_database_file`. Probing with the code under test would let
a regression in file creation disable the very tests that would have caught
it: the suite would report "ADOX unavailable", skip, and pass green.

Building the documentation
--------------------------

.. code-block:: console

    pip install -e ".[doc]"
    sphinx-build -b html -W docs docs/_build/html

``-W`` turns warnings into errors, so a broken cross-reference fails the
build rather than scrolling past. ``docs/conf.py`` mocks ``pyodbc``,
``win32com`` and ``pythoncom``, so the documentation builds on a machine
with no driver -- which is what lets CI build it on Linux.

Every push to ``main`` publishes the result to GitHub Pages, which is where
the **Documentation** link on the PyPI project page points.

Releasing
---------

The version is single-sourced from ``pwaccess.__version__``; ``pyproject``
reads it through setuptools dynamic metadata, so the package and its
metadata cannot drift. Pushing a ``v*`` tag builds the distributions,
verifies that the tag matches ``__version__``, publishes to PyPI through
Trusted Publishing, and creates the GitHub release.

That guard is the last line of defence rather than the first: a tag of
``v1.0.3`` against a package still saying ``1.0.2`` would otherwise publish
the wrong version under the right name, which cannot be undone, because
PyPI does not allow a filename to be reused.
