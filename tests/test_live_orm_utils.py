##
# @file test_live_orm_utils.py
# @brief The playhouse ORM-utility surface, against a real Access database.
#
# Peewee's ORM Utilities page says these modules work with any backend.
# For most of them that is true and these tests only pin it down. Two
# needed adapting -- the key/value store and pagination -- and those are
# tested here in more depth.
#
# Flask and pydantic are optional; the tests that need them skip cleanly
# when they are absent, because neither is a dependency of pwaccess.
#

import pytest

import pwaccess

pytestmark = pytest.mark.driver


##
# @brief A small model with rows numbered 0..24, for pagination.
#
# Rows are inserted one at a time on purpose: Jet rejects the multi-row
# VALUES clause that insert_many() generates.
#
@pytest.fixture(scope='module')
def paged(live_db):
	from peewee import IntegerField, Model

	_db = live_db

	class Row(Model):
		n = IntegerField()

		class Meta:
			database = _db
			table_name = 'ou_row'

	live_db.drop_tables([Row], safe=True)
	live_db.create_tables([Row])
	for i in range(25):
		Row.create(n=i)
	yield Row
	live_db.drop_tables([Row], safe=True)


##
# @brief A key/value store on a scratch table.
#
@pytest.fixture
def kv(live_db):
	store = pwaccess.AccessKeyValue(database=live_db,
	                                table_name='ou_keyvalue')
	store.clear()
	yield store
	store.clear()


# ---------------------------------------------------------------------------
# Key/value store
# ---------------------------------------------------------------------------

##
# @brief A database is mandatory; the SQLite default is refused.
#
def test_keyvalue_requires_database():
	with pytest.raises(pwaccess.AccessConfigurationError):
		pwaccess.AccessKeyValue()


##
# @brief Setting one key then reading it back.
#
def test_keyvalue_set_and_get(kv):
	kv['theme'] = 'dark'
	assert kv['theme'] == 'dark'


##
# @brief Re-setting a key updates rather than inserting a duplicate.
#
# This is the path that raised before the upsert override: the base class
# reaches for ON CONFLICT, which Jet has not got.
#
def test_keyvalue_overwrite_does_not_duplicate(kv):
	kv['theme'] = 'dark'
	kv['theme'] = 'light'
	assert kv['theme'] == 'light'
	assert len(kv) == 1


##
# @brief Bulk update writes every pair.
#
def test_keyvalue_bulk_update(kv):
	kv.update(retries=3, timeout=30)
	assert kv['retries'] == 3
	assert kv['timeout'] == 30
	assert len(kv) == 2


##
# @brief Bulk update over existing keys replaces their values.
#
def test_keyvalue_bulk_update_overwrites(kv):
	kv.update(a=1, b=2)
	kv.update({'b': 22, 'c': 3})
	assert dict(kv) == {'a': 1, 'b': 22, 'c': 3}


##
# @brief A missing key raises KeyError, not a driver error.
#
def test_keyvalue_missing_key(kv):
	with pytest.raises(KeyError):
		kv['nope']


##
# @brief Values round-trip through PickleField, so any object survives.
#
def test_keyvalue_pickles_arbitrary_objects(kv):
	kv['payload'] = {'nested': [1, 2, 3]}
	assert kv['payload'] == {'nested': [1, 2, 3]}


##
# @brief Expression-based read, bulk write and delete.
#
def test_keyvalue_expressions(kv):
	kv.update(k1='v1', k2='v2', k3='v3')

	assert sorted(kv[kv.key > 'k1']) == ['v2', 'v3']

	kv[kv.key > 'k1'] = 'replaced'
	assert kv['k2'] == 'replaced'
	assert kv['k1'] == 'v1'

	del kv[kv.key > 'k1']
	assert dict(kv) == {'k1': 'v1'}


##
# @brief An empty update is a no-op rather than an empty INSERT.
#
def test_keyvalue_empty_update(kv):
	assert kv.update() == 0
	assert len(kv) == 0


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

##
# @brief Pages must be contiguous, non-overlapping and correctly ordered.
#
def test_paginate_pages_are_contiguous(paged):
	query = paged.select().order_by(paged.n)
	p1 = [r.n for r in pwaccess.paginate(query, 1, 10)]
	p2 = [r.n for r in pwaccess.paginate(query, 2, 10)]
	assert p1 == list(range(0, 10))
	assert p2 == list(range(10, 20))


