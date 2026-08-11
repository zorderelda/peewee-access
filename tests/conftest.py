##
# @file conftest.py
# @brief Shared fixtures and driver detection for the pwaccess test suite.
#
# The suite is split in two. Tests that only exercise SQL generation, URL
# parsing and dialect metadata need no database and run on any platform.
# Tests that touch a real .accdb/.mdb file are marked @pytest.mark.driver
# and skip automatically when the Microsoft Access ODBC driver is absent,
# which is every non-Windows machine and any Windows box without the
# Access Database Engine installed.
#

import pytest

import pwaccess


##
# @brief Register the custom markers so --strict-markers passes.
#
def pytest_configure(config):
	config.addinivalue_line(
		'markers',
		'driver: requires a live Microsoft Access ODBC driver')
	config.addinivalue_line(
		'markers',
		'adox: requires the ADOX COM interface (pywin32 on Windows)')


##
# @brief Whether a usable Access ODBC driver is present.
# @return True when pyodbc reports an Access driver.
#
def _has_driver():
	try:
		return pwaccess.detect_driver() is not None
	except Exception:
		return False


##
# @brief Whether ADOX can be dispatched.
# @return True when pywin32 is importable.
#
def _has_adox():
	try:
		import win32com.client  # noqa: F401
	except ImportError:
		return False
	return True


HAS_DRIVER = _has_driver()
HAS_ADOX = _has_adox()


##
# @brief Skip driver/adox-marked tests when the prerequisite is missing.
#
def pytest_runtest_setup(item):
	if 'driver' in item.keywords and not HAS_DRIVER:
		pytest.skip('no Microsoft Access ODBC driver installed')
	if 'adox' in item.keywords and not HAS_ADOX:
		pytest.skip('pywin32 / ADOX not available')


# ---------------------------------------------------------------------------
# Offline fixtures -- no database file, no driver
# ---------------------------------------------------------------------------

##
# @brief An AccessDatabase that is never connected.
#
# Sufficient for SQL generation: peewee builds statements from the
# dialect metadata on the class, not from a live connection.
#
@pytest.fixture
def offline_db():
	return pwaccess.AccessDatabase(r'C:\nonexistent\offline.accdb')


##
# @brief An AccessMigrator bound to the offline database.
#
# Foreign-key lookups are stubbed out, because the base drop_column()
# consults them and would otherwise demand a connection.
#
@pytest.fixture
def offline_migrator(offline_db):
	from playhouse.migrate import SchemaMigrator

	offline_db.get_foreign_keys = lambda table, schema=None: []
	return SchemaMigrator.from_database(offline_db)


##
# @brief Render a migrator operation to its SQL string.
# @return A callable taking (migrator, method_name, *args) -> SQL text.
#
@pytest.fixture
def render_sql():
	def _render(migrator, method, *args, **kwargs):
		kwargs['with_context'] = True
		return getattr(migrator, method)(*args, **kwargs).query()[0]
	return _render


# ---------------------------------------------------------------------------
# Recording database -- executes nothing, records everything
# ---------------------------------------------------------------------------

##
# @brief A connection handle that satisfies peewee without a driver.
#
class FakeConnection(object):
	autocommit = True

	def close(self):
		pass

	def commit(self):
		pass

	def rollback(self):
		pass


##
# @brief A cursor that satisfies peewee without touching a driver.
#
class FakeCursor(object):
	description = None
	rowcount = 1
	lastrowid = None

	def fetchone(self):
		return [7]

	def fetchall(self):
		return []

	def execute(self, sql, params=None):
		return self

	def close(self):
		pass


##
# @brief An AccessDatabase that records SQL instead of executing it.
#
# The execution-time behaviour -- the LIMIT-to-TOP rewrite and the
# multi-row INSERT split -- runs on the way to the driver, so it cannot be
# reached by inspecting a query's .sql(). It needs a database that peewee
# believes is connected. This is that database: every statement peewee
# hands it is rewritten exactly as the real backend would, then appended to
# .statements instead of being sent anywhere.
#
class RecordingAccess(pwaccess.AccessDatabase):

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.statements = []

	def _connect(self):
		return FakeConnection()

	def _initialize_connection(self, conn):
		pass

	def _set_server_version(self, conn):
		self.server_version = (4, 0, 0)

	def cursor(self, commit=None, named_cursor=None):
		return FakeCursor()

	def execute_sql(self, sql, params=None, commit=None):
		sql, params = pwaccess._sql.rewrite_limit_to_top(sql, params)
		self.statements.append((sql, list(params or [])))
		return FakeCursor()

	def last_insert_id(self, cursor, query_type=None):
		return 7

	## Transactions are recorded rather than driven: there is no pyodbc
	## connection to toggle autocommit on.
	def begin(self):
		self.statements.append(('BEGIN', []))

	def commit(self):
		self.statements.append(('COMMIT', []))

	def rollback(self):
		self.statements.append(('ROLLBACK', []))


##
# @brief A connected RecordingAccess, cleared before each test.
#
@pytest.fixture
def recording_db():
	database = RecordingAccess(r'C:\nonexistent\recording.accdb')
	database.connect()
	yield database
	if not database.is_closed():
		database.close()


##
# @brief Statements from recording_db with the BEGIN/COMMIT noise removed.
#
@pytest.fixture
def sql_only():
	def _filter(statements):
		return [(s, p) for s, p in statements
		        if s not in ('BEGIN', 'COMMIT', 'ROLLBACK')]
	return _filter


# ---------------------------------------------------------------------------
# Live fixtures -- real file, real driver
# ---------------------------------------------------------------------------

##
# @brief Path to a scratch .accdb, created once per test session.
#
@pytest.fixture(scope='session')
def accdb_path(tmp_path_factory):
	directory = tmp_path_factory.mktemp('pwaccess')
	return str(directory / 'suite.accdb')


##
# @brief A connected AccessDatabase against the scratch file.
#
@pytest.fixture(scope='session')
def live_db(accdb_path):
	database = pwaccess.AccessDatabase(accdb_path)
	database.connect()
	yield database
	if not database.is_closed():
		database.close()


##
# @brief Model classes bound to the live database, tables created.
#
# Returns a (Note, Comment) tuple. Note carries one column of each
# interesting type plus a unique constraint; Comment carries a foreign
# key, so reflection has a relationship to find.
#
@pytest.fixture(scope='session')
def live_models(live_db):
	from peewee import (
		DateTimeField,
		ForeignKeyField,
		IntegerField,
		Model,
		TextField,
	)

	class Note(Model):
		title = TextField(unique=True)
		body = TextField(null=True)
		votes = IntegerField(default=0)
		created = DateTimeField(null=True)

		class Meta:
			database = live_db
			table_name = 'note'

	class Comment(Model):
		note = ForeignKeyField(Note, backref='comments')
		body = TextField(null=True)

		class Meta:
			database = live_db
			table_name = 'comment'

	live_db.drop_tables([Comment, Note], safe=True)
	live_db.create_tables([Note, Comment])
	yield Note, Comment
	live_db.drop_tables([Comment, Note], safe=True)


##
# @brief Column metadata for a table, keyed by column name.
#
@pytest.fixture
def columns_of(live_db):
	def _columns(table):
		return {c.name: c for c in live_db.get_columns(table)}
	return _columns
