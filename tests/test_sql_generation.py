##
# @file test_sql_generation.py
# @brief The four peewee patches, verified through generated SQL.
#
# None of these need a connection: peewee builds statements from the
# dialect metadata carried on the Database class.
#

import pytest
from peewee import (
	ForeignKeyField,
	IntegerField,
	Model,
	TextField,
)

import pwaccess


##
# @brief Build a throwaway model bound to the offline database.
#
def _model(database, **fields):
	attrs = dict(fields)
	attrs['Meta'] = type('Meta', (), {'database': database,
	                                  'table_name': 'thing'})
	return type('Thing', (Model,), attrs)


##
# @brief The patches must be installed on import.
#
def test_patches_installed():
	assert pwaccess.is_installed()


##
# @brief The tooling must be wired on import.
#
def test_tooling_registered():
	assert pwaccess.tooling_registered()


##
# @brief An indexed TextField becomes TEXT(255): Access cannot index MEMO.
#
def test_unique_text_is_bounded(offline_db):
	model = _model(offline_db, title=TextField(unique=True))
	sql = model._schema._create_table(safe=False).query()[0]
	assert 'TEXT(255)' in sql
	assert 'MEMO' not in sql


##
# @brief A plain TextField stays MEMO.
#
def test_plain_text_is_memo(offline_db):
	model = _model(offline_db, body=TextField(null=True))
	sql = model._schema._create_table(safe=False).query()[0]
	assert 'MEMO' in sql


##
# @brief MEMO columns must not carry NOT NULL, which Access rejects.
#
def test_memo_omits_not_null(offline_db):
	model = _model(offline_db, body=TextField())
	sql = model._schema._create_table(safe=False).query()[0]
	assert 'MEMO NOT NULL' not in sql


##
# @brief Types that accept NOT NULL must still receive it.
#
def test_not_null_emitted_where_supported(offline_db):
	model = _model(offline_db, votes=IntegerField())
	sql = model._schema._create_table(safe=False).query()[0]
	assert 'LONG NOT NULL' in sql


##
# @brief Access rejects IF NOT EXISTS, so safe=True must not emit it.
#
def test_create_table_has_no_if_not_exists(offline_db):
	model = _model(offline_db, votes=IntegerField())
	sql = model._schema._create_table(safe=True).query()[0]
	assert 'IF NOT EXISTS' not in sql


##
# @brief Access rejects IF EXISTS on DROP TABLE.
#
def test_drop_table_has_no_if_exists(offline_db):
	model = _model(offline_db, votes=IntegerField())
	sql = model._schema._drop_table(safe=True).query()[0]
	assert 'IF EXISTS' not in sql


##
# @brief A three-table join must be nested in parentheses for Access.
#
def test_multi_join_is_nested(offline_db):
	class Author(Model):
		name = TextField()

		class Meta:
			database = offline_db
			table_name = 'author'

	class Book(Model):
		author = ForeignKeyField(Author)

		class Meta:
			database = offline_db
			table_name = 'book'

	class Review(Model):
		book = ForeignKeyField(Book)

		class Meta:
			database = offline_db
			table_name = 'review'

	query = Review.select().join(Book).join(Author)
	sql = query.sql()[0]

	## Jet requires each nested join to be parenthesized:
	##   FROM ([a] JOIN [b] ON ...) JOIN [c] ON ...
	## The outermost pair is not required. A flat chain, which every
	## other engine accepts, is a syntax error in Access.
	assert 'FROM ([review]' in sql, sql
	assert ') INNER JOIN [author]' in sql, sql


##
# @brief LIMIT must be rewritten to TOP, which takes no parameter marker.
#
def test_limit_becomes_top(offline_db):
	model = _model(offline_db, votes=IntegerField())
	sql, params = model.select().limit(5).sql()
	rewritten, rewritten_params = pwaccess._sql.rewrite_limit_to_top(
		sql, params)
	assert 'TOP 5' in rewritten
	assert 'LIMIT' not in rewritten


##
# @brief A non-zero OFFSET must refuse, with keyset guidance.
#
def test_offset_refuses(offline_db):
	model = _model(offline_db, votes=IntegerField())
	sql, params = model.select().limit(5).offset(10).sql()
	with pytest.raises(pwaccess.AccessNotSupportedError):
		pwaccess._sql.rewrite_limit_to_top(sql, params)


##
# @brief Constructs Access cannot express must raise, not emit bad SQL.
#
@pytest.mark.parametrize('method,args', [
	('sequence_exists', ('seq',)),
	('default_values_insert', (None,)),
])
def test_unsupported_constructs_raise(offline_db, method, args):
	with pytest.raises(pwaccess.AccessNotSupportedError):
		getattr(offline_db, method)(*args)