##
# @brief The final page is short rather than padded or refused.
#
def test_paginate_final_page_is_short(paged):
	query = paged.select().order_by(paged.n)
	assert [r.n for r in pwaccess.paginate(query, 3, 10)] == \
	       list(range(20, 25))


##
# @brief A page past the end is empty, not an error.
#
def test_paginate_past_end_is_empty(paged):
	query = paged.select().order_by(paged.n)
	assert list(pwaccess.paginate(query, 99, 10)) == []


##
# @brief Every row appears exactly once across all pages.
#
# Guards the failure mode that ruled out the nested-TOP approach: pages
# that silently duplicate or drop records.
#
def test_paginate_covers_every_row_once(paged):
	query = paged.select().order_by(paged.n)
	seen = []
	for page in range(1, 4):
		seen.extend(r.n for r in pwaccess.paginate(query, page, 10))
	assert sorted(seen) == list(range(25))
	assert len(seen) == len(set(seen))


##
# @brief Page one is returned unevaluated, so it can be refined further.
#
def test_paginate_page_one_defers(paged):
	query = paged.select().order_by(paged.n)
	assert not isinstance(pwaccess.paginate(query, 1, 10), list)


##
# @brief Paging an unordered query refuses rather than guessing.
#
def test_paginate_unordered_refuses(paged):
	with pytest.raises(pwaccess.AccessNotSupportedError):
		pwaccess.paginate(paged.select(), 2, 10)


##
# @brief Page one of an unordered query is allowed: no offset is involved.
#
def test_paginate_unordered_page_one_allowed(paged):
	assert len(list(pwaccess.paginate(paged.select(), 1, 10))) == 10


##
# @brief Nonsensical page or page-size arguments are rejected eagerly.
#
@pytest.mark.parametrize('page,size', [(0, 10), (-1, 10), (1, 0)])
def test_paginate_rejects_bad_arguments(paged, page, size):
	with pytest.raises(ValueError):
		pwaccess.paginate(paged.select().order_by(paged.n), page, size)


##
# @brief The Flask adapter reads the page number from the request.
#
def test_flask_paginated_query(paged):
	flask = pytest.importorskip('flask')

	app = flask.Flask(__name__)
	query = paged.select().order_by(paged.n)

	with app.test_request_context('/?page=2'):
		pq = pwaccess.AccessPaginatedQuery(query, paginate_by=10)
		assert [r.n for r in pq.get_object_list()] == list(range(10, 20))
		assert pq.get_page() == 2
		assert pq.get_page_count() == 3


# ---------------------------------------------------------------------------
# Utilities expected to work unchanged
# ---------------------------------------------------------------------------

##
# @brief model_to_dict and dict_to_model are pure Python over instances.
#
def test_shortcuts_round_trip(live_models):
	from playhouse.shortcuts import dict_to_model, model_to_dict

	Note, Comment = live_models
	note = Note.create(title='shortcuts', body='b', votes=1)

	data = model_to_dict(note)
	assert data['title'] == 'shortcuts'

	rebuilt = dict_to_model(Note, data)
	assert rebuilt.title == 'shortcuts'

	note.delete_instance()


##
# @brief A foreign key serializes as a nested dict, or flat with recurse off.
#
def test_shortcuts_recurse(live_models):
	from playhouse.shortcuts import model_to_dict

	Note, Comment = live_models
	note = Note.create(title='parent', votes=0)
	comment = Comment.create(note=note, body='child')

	assert model_to_dict(comment)['note']['title'] == 'parent'
	assert model_to_dict(comment, recurse=False)['note'] == note.id

	comment.delete_instance()
	note.delete_instance()


##
# @brief A hybrid property must evaluate in Python and compile to SQL.
#
def test_hybrid_property(live_db):
	from peewee import IntegerField, Model
	from playhouse.hybrid import hybrid_property

	_db = live_db

	class Span(Model):
		start = IntegerField()
		finish = IntegerField()

		class Meta:
			database = _db
			table_name = 'ou_span'

		@hybrid_property
		def length(self):
			return self.finish - self.start

	live_db.drop_tables([Span], safe=True)
	live_db.create_tables([Span])
	try:
		Span.create(start=1, finish=5)
		Span.create(start=1, finish=100)

		assert Span(start=1, finish=5).length == 4

		rows = list(Span.select().where(Span.length > 50))
		assert len(rows) == 1
	finally:
		live_db.drop_tables([Span], safe=True)


