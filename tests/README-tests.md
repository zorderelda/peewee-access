Test layout
===========

Place these files in `tests\` at the repo root, alongside `src\`.

Offline tests (no driver, run anywhere)
---------------------------------------
  test_url.py             db_url schemes and Windows path recovery
  test_sql_generation.py  the four peewee patches, via generated SQL
  test_migrator.py        AccessMigrator DDL, via generated SQL
  test_metadata.py        type mapping, provider ordering

Live tests (marked, auto-skip without the Access ODBC driver)
-------------------------------------------------------------
  test_live_ansi.py       ANSI-92 query mode, ON DELETE, LIKE wildcards
  test_live_schema.py     catalog introspection, ADOX fallbacks
  test_live_reflection.py generate_models() against a real file
  test_live_migrate.py    migrations executed for real
  test_live_tooling.py    DataSet, pwiz, connection pooling
  test_live_mdb.py        the legacy .mdb provider path

Running
-------
  python -m pytest                    everything
  python -m pytest -m "not driver"    offline only
  python -m pytest -m driver          live only
  python -m pytest -v                 per-test names
  python -m pytest --require-driver   fail rather than skip live tests

Configuration lives in pyproject.toml under [tool.pytest.ini_options].
Markers are declared there, and --strict-markers is on, so a typo in a
marker name is an error rather than a silently-ignored test.

Before tagging a release
------------------------
Run `python -m pytest --require-driver`.

The live tests are the only place the driver is exercised at all -- CI runs
the offline half on Linux, where they cannot run -- so an ordinary green
run on a machine without a working driver means the release was never
tested against a database. --require-driver turns those skips into errors,
which makes that impossible to do by accident.

Availability is probed rather than assumed: the driver check calls
detect_driver(), and the ADOX check actually creates a database file
through raw COM. Importing win32com is not evidence that ACE works -- it
has been seen to answer REGDB_E_CLASSNOTREG transiently on a machine where
the provider is correctly registered -- and an import-only check turns that
into dozens of errors instead of one clear skip. The probe deliberately
does not go through pwaccess.create_database_file(): probing with the code
under test would let a regression in it silently disable the tests that
would have caught the regression.

When live tests are skipped, the run prints a "live coverage" summary
saying so. A quiet skip is worse than a noisy error.
