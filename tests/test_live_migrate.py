##
# @file test_live_migrate.py
# @brief Migrations executed against a real Access database.
#
# The offline tests assert the SQL is correct; these assert Access
# accepts it and that the schema really changed.
#

import pytest
from peewee import DoubleField, IntegerField
from playhouse.migrate import SchemaMigrator, migrate

pytestmark = [pytest.mark.driver, pytest.mark.adox]


##
# @brief A migrator bound to the live database.
#
@pytest.fixture
def live_migrator(live_db, live_models):
	return SchemaMigrator.from_database(live_db)


##
# @brief Column names currently on a table, straight from the catalog.
#
def _column_names(database, table):
	database._adox_cache.clear()
	return [c.name for c in database.get_columns(table)]


##
# @brief ADD COLUMN then DROP COLUMN must round-trip.
#
def test_add_and_drop_column(live_db, live_migrator):
	migrate(live_migrator.add_column('note', 'flags',
	                                 IntegerField(null=True)))
	assert 'flags' in _column_names(live_db, 'note')

	migrate(live_migrator.drop_column('note', 'flags'))
	assert 'flags' not in _column_names(live_db, 'note')


##
# @brief ALTER COLUMN must change the type, both directions.
#
def test_alter_column_type(live_db, live_migrator):
	def votes_type():
		live_db._adox_cache.clear()
		for column in live_db.get_columns('note'):
			if column.name == 'votes':
				return column.data_type.upper()
		return None

	original = votes_type()

	migrate(live_migrator.alter_column_type('note', 'votes',
	                                        DoubleField(null=False)))
	assert votes_type() == 'DOUBLE'

	migrate(live_migrator.alter_column_type('note', 'votes',
	                                        IntegerField(null=False)))
	assert votes_type() == original


##
# @brief NOT NULL restated inline must survive the type change.
#
# Access has no SET NOT NULL, so the constraint has to be repeated in the
# ALTER COLUMN statement or it is silently dropped.
#
def test_alter_column_preserves_not_null(live_db, live_migrator):
	migrate(live_migrator.alter_column_type('note', 'votes',
	                                        IntegerField(null=False)))
	live_db._adox_cache.clear()
	columns = {c.name: c for c in live_db.get_columns('note')}
	assert columns['votes'].null is False


##
# @brief DROP INDEX must accept Jet's "ON table" syntax.
#
def test_drop_index(live_db, live_migrator):
	before = live_db.get_indexes('note')
	targets = [i.name for i in before if 'title' in (i.columns or [])]
	if not targets:
		pytest.skip('no index on title to drop')

	migrate(live_migrator.drop_index('note', targets[0]))
	after = [i.name for i in live_db.get_indexes('note')]
	assert targets[0] not in after

	## Restore it so later tests see the original schema.
	migrate(live_migrator.add_index('note', ('title',), unique=True))
