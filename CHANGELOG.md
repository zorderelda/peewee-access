# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.4] — 2026-10-21

### Fixed

- **`AccessMigrator` works with peewee 4.4 and later.** peewee 4.4 rewrote
  `playhouse.migrate`: the `with_context=True` flag that ran an operation
  body immediately is gone, `Operation.method` became `Operation.fn`, and
  `SchemaMigrator.from_database()` gained a `schema=` keyword that the new
  `playhouse.migrations` runner always passes. `drop_column()` and a
  nullable `add_column()` relied on the flag, so under peewee 4.4+ both
  failed inside `migrate()` with `unexpected keyword argument
  'with_context'`; the non-null `add_column()` path was unaffected. The
  weekly CI run went red once pip resolved peewee 4.5.3, while the locked
  Windows job stayed green on its pinned 4.3.0. The overrides now reach the
  base implementation through the `__wrapped__` attribute
  `functools.wraps` leaves on the decorator, which holds on every supported
  peewee, and `from_database()` accepts `schema=` (refusing a non-`None`
  value, since Access has no schemas) and an initialised `Proxy`. The test
  suite calls operation bodies in a version-independent way and gains a
  test that goes through `migrate()` itself, so the deferral layer is
  covered rather than only the generated SQL.

### Added

- **`add_column(..., allow_not_null=True)`** is passed through to peewee
  4.4+, which emits `ALTER TABLE t ADD COLUMN c LONG NOT NULL` as a single
  statement with no back-fill and no `add_not_null()` step. That makes it
  the one route to a genuinely required column through the migrator on
  Access. Whether the engine accepts it on a table that already holds rows
  is the engine's decision; it has not been exercised against a live
  database.

## [1.0.3] — 2026-08-14

**No functional change.** The package code is byte-identical to 1.0.2; a
`diff` of `src/` between the two tags is empty. What reaches users is the
corrected `Documentation` URL in the metadata, since project URLs are part
of a release's metadata and cannot be updated in place. Everything else
here is the release pipeline and the test suite — the machinery that
decides whether a future release can be trusted.

### Security

- **Nothing reaches PyPI untested.** `release.yml` built and published
  without running a single test. `ci.yml` does trigger on a `v*` tag, but
  the two workflows race and the upload never waited for the result, so a
  tag on a commit with failing tests published anyway — and a PyPI filename
  can never be reused. The build job now installs the built wheel and runs
  the driver-free suite against it before the artifacts are uploaded, so a
  packaging mistake that omits a module fails the release rather than a
  user's install.
- **Release tags are protected** against deletion and being moved. Because
  PyPI filenames are immutable, a tag repointed after publication
  misrepresents what was shipped for good.

### Documentation

- **The docs are published to GitHub Pages**, built by a new
  `docs.yml` workflow on every push to `main`. `ci.yml` still builds them
  under `-W` on pull requests, which is what gates a broken build before it
  merges; the new workflow publishes rather than validates.
- **The `Documentation` URL in the package metadata now points at the
  rendered documentation** (`https://zorderelda.github.io/peewee-access/`)
  rather than back at the README anchor, so the link on the PyPI project
  page reaches something more than the front page. This reaches PyPI with
  the next release, since project URLs are part of a release's metadata.
- A **Development** page covering the two test halves, the `driver` and
  `adox` markers, `--require-driver`, how availability is probed, building
  the documentation, and how the tag-triggered release works. Summarized in
  the README as well.

### Testing

- **Live-test availability is now probed rather than assumed.** The ADOX
  check only confirmed that `win32com` imported, which is not evidence that
  ACE works: it has been observed answering `REGDB_E_CLASSNOTREG`
  transiently on a machine where the provider is correctly registered and
  the DLL present. Every `adox`-marked test then failed at file creation
  instead of skipping, burying one real cause under dozens of errors. The
  check now creates a database file through raw COM — deliberately not
  through `create_database_file()`, since probing with the code under test
  would let a regression in it disable the tests that would catch the
  regression.
- **`--require-driver`.** Turns a skipped live test into an error, so a run
  cannot pass having quietly exercised no database at all. Worth running
  before tagging, and now also what makes the CI job below meaningful.
- A run that skips live tests now prints a **live coverage** summary saying
  so, rather than reporting an unqualified pass.