##
# @brief A hybrid expression must survive the LIMIT-to-TOP rewrite.
#
def test_hybrid_with_top(live_db):
	from peewee import IntegerField, Model
	from playhouse.hybrid import hybrid_property

	_db = live_db

	class Span2(Model):
		start = IntegerField()
		finish = IntegerField()

		class Meta:
			database = _db
			table_name = 'ou_span2'

		@hybrid_property
		def length(self):
			return self.finish - self.start

	live_db.drop_tables([Span2], safe=True)
	live_db.create_tables([Span2])
	try:
		for i in range(5):
			Span2.create(start=0, finish=i * 10)
		rows = list(Span2.select().where(Span2.length > 5).limit(2))
		assert len(rows) == 2
	finally:
		live_db.drop_tables([Span2], safe=True)


##
# @brief Signals must fire on save and delete.
#
def test_signals(live_db):
	from peewee import CharField
	from playhouse.signals import Model as SignalModel
	from playhouse.signals import post_delete, post_save

	_db = live_db
	fired = []

	class Watched(SignalModel):
		name = CharField()

		class Meta:
			database = _db
			table_name = 'ou_watched'

	@post_save(sender=Watched)
	def _on_save(sender, instance, created):
		fired.append(('save', created))

	@post_delete(sender=Watched)
	def _on_delete(sender, instance):
		fired.append(('delete', None))

	live_db.drop_tables([Watched], safe=True)
	live_db.create_tables([Watched])
	try:
		row = Watched.create(name='x')
		row.name = 'y'
		row.save()
		row.delete_instance()
		assert fired == [('save', True), ('save', False), ('delete', None)]
	finally:
		post_save.disconnect(_on_save, sender=Watched)
		post_delete.disconnect(_on_delete, sender=Watched)
		live_db.drop_tables([Watched], safe=True)


##
# @brief PickleField and CompressedField store through LONGBINARY.
#
def test_extra_field_types(live_db):
	from peewee import Model
	from playhouse.fields import CompressedField, PickleField

	_db = live_db

	class Payload(Model):
		blob = PickleField(null=True)
		packed = CompressedField(null=True)

		class Meta:
			database = _db
			table_name = 'ou_payload'

	live_db.drop_tables([Payload], safe=True)
	live_db.create_tables([Payload])
	try:
		Payload.create(blob={'a': [1, 2]}, packed=b'x' * 1000)
		row = Payload.select().get()
		assert row.blob == {'a': [1, 2]}
		assert row.packed == b'x' * 1000
	finally:
		live_db.drop_tables([Payload], safe=True)


##
# @brief A reflected Access model must generate a usable pydantic schema.
#
def test_to_pydantic(live_models):
	pytest.importorskip('pydantic')
	from playhouse.pydantic_utils import to_pydantic

	Note, Comment = live_models
	schema = to_pydantic(Note)
	data = schema.model_validate({'title': 't', 'body': 'b', 'votes': 1})
	assert data.model_dump()['title'] == 't'


##
# @brief A compound UNION must resolve rows back to the right model class.
#
# Jet supports UNION, but peewee wraps compound selects differently per
# dialect and the Access dialect sets CSQ_PARENTHESES_NEVER, so this is
# the least certain test in the file.
#
def test_resolve_multimodel_query(live_db):
	from peewee import CharField, Model
	from playhouse.shortcuts import resolve_multimodel_query

	_db = live_db

	class Cat(Model):
		name = CharField()

		class Meta:
			database = _db
			table_name = 'ou_cat'

	class Dog(Model):
		name = CharField()

		class Meta:
			database = _db
			table_name = 'ou_dog'

	live_db.drop_tables([Cat, Dog], safe=True)
	live_db.create_tables([Cat, Dog])
	try:
		Cat.create(name='whiskers')
		Dog.create(name='rex')

		# resolve_multimodel_query adds its own _model_identifier column,
		# so supplying one here produces a duplicate output alias.
		cats = Cat.select()
		dogs = Dog.select()

		found = sorted(type(row).__name__
		               for row in resolve_multimodel_query(cats | dogs))
		assert found == ['Cat', 'Dog']
	finally:
		live_db.drop_tables([Cat, Dog], safe=True)
