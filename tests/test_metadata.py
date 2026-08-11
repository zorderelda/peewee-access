##
# @file test_metadata.py
# @brief AccessMetadata type mapping, exercised without a connection.
#

import pytest
from peewee import (
	AutoField,
	BlobField,
	BooleanField,
	CharField,
	DateTimeField,
	DecimalField,
	FloatField,
	IntegerField,
	TextField,
	UUIDField,
)

import pwaccess


##
# @brief The ODBC type names the Access driver actually reports.
#
# COUNTER/LONGCHAR/MEMO are Access's native names; INTEGER/VARCHAR are the
# ANSI spellings. Which set appears depends on driver version and on
# whether the table was created through DAO or ODBC, so both are mapped.
#
@pytest.mark.parametrize('type_name,expected', [
	('COUNTER', AutoField),
	('AUTOINCREMENT', AutoField),
	('INTEGER', IntegerField),
	('LONG', IntegerField),
	('VARCHAR', CharField),
	('TEXT', CharField),
	('VARCHAR(50)', CharField),
	('LONGCHAR', TextField),
	('MEMO', TextField),
	('BIT', BooleanField),
	('CURRENCY', DecimalField),
	('DATETIME', DateTimeField),
	('SINGLE', FloatField),
	('LONGBINARY', BlobField),
	('GUID', UUIDField),
])
def test_column_map(offline_db, type_name, expected):
	metadata = pwaccess.AccessMetadata(offline_db)
	assert metadata._map_col(type_name) is expected


##
# @brief An unrecognised type must fall back, not raise.
#
def test_unknown_type_falls_back(offline_db):
	metadata = pwaccess.AccessMetadata(offline_db)
	mapped = metadata._map_col('SOMETHING_INVENTED')
	assert mapped.__name__ in ('UnknownField', 'BareField')


##
# @brief Access TEXT is a short text column, not an unbounded one.
#
# This is the reverse of SQLite and PostgreSQL, where TEXT is unbounded.
# Mapping it to TextField would silently widen every short text column.
#
def test_access_text_is_char_not_text(offline_db):
	metadata = pwaccess.AccessMetadata(offline_db)
	assert metadata._map_col('TEXT') is CharField
	assert metadata._map_col('MEMO') is TextField


##
# @brief pwiz must emit the import the generated module needs.
#
def test_extension_import(offline_db):
	metadata = pwaccess.AccessMetadata(offline_db)
	assert metadata.requires_extension is True
	assert 'from pwaccess import AccessDatabase' in metadata.extension_import


##
# @brief The provider order must put ACE first for both extensions.
#
# Microsoft.Jet.OLEDB.4.0 has no 64-bit build, so preferring it for .mdb
# makes creation impossible on a 64-bit interpreter.
#
def test_provider_order():
	assert pwaccess.adox_providers('a.accdb') == \
	       ('Microsoft.ACE.OLEDB.12.0',)
	assert pwaccess.adox_providers('a.mdb')[0] == 'Microsoft.ACE.OLEDB.12.0'
	assert 'Microsoft.Jet.OLEDB.4.0' in pwaccess.adox_providers('a.mdb')