- **The live tests now run in CI**, in a `windows live driver` job that
  installs the Access Database Engine redistributable and runs the suite
  under `--require-driver`. Previously no job anywhere touched a real
  database: the Linux matrix cannot load an ODBC driver, and GitHub's
  Windows image ships no Access components, so the existing Windows jobs
  skipped every live test. The driver was exercised only on a maintainer's
  machine. First run: 263 passed, none skipped.

  It is deliberately **not** a required status check. It downloads 80MB
  from `download.microsoft.com` and those URLs rot — the 2010
  redistributable link already 404s — so a required check would block every
  merge the day Microsoft moves the file.

### Maintenance

- **Dependabot no longer proposes a lockfile that breaks Python 3.9.** It
  had picked `constraints-py39.txt` up as a manifest and proposed pytest 9,
  Sphinx 8 and alabaster 1.0 into it, all of which require Python 3.10+, in
  a file that exists to pin one verified resolution for 3.9. The `pip`
  entry carried a comment claiming it would not touch that file; the
  comment was an assumption, not a rule. It cannot be scoped away —
  `dependabot.yml` has no `exclude-paths`, and `ignore` matches dependency
  names rather than manifest files — so the entry was removed and the
  reasoning recorded in its place. Security alerts are unaffected; they do
  not come from that file.
- Pinned actions updated past the Node 20 deprecation (`checkout` v7.0.1,
  `setup-python` v7.0.0).

## [1.0.2] — 2026-08-13

### Fixed

- **`db_url.connect()` forwarded unusable parameters to the ODBC driver.**
  `playhouse.db_url.connect()` merges the URL with any `**connect_params`
  and hands the whole set to the class registered for the scheme, and
  `AccessDatabase` turns every keyword it does not recognize into a
  `KEY=VALUE` pair in the connection string. A `user` or `port` — from the
  URL authority, the query string or the keyword arguments — was therefore
  sent to the driver verbatim as `;user=jeff;port=1234`. Both are now
  dropped, so one parameter dict can serve Access and a network backend
  without an Access special case. `password`, `host` and driver keywords
  such as `Exclusive='Yes'` are unaffected.

### Added

- `pwaccess.IGNORED_URL_PARAMS`, the names the `access` schemes discard.

## [1.0.1] — 2026-08-12

### Fixed

- **`ForeignKeyField(on_delete=...)` could not create its table.** The
  connection string never asked for ANSI-92 query mode, so the driver
  parsed in ANSI-89, which has no grammar for a referential action. The
  `ON DELETE CASCADE` / `ON DELETE SET NULL` peewee emits was rejected with
  `42000 Syntax error in CONSTRAINT clause`, failing `create_table()` for
  any model declaring `on_delete`. `ExtendedAnsiSQL=1` is now sent by
  default. A `FOREIGN KEY` carrying no action was accepted in either mode,
  named or bare, so only models using `on_delete` were affected.

### Changed

- Connections now include `ExtendedAnsiSQL=1`. Pass `ExtendedAnsiSQL=0` as
  a keyword argument to `AccessDatabase` to restore the previous mode; an
  explicit setting always wins over the default. Beyond accepting
  referential actions, ANSI-92 mode reserves more words — identifiers are
  quoted with `[]` throughout, so this is a concern only for hand-written
  SQL passed through `execute_sql()`.

### Testing

- `tests/test_live_ansi.py`, covering both query modes against a real
  driver: `ON DELETE` accepted under ANSI-92 and rejected under ANSI-89,
  `CASCADE` actually cascading rather than merely parsing, and the `LIKE`
  wildcard behaviour below.
- Recorded a non-finding. `LIKE` was expected to be a second casualty of
  ANSI-89, since the two modes are documented to spell the wildcards `*`/`?`
  and `%`/`_` respectively, and peewee emits `%`/`_`. It is not: that split
  belongs to the Access UI and DAO, and the ODBC driver takes `%`/`_` in
  both modes while treating `*`/`?` as literals in both. `.contains()`,
  `.startswith()` and `.endswith()` were correct before this release and
  are unchanged by it. Asserted in both modes so the plausible-but-wrong
  version of the story cannot creep back in.

## [1.0.0] — 2026-08-11

First public release.

### Fixed

- **The package could not be imported without pyodbc.** `pwaccess.pool`
  imported pyodbc unguarded while `database` and `_drivers` guarded theirs,
  so the guards were unreachable, the specific "pip install pyodbc" guidance
  in `_connect()` could never be shown, and the driver-free half of the test
  suite would not run at all.
