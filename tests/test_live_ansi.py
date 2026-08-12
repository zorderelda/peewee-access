##
# @file test_live_ansi.py
# @brief ANSI-92 query mode against a real Access database.
#
# The Access ODBC driver parses in ANSI-89 query mode unless the connection
# string asks for ANSI-92 with ExtendedAnsiSQL=1. One thing peewee emits
# depends on the difference: the ON DELETE CASCADE / SET NULL that
# ForeignKeyField(on_delete=...) produces. ANSI-89 has no grammar for the
# action, so create_table() fails with "42000 Syntax error in CONSTRAINT
# clause". The constraint name is not involved -- a FOREIGN KEY carrying no
# action is accepted in either mode.
#
# LIKE looks like it should be a second casualty and is not, so it is
# pinned down here too. The documented ANSI-89/92 wildcard split -- */?
# against %/_ -- belongs to the Access UI and DAO, not to the ODBC driver,
# which takes %/_ in both modes. Both halves are asserted below, because
# the plausible-but-wrong version of this story is that .contains() returns
# silently empty results in ANSI-89 mode, and that deserves a test standing
# against it rather than a comment.
#
# Every test opens its own database so the connection string, and therefore
# the query mode, is under the test's control.
#

import pytest
from peewee import ForeignKeyField, Model, TextField

import pwaccess

pytestmark = pytest.mark.driver


##
# @brief A parent/child model pair bound to *database*.
# @param on_delete Referential action for the child's foreign key, or None
#        for a bare FOREIGN KEY.
# @param suffix Appended to the table names so each test owns its tables.
# @return An (Owner, Item) tuple.
#
def _models(database, on_delete, suffix):
	## Bound under a second name: a class body that assigns `database`
	## cannot also read the enclosing function's `database`.
	bound = database

	class Owner(Model):
		name = TextField()

		class Meta:
			database = bound
			table_name = 'ansi_owner_%s' % suffix

	class Item(Model):
		## Nullable so SET NULL has somewhere to write.
		owner = ForeignKeyField(Owner, backref='items', null=True,
		                        on_delete=on_delete)
		label = TextField(null=True)

		class Meta:
			database = bound
			table_name = 'ansi_item_%s' % suffix

	return Owner, Item


##
# @brief Create the tables, yield the models, drop them again.
#
def _tables(database, on_delete, suffix):
	Owner, Item = _models(database, on_delete, suffix)
	database.drop_tables([Item, Owner], safe=True)
	database.create_tables([Owner, Item])
	return Owner, Item


# ---------------------------------------------------------------------------
# ON DELETE -- tested, and the reason ANSI-92 is the default
# ---------------------------------------------------------------------------

##
# @brief A referential action must survive create_table().
#
# Without ExtendedAnsiSQL=1 both of these fail with "42000 Syntax error in
# CONSTRAINT clause", which is to say that every peewee model using
# ForeignKeyField(on_delete=...) is unusable.
#
@pytest.mark.parametrize('action, suffix', [('CASCADE', 'cascade'),
                                            ('SET NULL', 'setnull')])
def test_on_delete_accepted(accdb_path, action, suffix):
	database = pwaccess.AccessDatabase(accdb_path)
	database.connect()
	try:
		Owner, Item = _tables(database, action, suffix)
		database.drop_tables([Item, Owner], safe=True)
	finally:
		database.close()


##
# @brief ON DELETE CASCADE must actually cascade.
#
# Parsing the clause and honouring it are separate things: a driver that
# accepted the DDL and then ignored the action would leave orphaned rows
# behind, which no amount of DDL-level testing would catch.
#
def test_on_delete_cascade_is_enforced(accdb_path):
	database = pwaccess.AccessDatabase(accdb_path)
	database.connect()
	try:
		Owner, Item = _tables(database, 'CASCADE', 'enforced')
		owner = Owner.create(name='keep')
		doomed = Owner.create(name='doomed')
		Item.create(owner=owner, label='survivor')
		Item.create(owner=doomed, label='casualty')

		doomed.delete_instance()

		labels = sorted(i.label for i in Item.select())
		assert labels == ['survivor']
		database.drop_tables([Item, Owner], safe=True)
	finally:
		database.close()


