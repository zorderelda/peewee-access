##
# @file test_migrator.py
# @brief AccessMigrator DDL, verified through generated SQL.
#
# Jet diverges from the ANSI DDL peewee emits in three ways that produce
# valid-looking but wrong statements if unhandled, plus six operations it
# cannot express at all.
#

import pytest
from peewee import DoubleField, IntegerField, TextField

import pwaccess


##
# @brief SchemaMigrator.from_database must dispatch to AccessMigrator.
#
def test_dispatch(offline_migrator):
	assert type(offline_migrator).__name__ == 'AccessMigrator'


##
# @brief Jet DDL is not transactional and must advertise that.
#
def test_not_transactional(offline_migrator):
	assert offline_migrator.transactional_ddl is False


##
# @brief DROP COLUMN must not emit CASCADE, which Jet rejects.
#
def test_drop_column_omits_cascade(offline_migrator, render_sql):
	sql = render_sql(offline_migrator, 'drop_column', 'note', 'votes')
	assert sql == 'ALTER TABLE [note] DROP COLUMN [votes]'


##
# @brief cascade=True must be ignored rather than honoured.
#
def test_drop_column_ignores_cascade_argument(offline_migrator, render_sql):
	sql = render_sql(offline_migrator, 'drop_column', 'note', 'votes',
	                 cascade=True)
	assert 'CASCADE' not in sql


##
# @brief Jet spells this "DROP INDEX name ON table".
#
def test_drop_index_includes_table(offline_migrator, render_sql):
	sql = render_sql(offline_migrator, 'drop_index', 'note', 'idx_title')
	assert sql == 'DROP INDEX [idx_title] ON [note]'


##
# @brief ALTER COLUMN takes no TYPE keyword in Jet.
#
def test_alter_column_type_omits_type_keyword(offline_migrator, render_sql):
	sql = render_sql(offline_migrator, '_alter_column_type', 'note',
	                 'votes', IntegerField(null=True))
	assert sql == 'ALTER TABLE [note] ALTER COLUMN [votes] LONG'
	assert ' TYPE ' not in sql


##
# @brief Access has no SET NOT NULL, so it is restated inline.
#
def test_alter_column_type_restates_not_null(offline_migrator, render_sql):
	sql = render_sql(offline_migrator, '_alter_column_type', 'note',
	                 'votes', IntegerField(null=False))
	assert sql == 'ALTER TABLE [note] ALTER COLUMN [votes] LONG NOT NULL'


##
# @brief The peewee type map must reach the ALTER statement.
#
def test_alter_column_type_uses_access_types(offline_migrator, render_sql):
	sql = render_sql(offline_migrator, '_alter_column_type', 'note',
	                 'votes', DoubleField(null=True))
	assert sql.endswith('DOUBLE')


##
# @brief A cast must refuse when written, not when migrate() runs it.
#
# alter_column_type() is a plain method that validates and then delegates
# to the @operation-decorated _alter_column_type(). Were the check inside
# the deferred operation, this call would return an Operation and only
# fail later.
#
def test_cast_refuses_eagerly(offline_migrator):
	with pytest.raises(pwaccess.AccessNotSupportedError):
		offline_migrator.alter_column_type('note', 'votes',
		                                   IntegerField(),
		                                   cast='CLng(votes)')


##
# @brief Without a cast, the call defers as normal.
#
def test_without_cast_defers(offline_migrator):
	operation = offline_migrator.alter_column_type('note', 'votes',
	                                               IntegerField())
	assert hasattr(operation, 'run')


##
# @brief Operations Jet SQL cannot express must raise with guidance.
#
@pytest.mark.parametrize('method,args', [
	('rename_column', ('note', 'body', 'content')),
	('rename_table', ('note', 'notes')),
	('add_not_null', ('note', 'body')),
	('drop_not_null', ('note', 'body')),
	('add_column_default', ('note', 'votes', 1)),
	('drop_column_default', ('note', 'votes')),
])
def test_unsupported_operations_refuse(offline_migrator, method, args):
	with pytest.raises(pwaccess.AccessNotSupportedError) as excinfo:
		getattr(offline_migrator, method)(*args)
	## The message must suggest a way forward, not merely refuse.
	assert len(str(excinfo.value)) > 40


