##
# @file test_live_reflection.py
# @brief generate_models() against a real Access database.
#

import pytest
from peewee import (
	AutoField,
	CharField,
	DateTimeField,
	ForeignKeyField,
	IntegerField,
	TextField,
)
from playhouse.reflection import Introspector, generate_models

pytestmark = [pytest.mark.driver, pytest.mark.adox]


##
# @brief The introspector must be Access-aware.
#
def test_introspector_dispatch(live_db, live_models):
	introspector = Introspector.from_database(live_db)
	assert type(introspector.metadata).__name__ == 'AccessMetadata'


##
# @brief Every column must map to the right field class.
#
def test_field_classes(live_db, live_models):
	model = generate_models(live_db)['note']
	fields = {f.name: type(f) for f in model._meta.sorted_fields}
	assert fields['id'] is AutoField
	assert fields['title'] is CharField
	assert fields['body'] is TextField
	assert fields['votes'] is IntegerField
	assert fields['created'] is DateTimeField


##
# @brief max_length must be recovered from the parameterized type.
#
def test_max_length_recovered(live_db, live_models):
	model = generate_models(live_db)['note']
	title = model._meta.fields['title']
	assert title.max_length == 255


##
# @brief Reflected nullability must match the real constraints.
#
def test_reflected_nullability(live_db, live_models):
	model = generate_models(live_db)['note']
	fields = model._meta.fields
	assert fields['title'].null is False
	assert fields['votes'].null is False
	assert fields['body'].null is True


##
# @brief The primary key must be an AutoField, not a composite key.
#
def test_primary_key_is_autofield(live_db, live_models):
	model = generate_models(live_db)['note']
	assert isinstance(model._meta.primary_key, AutoField)


##
# @brief A relationship must reflect as a ForeignKeyField.
#
def test_foreign_key_reflected(live_db, live_models):
	models = generate_models(live_db)
	comment = models['comment']
	fields = {f.name: type(f) for f in comment._meta.sorted_fields}
	assert fields['note'] is ForeignKeyField


##
# @brief The generated model must be usable, not merely constructible.
#
def test_generated_model_queries(live_db, live_models):
	model = generate_models(live_db)['note']
	assert model.select().count() >= 0
