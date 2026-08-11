##
# @file test_patches_lifecycle.py
# @brief install() / uninstall() and the isolation of other backends.
#
# The patches are applied to peewee's own classes, process-wide. Two
# properties follow from that and both are load-bearing:
#
#   1. They must be reversible and re-appliable, or a test suite that
#      calls uninstall() leaves peewee permanently altered.
#   2. They must be inert for every non-Access database, or importing
#      pwaccess breaks an application's SQLite and Postgres connections.
#

import pytest
from peewee import IntegerField, Model, SqliteDatabase, TextField

import pwaccess
from pwaccess import _patches


##
# @brief Restore the patched state whatever a test leaves behind.
#
@pytest.fixture(autouse=True)
def restore_patches():
	yield
	if not _patches.is_installed():
		_patches.install()


##
# @brief Importing the package must leave the patches installed.
#
def test_installed_on_import():
	assert pwaccess.is_installed()


##
# @brief A second install() must report that it did nothing.
#
def test_install_is_idempotent():
	assert _patches.install() is False
	assert _patches.is_installed()


##
# @brief uninstall() must restore peewee's own methods.
#
def test_uninstall_restores_peewee(offline_db):
	class Thing(Model):
		n = IntegerField()

		class Meta:
			database = offline_db
			table_name = 'thing'

	patched = Thing._schema._create_table(safe=True).query()[0]
	assert 'IF NOT EXISTS' not in patched

	assert _patches.uninstall() is True
	assert _patches.is_installed() is False

	## peewee's own _create_table is back, so safe=True emits the clause
	## Access cannot parse.
	restored = Thing._schema._create_table(safe=True).query()[0]
	assert 'IF NOT EXISTS' in restored


##
# @brief A second uninstall() must report that it did nothing.
#
def test_uninstall_is_idempotent():
	_patches.uninstall()
	assert _patches.uninstall() is False


##
# @brief install() after uninstall() must take effect again.
#
# The wrappers stash the original on themselves, so a reinstall must not
# capture an already-patched method as the "original" -- that would
# delegate to a wrapper and recurse.
#
def test_reinstall_after_uninstall(offline_db):
	class Thing(Model):
		n = IntegerField()

		class Meta:
			database = offline_db
			table_name = 'thing'

	_patches.uninstall()
	assert _patches.install() is True

	sql = Thing._schema._create_table(safe=True).query()[0]
	assert 'IF NOT EXISTS' not in sql
	## And the column DDL wrapper is live again, not doubled up.
	assert sql.count('LONG') == 1


##
# @brief Every wrapper must carry the marker the reload path relies on.
#
def test_wrappers_carry_their_original():
	from peewee import Field, Insert, Join, SchemaManager

	for owner, name in ((Field, 'ddl'),
	                    (SchemaManager, '_create_table'),
	                    (SchemaManager, '_drop_table'),
	                    (Join, '__sql__'),
	                    (Insert, '_execute')):
		wrapper = getattr(owner, name)
		assert getattr(wrapper, '_pwaccess_patch', False), name
		assert getattr(wrapper, '_pwaccess_original', None) is not None, name


# ---------------------------------------------------------------------------
# Other backends must be unaffected
# ---------------------------------------------------------------------------

##
# @brief A fixture giving a live in-memory SQLite database.
#
@pytest.fixture
def sqlite_models():
	sqlite = SqliteDatabase(':memory:')

	class Author(Model):
		name = TextField()

		class Meta:
			database = sqlite
			table_name = 'author'

	sqlite.connect()
	sqlite.create_tables([Author])
	yield sqlite, Author
	sqlite.close()


##
# @brief SQLite must still get IF NOT EXISTS from safe=True.
#
def test_sqlite_keeps_if_not_exists(sqlite_models):
	_, Author = sqlite_models
	sql = Author._schema._create_table(safe=True).query()[0]
	assert 'IF NOT EXISTS' in sql


##
# @brief SQLite must still get an unbounded TEXT column, not TEXT(255).
#
def test_sqlite_keeps_its_own_types(sqlite_models):
	_, Author = sqlite_models
	sql = Author._schema._create_table(safe=False).query()[0]
	assert 'TEXT(255)' not in sql
	assert 'MEMO' not in sql


##
# @brief SQLite must still emit a flat, unparenthesized join chain.
#
def test_sqlite_joins_are_not_nested():
	from peewee import ForeignKeyField

	sqlite = SqliteDatabase(':memory:')

	class A(Model):
		class Meta:
			database = sqlite
			table_name = 'a'

	class B(Model):
		a = ForeignKeyField(A)

		class Meta:
			database = sqlite
			table_name = 'b'

	class C(Model):
		b = ForeignKeyField(B)

		class Meta:
			database = sqlite
			table_name = 'c'

	sql = C.select().join(B).join(A).sql()[0]
	assert 'FROM ("c"' not in sql


##
# @brief SQLite must still get LIMIT and OFFSET, not TOP.
#
def test_sqlite_keeps_limit_and_offset(sqlite_models):
	_, Author = sqlite_models
	sql = Author.select().limit(5).offset(10).sql()[0]
	assert 'LIMIT' in sql
	assert 'OFFSET' in sql
	assert 'TOP' not in sql
