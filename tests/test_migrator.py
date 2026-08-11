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
def test_add_column_nullable(offline_migrator):
	## with_context=True runs the operation body immediately instead of
	## deferring it, which is how migrate() ultimately invokes it.
	operations = offline_migrator.add_column('note', 'flags',
	                                         IntegerField(null=True),
	                                         with_context=True)
	## One statement only: no default to back-fill, no index to build.
	assert len(operations) == 1


##
# @brief A non-null column is created, back-filled, and left nullable.
#
# Access cannot add a NOT NULL constraint to an existing column, so the
# base implementation's trailing add_not_null() step is omitted. Were it
# kept, add_column() would raise for every non-null field.
#
def test_add_column_not_null_skips_constraint(offline_migrator, caplog):
	import logging

	with caplog.at_level(logging.WARNING, logger='peewee'):
		operations = offline_migrator.add_column(
			'note', 'votes', IntegerField(null=False, default=0),
			with_context=True)

	assert isinstance(operations, list)
	assert len(operations) == 2          # ADD COLUMN, then UPDATE
	assert 'NOT NULL' in caplog.text

	## Crucially, no add_not_null step: that would raise.
	assert not any(getattr(op, 'method', '') == 'add_not_null'
	               for op in operations)


##
# @brief An indexed column also produces a CREATE INDEX.
#
def test_add_column_with_index(offline_migrator):
	operations = offline_migrator.add_column(
		'note', 'tag', TextField(null=True, index=True),
		with_context=True)
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
def test_add_column_not_null_without_default_refuses(offline_migrator):
	with pytest.raises(ValueError) as excinfo:
		offline_migrator.add_column('note', 'votes',
		                            IntegerField(null=False),
		                            with_context=True)
	assert 'default' in str(excinfo.value)


##
# @brief A non-null foreign key must still get its constraint.
#
# AccessMigrator sets explicit_create_foreign_key, so the constraint is a
# separate statement rather than part of the column definition. Omitting
# it leaves an ordinary integer column where a relationship was asked for
# -- which reflection then cannot see either.
#
def test_add_column_not_null_foreign_key_keeps_constraint(offline_migrator):
	from peewee import ForeignKeyField, Model

	class Note(Model):
		class Meta:
			database = offline_migrator.database
			table_name = 'note'

	field = ForeignKeyField(Note, field=Note.id, null=False, default=1)
	field.name = field.column_name = 'note_id'

	operations = offline_migrator.add_column('comment', 'note_id', field,
	                                         with_context=True)
	methods = [getattr(op, 'method', None) for op in operations]
	assert 'add_foreign_key_constraint' in methods
	## And the NOT NULL step is still absent, which is the whole point of
	## overriding add_column() in the first place.
	assert 'add_not_null' not in methods


##
# @brief A nullable foreign key goes through the base implementation.
#
def test_add_column_nullable_foreign_key(offline_migrator):
	from peewee import ForeignKeyField, Model

	class Note(Model):
		class Meta:
			database = offline_migrator.database
			table_name = 'note'

	field = ForeignKeyField(Note, field=Note.id, null=True)
	field.name = field.column_name = 'note_id'

	operations = offline_migrator.add_column('comment', 'note_id', field,
	                                         with_context=True)
	methods = [getattr(op, 'method', None) for op in operations]
	assert 'add_foreign_key_constraint' in methods
	assert 'add_not_null' not in methods


##
# @brief A non-null column with a default is back-filled, not nulled.
#
def test_add_column_backfills_the_default(offline_migrator):
	operations = offline_migrator.add_column(
		'note', 'votes', IntegerField(null=False, default=7),
		with_context=True)
	apply_default = [op for op in operations
	                 if getattr(op, 'method', None) == 'apply_default']
	assert len(apply_default) == 1
	## The field handed to apply_default must still carry its default; the
	## non-null path temporarily clears null on a copy and has to put the
	## default back before the back-fill is queued.
	assert apply_default[0].args[2].default == 7
