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
| No `OFFSET` | Keyset pagination — `.where(Model.id > last_id).limit(n)` |
| No savepoints | One level of `atomic()`; nested blocks raise |
| No sequences, `TRUNCATE TABLE`, `FULL OUTER JOIN`, `INTERSECT`, `EXCEPT` | — |
| No 64-bit integers | `BigIntegerField` / `BigAutoField` map to 32-bit types and will overflow past 2³¹−1 |
| `INSERT ... DEFAULT VALUES` unsupported | Supply at least one explicit column |
| Single writer | Serialize writes in your application |

`LIMIT n` is rewritten to `SELECT TOP n` at execution time, since Access
will not accept a parameter marker in a `TOP` clause. A non-zero `OFFSET`
raises `AccessNotSupportedError` with keyset-pagination guidance.

---

## How it works

Importing `pwaccess` applies four patches to peewee's SQL generation. Each
is gated on the Access dialect flag and delegates to peewee's original
implementation for every other database, so SQLite, PostgreSQL and MySQL
connections in the same process are unaffected. The patches are idempotent
and removable with `pwaccess.uninstall()`.

| Patch | Reason |
|---|---|
| `Field.ddl` | Omit `NOT NULL` for types that reject it; strip precision from `CURRENCY`; emit an indexed `TextField` as `TEXT(255)`, since Access cannot index a `MEMO` |
| `SchemaManager._create_table` / `._drop_table` | Access rejects `IF NOT EXISTS` / `IF EXISTS` |
| `Join.__sql__` | Access requires `FROM ((a JOIN b) JOIN c)`, not a flat join chain |

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
* Python 3.8+
* Microsoft Access Database Engine, bitness matching your interpreter
* `.accdb` (ACE) and `.mdb` (JET) files are both supported

## License

MIT