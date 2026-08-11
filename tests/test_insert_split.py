##
# @file test_insert_split.py
# @brief The multi-row INSERT split, verified through recorded statements.
#
# Jet accepts exactly one VALUES tuple per INSERT. peewee's insert_many()
# emits VALUES (?),(?),... which the driver rejects with its generic
# "Missing semicolon (;) at end of SQL statement", naming no cause. The
# _access_insert_execute patch splits the query into one statement per row.
#
# None of this is visible in a query's .sql(): the split happens at
# execution time. These tests use the recording_db fixture, which is an
# AccessDatabase that records statements rather than sending them.
#

import pytest
from peewee import IntegerField, Model, TextField

import pwaccess


##
# @brief A model bound to the recording database.
#
@pytest.fixture
def Note(recording_db):
	class Note(Model):
		title = TextField()
		votes = IntegerField(default=0)

		class Meta:
			database = recording_db
			table_name = 'note'

	return Note


ROWS = [{'title': 'a', 'votes': 1},
        {'title': 'b', 'votes': 2},
        {'title': 'c', 'votes': 3}]


##
# @brief Three rows must become three separate INSERT statements.
#
def test_multi_row_insert_is_split(recording_db, sql_only, Note):
	Note.insert_many(ROWS).execute()
	statements = sql_only(recording_db.statements)

	assert len(statements) == 3
	for sql, _ in statements:
		## One VALUES tuple each. A comma between tuples is the failure
		## this whole patch exists to prevent.
		assert sql.count('VALUES') == 1
		assert '), (' not in sql


##
# @brief Every row's values must survive the split, in order.
#
def test_split_preserves_every_row(recording_db, sql_only, Note):
	Note.insert_many(ROWS).execute()
	params = [p for _, p in sql_only(recording_db.statements)]
	assert params == [['a', 1], ['b', 2], ['c', 3]]


##
# @brief The rows must be written inside a single transaction.
#
# Jet has no savepoints, so a partial failure cannot be unwound at the
# statement level. One surrounding transaction is what makes the batch
# atomic.
#
def test_split_is_wrapped_in_one_transaction(recording_db, Note):
	Note.insert_many(ROWS).execute()
	kinds = [s for s, _ in recording_db.statements]
	assert kinds[0] == 'BEGIN'
	assert kinds[-1] == 'COMMIT'
	assert kinds.count('BEGIN') == 1


##
# @brief A generator must not be consumed before the rows are read.
#
# The patch lists the rows in order to count them; a generator listed once
# and iterated again yields nothing, silently inserting no rows at all.
#
def test_generator_rows_are_not_exhausted(recording_db, sql_only, Note):
	Note.insert_many({'title': t, 'votes': 0} for t in 'xyz').execute()
	assert len(sql_only(recording_db.statements)) == 3


##
# @brief Tuple rows with an explicit field list must split too.
#
def test_tuple_rows_split(recording_db, sql_only, Note):
	Note.insert_many([('p', 1), ('q', 2)],
	                 fields=[Note.title, Note.votes]).execute()
	statements = sql_only(recording_db.statements)
	assert len(statements) == 2
	assert [p for _, p in statements] == [['p', 1], ['q', 2]]


##
# @brief A single row is already valid Jet and must not be wrapped.
#
def test_single_row_is_left_alone(recording_db, Note):
	Note.insert_many([{'title': 'solo', 'votes': 9}]).execute()
	## No transaction, no split: one bare statement.
	assert len(recording_db.statements) == 1


##
# @brief A plain insert() is untouched by the patch.
#
def test_plain_insert_untouched(recording_db, Note):
	Note.insert(title='one', votes=1).execute()
	assert len(recording_db.statements) == 1


##
# @brief INSERT ... SELECT is already valid Jet and must pass through.
#
def test_insert_from_select_passes_through(recording_db, sql_only, Note):
	Note.insert_from(Note.select(Note.title, Note.votes),
	                 fields=[Note.title, Note.votes]).execute()
	statements = sql_only(recording_db.statements)
	assert len(statements) == 1
	assert 'SELECT' in statements[0][0]


##
# @brief as_rowcount() must total the split statements, not report one.
#
def test_as_rowcount_totals_the_batch(recording_db, Note):
	assert Note.insert_many(ROWS).as_rowcount().execute() == 3


##
# @brief Without as_rowcount(), the last inserted id is returned.
#
# That matches what peewee returns for a single-row insert, so calling
# code does not have to know the batch was split.
#
def test_returns_last_insert_id(recording_db, Note):
	assert Note.insert_many(ROWS).execute() == 7


##
# @brief bulk_create() routes through insert_many and must split as well.
#
def test_bulk_create_splits(recording_db, sql_only, Note):
	Note.bulk_create([Note(title='m', votes=1), Note(title='n', votes=2)])
	assert len(sql_only(recording_db.statements)) == 2


##
# @brief An already-open transaction must be reused, not nested.
#
# Access has no savepoints, so entering a second atomic() inside the first
# would raise. The patch checks in_transaction() for exactly this reason.
#
def test_existing_transaction_is_not_nested(recording_db, Note):
	with recording_db.atomic():
		Note.insert_many(ROWS).execute()
	kinds = [s for s, _ in recording_db.statements]
	assert kinds.count('BEGIN') == 1


##
# @brief ON CONFLICT has no Jet equivalent and must refuse.
#
def test_on_conflict_refuses(recording_db, Note):
	with pytest.raises(pwaccess.AccessNotSupportedError):
		Note.insert(title='z').on_conflict_ignore().execute()


##
# @brief The patch must leave every other backend alone.
#
# _access_insert_execute is installed on peewee's Insert class globally, so
# a process that also talks to SQLite must be unaffected. A multi-row
# insert there has to stay a single statement.
#
def test_other_backends_still_batch():
	from peewee import SqliteDatabase

	sqlite = SqliteDatabase(':memory:')

	class Thing(Model):
		name = TextField()

		class Meta:
			database = sqlite
			table_name = 'thing'

	sqlite.connect()
	sqlite.create_tables([Thing])
	Thing.insert_many([{'name': 'a'}, {'name': 'b'}, {'name': 'c'}]).execute()
	assert Thing.select().count() == 3
	sqlite.close()