##
# @brief ANSI-89 mode must still reject ON DELETE.
#
# This is the failure the default exists to prevent. If it ever stops
# failing -- a driver update, say -- the default has become optional rather
# than load-bearing, and this test is where that shows up.
#
def test_on_delete_rejected_without_ansi_92(accdb_path):
	database = pwaccess.AccessDatabase(accdb_path, ExtendedAnsiSQL=0)
	database.connect()
	try:
		Owner, Item = _models(database, 'CASCADE', 'ansi89')
		database.drop_tables([Item, Owner], safe=True)
		database.create_tables([Owner])
		with pytest.raises(Exception) as excinfo:
			database.create_tables([Item])
		assert '42000' in str(excinfo.value) or \
			'CONSTRAINT' in str(excinfo.value).upper()
		database.drop_tables([Item, Owner], safe=True)
	finally:
		database.close()


# ---------------------------------------------------------------------------
# LIKE wildcards
# ---------------------------------------------------------------------------

##
# @brief Populate a table with labels chosen to expose wildcard handling.
# @return An (Owner, Item, found) triple; found(pattern) -> sorted labels.
#
def _like_fixture(database, suffix):
	Owner, Item = _tables(database, None, suffix)
	for label in ('alpha', 'beta', 'gamma', 'alp'):
		Item.create(label=label)

	def found(pattern):
		return sorted(i.label for i in
		              Item.select().where(Item.label ** pattern))

	return Owner, Item, found


##
# @brief The ODBC driver's LIKE wildcards must be %/_ in both query modes.
#
# Parametrized over the query mode because the point is that the mode makes
# no difference. peewee binds patterns spelled with % and _ for
# .contains(), .startswith() and .endswith(); if ANSI-89 mode interpreted
# them literally, those three would return empty result sets rather than
# raising, and the wrong answers would look like missing data.
#
@pytest.mark.parametrize('connect_params, suffix',
                         [({}, 'like92'), ({'ExtendedAnsiSQL': 0}, 'like89')])
def test_like_takes_ansi_92_wildcards_in_both_modes(accdb_path,
                                                    connect_params, suffix):
	database = pwaccess.AccessDatabase(accdb_path, **connect_params)
	database.connect()
	try:
		Owner, Item, found = _like_fixture(database, suffix)

		assert found('%lph%') == ['alpha']
		assert found('al%') == ['alp', 'alpha']
		assert found('%ma') == ['gamma']
		## The single-character wildcard.
		assert found('al_') == ['alp']
		database.drop_tables([Item, Owner], safe=True)
	finally:
		database.close()


##
# @brief The Access UI wildcards */? must be literals in both query modes.
#
# The other half of the same finding. ANSI-89 query mode does not resurrect
# the DAO spelling, so a pattern written '*lph*' matches nothing through
# ODBC no matter how the connection was opened.
#
@pytest.mark.parametrize('connect_params, suffix',
                         [({}, 'star92'), ({'ExtendedAnsiSQL': 0}, 'star89')])
def test_dao_wildcards_are_literal_in_both_modes(accdb_path,
                                                 connect_params, suffix):
	database = pwaccess.AccessDatabase(accdb_path, **connect_params)
	database.connect()
	try:
		Owner, Item, found = _like_fixture(database, suffix)

		assert found('*lph*') == []
		assert found('al*') == []
		assert found('al?') == []
		## A pattern with no wildcard at all still matches exactly, which
		## rules out the empty results above being a broken fixture.
		assert found('alpha') == ['alpha']
		database.drop_tables([Item, Owner], safe=True)
	finally:
		database.close()
