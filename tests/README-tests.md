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

Configuration lives in pyproject.toml under [tool.pytest.ini_options].
Markers are declared there, and --strict-markers is on, so a typo in a
marker name is an error rather than a silently-ignored test.