##
# @brief A nullable column is added with a single statement.
#
def test_add_column_nullable(offline_migrator, run_body):
	## run_body() invokes the operation body directly instead of deferring
	## it, which is what migrate() ultimately does.
	operations = run_body(offline_migrator, 'add_column', 'note', 'flags',
	                      IntegerField(null=True))
	## One statement only: no default to back-fill, no index to build.
	assert len(operations) == 1


##
# @brief A non-null column is created, back-filled, and left nullable.
#
# Access cannot add a NOT NULL constraint to an existing column, so the
# base implementation's trailing add_not_null() step is omitted. Were it
# kept, add_column() would raise for every non-null field.
#
def test_add_column_not_null_skips_constraint(offline_migrator, run_body,
                                              operation_name, caplog):
	import logging

	with caplog.at_level(logging.WARNING, logger='peewee'):
		operations = run_body(
			offline_migrator, 'add_column',
			'note', 'votes', IntegerField(null=False, default=0))

	assert isinstance(operations, list)
	assert len(operations) == 2          # ADD COLUMN, then UPDATE
	assert 'NOT NULL' in caplog.text

	## Crucially, no add_not_null step: that would raise.
	assert not any(operation_name(op) == 'add_not_null' for op in operations)


##
# @brief An indexed column also produces a CREATE INDEX.
#
def test_add_column_with_index(offline_migrator, run_body):
	operations = run_body(offline_migrator, 'add_column',
	                      'note', 'tag', TextField(null=True, index=True))
	assert isinstance(operations, list)
	assert len(operations) == 2          # ADD COLUMN, then CREATE INDEX


##
# @brief A non-null column with no default must refuse.
#
# The non-null path reimplements the base add_column() minus its trailing
# add_not_null(). Reimplementing it means re-stating the guards it makes,
# and this is the one that matters most: without it the back-fill step
# runs anyway and emits UPDATE note SET votes = NULL, quietly writing
# NULLs into a column the caller asked to be non-null.
#
def test_add_column_not_null_without_default_refuses(offline_migrator,
                                                     run_body):
	with pytest.raises(ValueError) as excinfo:
		run_body(offline_migrator, 'add_column', 'note', 'votes',
		         IntegerField(null=False))
	assert 'default' in str(excinfo.value)


##
# @brief A non-null foreign key must still get its constraint.
#
# AccessMigrator sets explicit_create_foreign_key, so the constraint is a
# separate statement rather than part of the column definition. Omitting
# it leaves an ordinary integer column where a relationship was asked for
# -- which reflection then cannot see either.
#
def test_add_column_not_null_foreign_key_keeps_constraint(offline_migrator,
                                                          run_body,
                                                          operation_name):
	from peewee import ForeignKeyField, Model

	class Note(Model):
		class Meta:
			database = offline_migrator.database
			table_name = 'note'

	field = ForeignKeyField(Note, field=Note.id, null=False, default=1)
	field.name = field.column_name = 'note_id'

	operations = run_body(offline_migrator, 'add_column',
	                      'comment', 'note_id', field)
	methods = [operation_name(op) for op in operations]
	assert 'add_foreign_key_constraint' in methods
	## And the NOT NULL step is still absent, which is the whole point of
	## overriding add_column() in the first place.
	assert 'add_not_null' not in methods


##
# @brief A nullable foreign key goes through the base implementation.
#
def test_add_column_nullable_foreign_key(offline_migrator, run_body,
                                         operation_name):
	from peewee import ForeignKeyField, Model

	class Note(Model):
		class Meta:
			database = offline_migrator.database
			table_name = 'note'

	field = ForeignKeyField(Note, field=Note.id, null=True)
	field.name = field.column_name = 'note_id'

	operations = run_body(offline_migrator, 'add_column',
	                      'comment', 'note_id', field)
	methods = [operation_name(op) for op in operations]
	assert 'add_foreign_key_constraint' in methods
	assert 'add_not_null' not in methods


