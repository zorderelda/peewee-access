##
# @file test_live_mdb.py
# @brief The legacy .mdb format, which uses a different provider path.
#
# Microsoft.Jet.OLEDB.4.0 has no 64-bit build, so .mdb creation must go
# through ACE on a 64-bit interpreter. An implementation that picks the
# provider by extension alone cannot create these files at all.
#

import pytest
from peewee import IntegerField, Model, TextField
from playhouse.reflection import generate_models

import pwaccess

pytestmark = [pytest.mark.driver, pytest.mark.adox]


##
# @brief A freshly created .mdb with one populated table.
#
@pytest.fixture(scope='module')
def mdb(tmp_path_factory):
	path = str(tmp_path_factory.mktemp('pwaccess_mdb') / 'legacy.mdb')
	database = pwaccess.AccessDatabase(path)
    
    ## @brief Alias so the Meta class body can see it; a class body cannot
	#  read an enclosing function local of the same name it assigns.
	_db = database

	class Legacy(Model):
		name = TextField(unique=True)
		count = IntegerField(default=0)

		class Meta:
			database = _db
			table_name = 'legacy'

	database.connect()
	database.create_tables([Legacy])
	Legacy.create(name='first', count=1)
	Legacy.create(name='second', count=2)

	yield database, Legacy, path

	if not database.is_closed():
		database.close()


##
# @brief The file must be created despite Jet being unavailable.
#
def test_mdb_created(mdb):
	import os
	_, _, path = mdb
	assert os.path.isfile(path)


##
# @brief Rows must round-trip.
#
def test_mdb_insert_and_select(mdb):
	_, Legacy, _ = mdb
	assert Legacy.select().count() == 2
	assert Legacy.get(Legacy.name == 'second').count == 2


##
# @brief ADOX must read a Jet-format file through the ACE provider.
#
def test_mdb_primary_key(mdb):
	database, _, _ = mdb
	assert database.get_primary_keys('legacy') == ['id']


##
# @brief Column metadata must be as accurate as it is for .accdb.
#
def test_mdb_columns(mdb):
	database, _, _ = mdb
	columns = {c.name: c for c in database.get_columns('legacy')}
	assert columns['id'].identity is True
	assert columns['id'].primary_key is True
	assert columns['name'].null is False
	assert columns['count'].null is False


##
# @brief Reflection must work identically on the legacy format.
#
def test_mdb_reflection(mdb):
	database, _, _ = mdb
	model = generate_models(database)['legacy']
	fields = {f.name: type(f).__name__ for f in model._meta.sorted_fields}
	assert fields['id'] == 'AutoField'
	assert fields['name'] == 'CharField'
	assert fields['count'] == 'IntegerField'
