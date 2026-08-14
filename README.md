# peewee-access

A Microsoft Access (JET/ACE) backend for the [peewee](http://docs.peewee-orm.com) ORM.

Use peewee exactly as you normally would. Only the `Database` class changes.

```python
import datetime
from peewee import *
from pwaccess import AccessDatabase

db = AccessDatabase(r'C:\data\myapp.accdb')

class BaseModel(Model):
    class Meta:
        database = db

class User(BaseModel):
    username = TextField(unique=True)
    joined = DateTimeField(default=datetime.datetime.now)

db.connect()
db.create_tables([User])
User.create(username='jeff')
```

If the `.accdb` or `.mdb` file does not exist, it is created automatically.

**Windows only.** The backend requires the Microsoft Access ODBC driver and
the ADOX COM interface, neither of which exists on other platforms.

---

## Installation

```
pip install peewee-access
```

You also need the **Microsoft Access Database Engine redistributable**, and
its bitness must match your Python interpreter. A 64-bit Python needs the
64-bit engine. To check what is installed:

```python
import pwaccess
pwaccess.list_access_drivers()
```

| Dependency | Why |
|---|---|
| `peewee` | The ORM itself |
| `pyodbc` | The DB-API driver — peewee has no ODBC support of its own |
| `pywin32` | Supplies ADOX, used to create database files *and* to read schema metadata the ODBC driver will not report |

---

## Connection options

Keyword arguments other than `driver` and `password` become extra
`KEY=VALUE` pairs in the ODBC connection string:

```python
db = AccessDatabase(r'C:\data\myapp.accdb', Exclusive='Yes')
```

`ExtendedAnsiSQL=1` is sent by default, which selects the driver's ANSI-92
query mode. ANSI-89 — the driver's own default — has no grammar for a
referential action, so the `ON DELETE CASCADE` / `ON DELETE SET NULL` that
peewee emits for `ForeignKeyField(on_delete=...)` is rejected with
`42000 Syntax error in CONSTRAINT clause`, and the table cannot be created
at all. Pass `ExtendedAnsiSQL=0` to opt back out; an explicit setting always
wins over the default.

`LIKE` is unaffected either way. The two ANSI modes are documented to spell
the wildcards `*`/`?` and `%`/`_`, but that split belongs to the Access UI
and DAO — the ODBC driver takes `%`/`_` in both modes and treats `*`/`?` as
literals in both, so `.contains()`, `.startswith()` and `.endswith()` behave
the same under either setting.

---

## Connection pooling

```python
from pwaccess import PooledAccessDatabase

db = PooledAccessDatabase(r'C:\data\app.accdb',
                          max_connections=8,
                          stale_timeout=300)
```

Access is a single-writer file database. Pooling helps connection reuse and
read concurrency; it does not make concurrent writes safe.

---

## Database URLs

```python
from playhouse.db_url import connect

db = connect('access:///C:/data/app.accdb')
db = connect('access+pool:///C:/data/app.accdb?max_connections=8')
```

Note the **three** slashes. Windows paths do not survive URL parsing intact,
so the drive letter must sit in the URL's path component rather than its
authority. Two lenient spellings are also accepted:

| URL | Resolves to |
|---|---|
| `access:///C:/data/app.accdb` | `C:/data/app.accdb` (canonical) |
| `access://C:/data/app.accdb` | `C:/data/app.accdb` |
| `access:///C\|/data/app.accdb` | `C:/data/app.accdb` |

Registered schemes: `access`, `msaccess`, `access+pool`, `msaccess+pool`.

`connect()` merges the URL with any `**connect_params` you pass and hands the
whole set to the backend, so the parameters a network database expects can
arrive here too. `user` and `port` are meaningless to a file database and are
silently ignored rather than being forwarded to the driver:

```python
params = {'user': 'jeff', 'port': 5432}          # shaped for Postgres
db = connect('access:///C:/data/app.accdb', **params)   # both dropped
```

Everything else still reaches the ODBC connection string, so `password`
(sent as `PWD`) and driver keywords such as `Exclusive='Yes'` work through a
URL exactly as they do through the constructor. The ignored names are
published as `pwaccess.IGNORED_URL_PARAMS`.

---

## Database tooling

Everything on peewee's [Database Tooling](http://docs.peewee-orm.com/en/latest/peewee/db_tools.html)
page works. Importing `pwaccess` wires it all up.

| Tool | Notes |
|---|---|
| `playhouse.db_url` | `access://` and `access+pool://` schemes |
| `playhouse.pool` | `PooledAccessDatabase` |
| `playhouse.migrate` | `AccessMigrator`, returned by `SchemaMigrator.from_database()` |
| `playhouse.reflection` | `AccessMetadata`; `generate_models()` works |
| `playhouse.dataset` | `DataSet` works |
| `playhouse.signals` | Database-agnostic, unchanged |
| `playhouse.test_utils` | Database-agnostic, unchanged |
| `pwiz` | See below |

### Generating models from an existing database

```
python -m pwaccess -e access C:/data/app.accdb > models.py
```

or, equivalently, the installed console script:

```
pwaccess-pwiz -e access C:/data/app.accdb > models.py
```

`python -m pwiz -e access ...` does **not** work. pwiz builds its engine
list while parsing arguments and never imports `pwaccess`, so the `access`
engine is not registered yet and the option is rejected. Running
`python -m pwaccess` performs the import first and then delegates.

### Migrations

```python
from playhouse.migrate import migrate, SchemaMigrator
from pwaccess import AccessNotSupportedError

migrator = SchemaMigrator.from_database(db)

migrate(
    migrator.add_column('tweet', 'flags', IntegerField(null=True)),
    migrator.drop_index('tweet', 'idx_tweet_content'),
)
```

Jet DDL is **not transactional**. A migration that fails partway leaves the
schema partly changed. Copy the file first.

These operations raise `AccessNotSupportedError`, because Jet SQL cannot
express them at all — they are DAO/ADOX operations in Access, not SQL ones:

| Operation | Workaround |
|---|---|
| `rename_column` | Add the new column, `UPDATE` across, drop the old |
| `rename_table` | `SELECT ... INTO` under the new name, then `DROP TABLE` |
| `add_not_null` | Recreate the table with the constraint in place |
| `drop_not_null` | `alter_column_type()` with a nullable field |
| `add_column_default` | Set the default in the peewee field definition |
| `alter_column_type(cast=...)` | Add a column, `UPDATE` with the conversion, drop the original |

`add_column()` with a non-null field works, but logs a warning: the column
is created and back-filled with its default, and remains nullable, because
Access cannot add a NOT NULL constraint to an existing column.

---

## Access limitations

These are constraints of the database engine, not of this library.

| Limitation | What to do instead |
|---|---|
| No upsert / `ON CONFLICT` | `get_or_create()`, or an explicit `SELECT` then `INSERT`/`UPDATE` |
| No `OFFSET` | `pwaccess.paginate()`, or keyset pagination — `.where(Model.id > last_id).limit(n)` |
| No savepoints | One level of `atomic()`; nested blocks raise |
| No multi-row `VALUES` | Handled for you: `insert_many()` is split into one statement per row inside a single transaction |
| No `LIMIT` on a `UNION` | Limit each branch separately, or slice in Python |
| No sequences, `TRUNCATE TABLE`, `FULL OUTER JOIN`, `INTERSECT`, `EXCEPT` | — |
| No 64-bit integers | `BigIntegerField` / `BigAutoField` map to 32-bit types and will overflow past 2³¹−1 |
| `INSERT ... DEFAULT VALUES` unsupported | Supply at least one explicit column |
| Single writer | Serialize writes in your application |

`LIMIT n` is rewritten to `SELECT TOP n` at execution time, since Access
will not accept a parameter marker in a `TOP` clause.

Three cases raise `AccessNotSupportedError` rather than reaching the driver,
because each would otherwise produce a wrong answer or an error message that
names no cause:

* **A non-zero `OFFSET`**, with or without an accompanying `LIMIT`. Use
  `pwaccess.paginate(query, page, paginate_by)`, which over-fetches with
  `TOP` and slices in Python, or keyset pagination for deep paging.
* **A limited compound query** (`UNION`, `INTERSECT`, `EXCEPT`). Jet applies
  `TOP` to the individual `SELECT` it is attached to rather than to the
  combined result, so the rewrite would silently return the wrong rows.
* **Savepoints**, reached by nesting `atomic()` blocks.

When the rewrite cannot be completed for any other reason, the statement is
passed through untouched. Stripping a `LIMIT` without replacing it would turn
a limited query into a full-table scan that looks correct on small data.

---

## How it works

Importing `pwaccess` applies five patches to peewee's SQL generation. Each
is gated on the Access dialect flag and delegates to peewee's original
implementation for every other database, so SQLite, PostgreSQL and MySQL
connections in the same process are unaffected. The patches are idempotent
and removable with `pwaccess.uninstall()`.

| Patch | Reason |
|---|---|
| `Field.ddl` | Omit `NOT NULL` for types that reject it; strip precision from `CURRENCY`; emit an indexed `TextField` as `TEXT(255)`, since Access cannot index a `MEMO` |
| `SchemaManager._create_table` | Access rejects `IF NOT EXISTS` |
| `SchemaManager._drop_table` | Access rejects `IF EXISTS` |
| `Join.__sql__` | Access requires `FROM ((a JOIN b) JOIN c)`, not a flat join chain |
| `Insert._execute` | Jet accepts one `VALUES` tuple per `INSERT`, so `insert_many()` is split into one statement per row inside a single transaction |

### Why ADOX is required

The Access ODBC driver does not implement several optional catalog
functions, and misreports others. Each of the following was confirmed
against the real driver, and each is worked around by reading the schema
through ADOX instead:

| Symptom | Consequence if unhandled |
|---|---|
| `SQLPrimaryKeys` answers `IM001` | Reflection sees no primary key, adopts every column as a composite key, and raises "over-determined primary key" |
| `SQLForeignKeys` answers `IM001` | Relationships reflect as `IntegerField` rather than `ForeignKeyField` |
| Every non-key column reported as nullable | Reflected models carry the wrong `null=` |
| `MSysObjects` unreadable by default | A `SELECT`-based connection liveness probe fails, so pooling silently discards every connection |

`Microsoft.Jet.OLEDB.4.0` has no 64-bit build, so ACE is used for `.mdb`
files as well as `.accdb`, with Jet kept only as a fallback.

---

## Requirements

* Windows
* Python 3.9+
* Microsoft Access Database Engine, bitness matching your interpreter
* `.accdb` (ACE) and `.mdb` (JET) files are both supported

### Locked-down environments

`pip install peewee-access` resolves to the newest release of everything,
which is what the package is developed and tested against.

Python 3.9 is the floor, and it costs you nothing: every runtime dependency
— peewee, pyodbc, pywin32 — resolves to its newest release on 3.9, the same
versions a 3.14 install gets. There is no "old" variant of the backend.

Where an environment needs installs to be *reproducible* rather than merely
current, use the lockfile:

```
pip install peewee-access -c constraints-py39.txt
```

The only genuine divergence on 3.9 is development tooling: pytest 9 requires
3.10+ and Sphinx 9 requires 3.12+, so a 3.9 box gets pytest 8.x and Sphinx
7.x. To reproduce those older lines on a newer interpreter — to check a
change before it reaches the constrained box — add the `work` extra:

```
pip install -e ".[test,doc,work]"
```

CI covers both ends on every run: 3.9 through 3.14, the 3.9 lockfile, and a
job that re-resolves everything from PyPI with no cache so an upstream
release that breaks the backend shows up here first.

---

## Development

```
pip install -e ".[test]"
python -m pytest
```

The suite is in two halves. Most of it covers SQL generation, URL parsing,
packaging invariants and the peewee patches — none of which need a database,
so they run anywhere, including the Linux runners CI uses. The rest talk to a
real `.accdb` or `.mdb` file and are marked `driver` (needs the ODBC driver)
or `adox` (additionally needs ADOX over COM), so they skip on a machine
without the Access Database Engine.

| Command | Runs |
|---|---|
| `pytest` | Everything available on this machine |
| `pytest -m "not driver"` | The driver-free half only |
| `pytest -m driver` | The live half only |
| `pytest --require-driver` | Everything, failing rather than skipping |

**Run `pytest --require-driver` before tagging a release.** Without it, a
machine whose driver is missing or temporarily unwell reports a clean green
pass having touched no database at all. When live tests are skipped, the run
ends with a `live coverage` summary saying so.

CI runs the live half too, in a `windows live driver` job that installs the
Access Database Engine and runs under `--require-driver` — which is what
stops a silently failed install from skipping everything and still reporting
green. It is not a required check: it downloads 80MB from Microsoft, and
those URLs rot.

Availability is probed, not assumed. The `adox` check creates a database file
through raw COM rather than importing `win32com` and hoping, because ACE has
been seen answering `REGDB_E_CLASSNOTREG` on a machine where the provider is
correctly registered — a fault an import check turns into dozens of errors
instead of one clear skip. The probe deliberately avoids
`create_database_file()`: probing with the code under test would let a
regression in it disable the tests that would have caught the regression.

Documentation is Sphinx, published to
[GitHub Pages](https://zorderelda.github.io/peewee-access/) on every push to
`main`:

```
pip install -e ".[doc]"
sphinx-build -b html -W docs docs/_build/html
```

## License

MIT