- **`.offset(n)` without `.limit()` reached the driver as invalid SQL.**
  peewee only pairs an OFFSET with a LIMIT when the dialect declares a
  `limit_max`, and Access declares none, so the query arrived as a bare
  `OFFSET ?` the rewrite could not see. Jet answered with its generic
  "Missing semicolon (;) at end of SQL statement". It now raises
  `AccessNotSupportedError` with keyset-pagination guidance. `.offset(0)`
  remains a no-op.
- **A failed LIMIT rewrite silently became a full-table scan.** The clause
  was stripped before the limit was validated, so an unparseable limit or a
  statement not beginning with `SELECT` returned SQL with the `LIMIT` gone
  and no `TOP` in its place. Such statements are now returned untouched.
- **`.limit()` on a compound query returned wrong rows.** Jet binds `TOP` to
  the individual `SELECT` it is attached to rather than to the combined
  result, so `a UNION b LIMIT 5` yielded five rows from `a` plus all of `b`.
  A limited `UNION` / `INTERSECT` / `EXCEPT` now raises.
- **`AccessMigrator.add_column()` dropped two of peewee's guards.** The
  non-null path reimplemented the base method to skip `add_not_null()` and
  lost the rest with it: a non-null field with no default emitted
  `UPDATE t SET col = NULL` instead of raising `ValueError`, and a non-null
  `ForeignKeyField` produced no foreign-key constraint despite the class
  setting `explicit_create_foreign_key`.
- **The database password leaked into tracebacks.** The `OperationalError`
  raised on a failed connection embedded the connection string verbatim,
  `PWD=` included. It is now redacted to `PWD=***`.
- **Stale ADOX snapshots after DDL.** A migration followed by
  `get_columns()` on the same connection answered from a snapshot taken
  before the `ALTER`, reporting the old primary key, foreign keys and
  nullability. The cache is now dropped on `ALTER` / `CREATE` / `DROP`.
- **`extract_date()` bound the interval code as a parameter.** Jet documents
  that argument as a string expression and ACE is unreliable at inferring a
  parameter's type there. The nine codes in `_DATE_PART_MAP` are now written
  as literals; an unrecognised part is still bound, so a caller's value is
  never interpolated.

### Changed

- **`requires-python` raised from `>=3.8` to `>=3.9`.** The old floor was not
  conservative but wrong: pyodbc 5.3 and pywin32 312 both require 3.9, so a
  3.8 install silently resolved to older drivers while the metadata claimed
  support. Nothing is lost — every runtime dependency resolves to its newest
  release on 3.9, so a locked 3.9 environment runs the same backend as 3.14.
- Version is now single-sourced from `pwaccess.__version__` via setuptools
  dynamic metadata, so the package and its metadata cannot drift.

### Added

- `constraints-py39.txt`, a verified 37-package lockfile for reproducible
  installs on Python 3.9.
- A `work` extra reproducing the 3.9 development-tooling line (pytest 8.x,
  Sphinx 7.x) on a newer interpreter.
- `MANIFEST.in`. Without it the sdist shipped `tests/test_*.py` but not
  `conftest.py` — a test suite that collects and then errors on the first
  fixture lookup.
- `LICENSE` (MIT). Previously declared in metadata with no file present.
- Continuous integration across Python 3.9–3.14 on Windows, a job pinned to
  the 3.9 lockfile, a job that re-resolves everything from PyPI with no
  cache, a documentation build under `-W`, and a weekly scheduled run.

### Testing

- Driver-free tests expanded from 63 to 171. The multi-row `INSERT` split —
  the patch this backend most depends on — previously had no test anywhere,
  because the split happens at execution time and is invisible in `.sql()`.
  A recording-database fixture makes that path, and the LIMIT rewrite,
  testable without a driver.
- New coverage for patch install/uninstall/reload, the isolation of other
  peewee backends, connection-string assembly and password redaction, all
  date and time helpers, pagination argument handling, and packaging
  invariants.

[1.0.4]: https://github.com/zorderelda/peewee-access/releases/tag/v1.0.4
[1.0.3]: https://github.com/zorderelda/peewee-access/releases/tag/v1.0.3
[1.0.2]: https://github.com/zorderelda/peewee-access/releases/tag/v1.0.2
[1.0.1]: https://github.com/zorderelda/peewee-access/releases/tag/v1.0.1
[1.0.0]: https://github.com/zorderelda/peewee-access/releases/tag/v1.0.0
