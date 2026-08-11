##
# @file test_live_tooling.py
# @brief DataSet, pwiz and pooling against a real Access database.
#

import pytest

pytestmark = [pytest.mark.driver, pytest.mark.adox]


# ---------------------------------------------------------------------------
# playhouse.dataset
# ---------------------------------------------------------------------------

##
# @brief DataSet needs db_url, reflection and migrate all working at once.
#
def test_dataset_round_trip(live_db, live_models, accdb_path):
	from playhouse.dataset import DataSet

	dataset = DataSet('access:///' + accdb_path.replace('\\', '/'))
	try:
		assert 'note' in dataset.tables

		table = dataset['note']
		table.insert(title='from dataset', votes=7)

		rows = list(table.find(title='from dataset'))
		assert len(rows) == 1
		assert rows[0]['votes'] == 7

		table.delete(title='from dataset')
		assert not list(table.find(title='from dataset'))
	finally:
		dataset.close()


# ---------------------------------------------------------------------------
# pwiz
# ---------------------------------------------------------------------------

##
# @brief The access engine must be registered with pwiz.
#
def test_pwiz_engine_registered():
	import pwiz
	assert 'access' in pwiz.DATABASE_MAP
	assert 'msaccess' in pwiz.DATABASE_MAP


##
# @brief Generated code must import AccessDatabase, or it will not run.
#
def test_pwiz_emits_extension_import(live_db, live_models, accdb_path):
	import contextlib
	import io

	import pwiz

	introspector = pwiz.make_introspector('access', accdb_path)
	buffer = io.StringIO()
	with contextlib.redirect_stdout(buffer):
		pwiz.print_models(introspector)
	generated = buffer.getvalue()

	assert 'from pwaccess import AccessDatabase' in generated
	assert 'class Note' in generated
	assert 'ForeignKeyField' in generated


##
# @brief The generated module must be syntactically valid Python.
#
def test_pwiz_output_parses(live_db, live_models, accdb_path):
	import ast
	import contextlib
	import io

	import pwiz

	introspector = pwiz.make_introspector('access', accdb_path)
	buffer = io.StringIO()
	with contextlib.redirect_stdout(buffer):
		pwiz.print_models(introspector)

	ast.parse(buffer.getvalue())


# ---------------------------------------------------------------------------
# Pooling
# ---------------------------------------------------------------------------

##
# @brief The liveness probe must not depend on MSysObjects.
#
# Access denies read permission on the system tables by default, so a
# SELECT-based probe reports every connection dead and the pool silently
# reopens on every checkout.
#
def test_pool_probe_reports_live_connection(accdb_path):
	import pwaccess

	pool = pwaccess.PooledAccessDatabase(accdb_path, max_connections=2)
	pool.connect()
	try:
		assert pool._is_closed(pool.connection()) is False
	finally:
		pool.close()


##
# @brief A returned connection must be reused, not reopened.
#
def test_pool_reuses_connection(accdb_path):
	import pwaccess

	pool = pwaccess.PooledAccessDatabase(accdb_path, max_connections=2)
	pool.connect()
	first = pool.connection()
	pool.close()

	pool.connect()
	try:
		assert pool.connection() is first
	finally:
		pool.close()


##
# @brief MSysObjects really is unreadable, which is why the probe changed.
#
def test_msysobjects_is_unreadable(live_db, live_models):
	with pytest.raises(Exception):
		live_db.execute_sql('SELECT TOP 1 1 FROM MSysObjects').fetchone()