##
# @brief A non-null column with a default is back-filled, not nulled.
#
def test_add_column_backfills_the_default(offline_migrator, run_body,
                                          operation_name):
	operations = run_body(
		offline_migrator, 'add_column',
		'note', 'votes', IntegerField(null=False, default=7))
	apply_default = [op for op in operations
	                 if operation_name(op) == 'apply_default']
	assert len(apply_default) == 1
	## The field handed to apply_default must still carry its default; the
	## non-null path temporarily clears null on a copy and has to put the
	## default back before the back-fill is queued.
	assert apply_default[0].args[2].default == 7


##
# @brief allow_not_null must emit a single NOT NULL ADD COLUMN.
#
# peewee 4.4 added the flag for every backend: one statement, no
# back-fill, no add_not_null() step. That last point is what makes it
# usable on Access at all, so the override must pass it through rather
# than divert it into the back-fill path.
#
def test_add_column_allow_not_null(offline_migrator, run_body,
                                   operation_name):
	import inspect

	from playhouse.migrate import SchemaMigrator

	base = SchemaMigrator.add_column.__wrapped__
	if 'allow_not_null' not in inspect.signature(base).parameters:
		pytest.skip('allow_not_null needs peewee >= 4.4')

	operations = run_body(offline_migrator, 'add_column', 'note', 'votes',
	                      IntegerField(null=False), allow_not_null=True)
	assert [operation_name(op) for op in operations] == ['alter_add_column']

	op = operations[0]
	sql = run_body(offline_migrator, 'alter_add_column',
	               *op.args, **op.kwargs).query()[0]
	assert sql == 'ALTER TABLE [note] ADD COLUMN [votes] LONG NOT NULL'


##
# @brief A deferred operation must still execute under migrate().
#
# The tests above call the operation bodies directly. This one goes
# through the deferral layer migrate() uses, which is where peewee 4.4
# changed shape: the with_context flag the overrides once passed to the
# base class is gone, and an Operation now calls the body itself. Under
# 4.4+ the old overrides raised TypeError here for drop_column() and a
# nullable add_column(), while every direct-call test still passed.
#
def test_deferred_operation_executes(recording_db, sql_only):
	from playhouse.migrate import SchemaMigrator, migrate

	recording_db.get_foreign_keys = lambda table, schema=None: []
	migrator = SchemaMigrator.from_database(recording_db)

	migrate(migrator.drop_column('note', 'votes'),
	        migrator.add_column('note', 'flags', IntegerField(null=True)),
	        migrator.add_column('note', 'score',
	                            IntegerField(null=False, default=0)))

	assert sql_only(recording_db.statements) == [
		('ALTER TABLE [note] DROP COLUMN [votes]', []),
		('ALTER TABLE [note] ADD COLUMN [flags] LONG', []),
		('ALTER TABLE [note] ADD COLUMN [score] LONG', []),
		('UPDATE [note] SET [score] = ?', [0]),
	]


##
# @brief from_database() must take the schema= keyword peewee 4.4 added.
#
# playhouse.migrations.Runner always passes it, as None. A real value
# must refuse: Access has no schemas to qualify a table name with.
#
def test_from_database_schema_keyword(offline_db):
	from playhouse.migrate import SchemaMigrator

	migrator = SchemaMigrator.from_database(offline_db, schema=None)
	assert type(migrator).__name__ == 'AccessMigrator'

	with pytest.raises(pwaccess.AccessNotSupportedError):
		SchemaMigrator.from_database(offline_db, schema='dbo')


##
# @brief from_database() must see through an initialised Proxy.
#
def test_from_database_unwraps_proxy(offline_db):
	from peewee import Proxy
	from playhouse.migrate import SchemaMigrator

	proxy = Proxy()
	proxy.initialize(offline_db)
	migrator = SchemaMigrator.from_database(proxy)
	assert type(migrator).__name__ == 'AccessMigrator'
	assert migrator.database is offline_db


##
# @brief Other backends must still reach their own migrator.
#
def test_from_database_other_backends_untouched():
	from peewee import SqliteDatabase
	from playhouse.migrate import SchemaMigrator

	migrator = SchemaMigrator.from_database(SqliteDatabase(':memory:'))
	assert type(migrator).__name__ == 'SqliteMigrator'
