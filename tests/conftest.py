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

import collections
import functools
import os
import tempfile

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
# @brief Add --require-driver.
#
def pytest_addoption(parser):
	parser.addoption(
		'--require-driver', action='store_true', default=False,
		help='Fail instead of skipping when the Access driver or ADOX is '
		     'unavailable. Intended for the run before tagging a release: '
		     'without it a machine with no driver reports a clean pass '
		     'having exercised no live behaviour at all.')


##
# @brief Whether a usable Access ODBC driver is present.
# @return An (available, reason) pair; reason is '' when available.
#
@functools.lru_cache(maxsize=None)
def _driver_status():
	try:
		driver = pwaccess.detect_driver()
	except Exception as exc:
		return False, 'detect_driver() raised %s: %s' % (
			type(exc).__name__, exc)
	if driver is None:
		return False, 'no Microsoft Access ODBC driver is installed'
	return True, ''


##
# @brief Whether ADOX can actually create a database file.
# @return An (available, reason) pair; reason is '' when available.
#
# Importing win32com is not the same as being able to use it. ACE has been
# observed to answer REGDB_E_CLASSNOTREG transiently on a machine where the
# provider is correctly registered and the DLL present, and an import check
# cannot see that: every adox-marked test then fails at file creation
# rather than skipping, burying the one real cause under dozens of errors.
#
# Probed through raw COM rather than through pwaccess.create_database_file()
# on purpose. Probing with the code under test would let a regression *in*
# that code disable the tests that would have caught it -- the suite would
# report "ADOX unavailable", skip, and pass green.
#
@functools.lru_cache(maxsize=None)
def _adox_status():
	try:
		import win32com.client
	except ImportError as exc:
		return False, 'pywin32 is not installed (%s)' % exc

	directory = tempfile.mkdtemp(prefix='pwaccess-probe-')
	path = os.path.join(directory, 'probe.accdb')
	try:
		catalog = win32com.client.Dispatch('ADOX.Catalog')
		catalog.Create('Provider=Microsoft.ACE.OLEDB.12.0;Data Source=%s;'
		               % path)
		del catalog
	except Exception as exc:
		return False, 'ADOX could not create a database file (%s)' % exc
	finally:
		try:
			if os.path.isfile(path):
				os.remove(path)
			os.rmdir(directory)
		except OSError:
			pass
	return True, ''


#: Live tests skipped this run, keyed by the marker that was unsatisfiable.
#: Reported by pytest_terminal_summary so a green run cannot quietly mean
#: "none of the database behaviour was exercised".
_skipped_counts = collections.Counter()
_skipped_reasons = {}


##
# @brief Skip driver/adox-marked tests when the prerequisite is missing.
#
# With --require-driver the same condition is a failure instead, so a
# release run cannot pass without having touched a real database.
#
def pytest_runtest_setup(item):
	require = item.config.getoption('--require-driver')

	for marker, status in (('driver', _driver_status),
	                       ('adox', _adox_status)):
		if marker not in item.keywords:
			continue
		available, reason = status()
		if available:
			continue

		message = '%s unavailable: %s' % (marker, reason)
		if require:
			pytest.fail(message + ' (--require-driver)', pytrace=False)
		_skipped_counts[marker] += 1
		_skipped_reasons[marker] = reason
		pytest.skip(message)


##
# @brief State plainly when a run covered none of the live behaviour.
#
def pytest_terminal_summary(terminalreporter):
	if not _skipped_counts:
		return

	terminalreporter.write_sep('=', 'live coverage', yellow=True)
	for marker, count in sorted(_skipped_counts.items()):
		terminalreporter.write_line(
			'%d test(s) requiring %r were SKIPPED: %s'
			% (count, marker, _skipped_reasons[marker]), yellow=True)
	terminalreporter.write_line(
		'This run did not exercise a real Access database. Re-run with '
		'--require-driver to turn the above into failures.', yellow=True)


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
# @brief Invoke a migrator operation's body directly, bypassing @operation.
#
# @operation defers every migrator method into an Operation. Through
# peewee 4.3 passing with_context=True ran the body at once instead;
# peewee 4.4 dropped that flag, so the portable route to the body is the
# __wrapped__ attribute functools.wraps leaves on the shim. The result is
# whatever the body returns: a Context for a single statement, or a list
# of further Operations for a composite one.
#
# @return A callable taking (migrator, method_name, *args, **kwargs).
#
@pytest.fixture
def run_body():
	def _run(migrator, method, *args, **kwargs):
		body = getattr(type(migrator), method).__wrapped__
		return body(migrator, *args, **kwargs)
	return _run


##
# @brief Render a single-statement migrator operation to its SQL string.
# @return A callable taking (migrator, method_name, *args) -> SQL text.
#
@pytest.fixture
def render_sql(run_body):
	def _render(migrator, method, *args, **kwargs):
		return run_body(migrator, method, *args, **kwargs).query()[0]
	return _render


##
# @brief The name of the migrator method a deferred Operation will call.
#
# peewee 4.3 stored the name (Operation.method); 4.4 stores the function
# itself (Operation.fn).
#
@pytest.fixture
def operation_name():
	def _name(op):
		method = getattr(op, 'method', None)
		if method is None:
			method = op.fn.__name__
		return method
	return _name


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
