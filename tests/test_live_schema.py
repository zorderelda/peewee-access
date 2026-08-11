##
# @file test_live_schema.py
# @brief Catalog introspection against a real Access database.
#
# The Access ODBC driver does not implement SQLPrimaryKeys or
# SQLForeignKeys, and reports every non-key column as nullable regardless
# of its actual constraint. Each of these tests fails without the ADOX
# fallback, and each failure mode is silent rather than loud, which is why
# they are asserted individually.
#

import pytest

pytestmark = [pytest.mark.driver, pytest.mark.adox]


##
# @brief The scratch file must be created automatically.
#
def test_file_created(live_db, live_models, accdb_path):
	import os
	assert os.path.isfile(accdb_path)


##
# @brief Both tables must be visible, and system tables hidden.
#
def test_get_tables(live_db, live_models):
	tables = live_db.get_tables()
	assert 'note' in tables
	assert 'comment' in tables
	assert not any(t.startswith('MSys') for t in tables)


##
# @brief The primary key must be found despite SQLPrimaryKeys answering
#        IM001. An empty result here makes reflection raise
#        "over-determined primary key".
#
def test_primary_key_found(live_db, live_models):
	assert live_db.get_primary_keys('note') == ['id']
	assert live_db.get_primary_keys('comment') == ['id']


##
# @brief The foreign key must be found despite SQLForeignKeys answering
#        IM001. An empty result reflects the column as IntegerField.
#
def test_foreign_key_found(live_db, live_models):
	foreign_keys = live_db.get_foreign_keys('comment')
	assert len(foreign_keys) == 1
	assert foreign_keys[0].column == 'note_id'
	assert foreign_keys[0].dest_table == 'note'
	assert foreign_keys[0].dest_column == 'id'


##
# @brief An AUTOINCREMENT column must be flagged as an identity.
#
def test_identity_flag(live_db, live_models, columns_of):
	columns = columns_of('note')
	assert columns['id'].identity is True
	assert columns['votes'].identity is False


##
# @brief The primary-key flag must reach the column metadata.
#
def test_primary_key_flag(live_db, live_models, columns_of):
	columns = columns_of('note')
	assert columns['id'].primary_key is True
	assert columns['title'].primary_key is False


##
# @brief Nullability must come from ADOX, not from ODBC.
#
# The driver reports title and votes as nullable even though Access
# enforces NOT NULL on both -- inserting a NULL is rejected.
#
def test_nullability_is_accurate(live_db, live_models, columns_of):
	columns = columns_of('note')
	assert columns['title'].null is False
	assert columns['votes'].null is False
	assert columns['body'].null is True
	assert columns['created'].null is True


##
# @brief Access must actually reject a NULL in a NOT NULL column.
#
# Proves the constraint is real, and therefore that the ODBC report is
# wrong rather than the DDL being ignored.
#
def test_not_null_is_enforced(live_db, live_models):
	Note, _ = live_models
	with pytest.raises(Exception):
		live_db.execute_sql(
			'INSERT INTO [note] ([title], [votes]) VALUES (NULL, 1)')


##
# @brief full_type must carry the length so reflection recovers it.
#
def test_full_type_carries_length(live_db, live_models, columns_of):
	columns = columns_of('note')
	assert '(' in columns['title'].full_type
	assert '255' in columns['title'].full_type


##
# @brief Indexes must be listed, with the unique flag set.
#
def test_get_indexes(live_db, live_models):
	indexes = live_db.get_indexes('note')
	assert indexes
	title_indexes = [i for i in indexes if 'title' in (i.columns or [])]
	assert title_indexes
	assert title_indexes[0].unique is True


##
# @brief The ADOX snapshot must be dropped when the connection closes.
#
# A schema change between connections would otherwise go unnoticed.
#
def test_adox_cache_cleared_on_close(accdb_path):
	import pwaccess

	database = pwaccess.AccessDatabase(accdb_path)
	database.connect()
	database.get_primary_keys('note')
	assert database._adox_cache
	database.close()
	assert database._adox_cache == {}
