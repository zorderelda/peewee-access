##
# @file test_dialect.py
# @brief Connection-string assembly, date helpers and path handling.
#
# Everything here is reachable without a driver: the connection string is
# built before pyodbc is called, and the date helpers return peewee
# expression trees rather than executing anything.
#

import pytest
from peewee import IntegerField, Model, TextField

import pwaccess
from pwaccess._drivers import normalize_path


@pytest.fixture
def Thing(offline_db):
	class Thing(Model):
		n = IntegerField()
		when = TextField(null=True)

		class Meta:
			database = offline_db
			table_name = 'thing'

	return Thing


# ---------------------------------------------------------------------------
# Connection string
# ---------------------------------------------------------------------------

##
# @brief The driver and file path must both reach the connection string.
#
def test_connection_string_basics():
	db = pwaccess.AccessDatabase(r'C:\data\app.accdb', driver='Fake Driver')
	built = db._build_connection_string(r'C:\data\app.accdb')
	assert built == ('Driver={Fake Driver};DBQ=C:\\data\\app.accdb;'
	                 'ExtendedAnsiSQL=1')


##
# @brief A password is sent as PWD.
#
def test_password_is_sent():
	db = pwaccess.AccessDatabase(r'C:\a.accdb', driver='D', password='s3cret')
	assert 'PWD=s3cret' in db._build_connection_string(r'C:\a.accdb')


##
# @brief Extra keyword arguments become extra KEY=VALUE pairs.
#
def test_connect_params_are_appended():
	db = pwaccess.AccessDatabase(r'C:\a.accdb', driver='D', Exclusive='Yes')
	assert 'Exclusive=Yes' in db._build_connection_string(r'C:\a.accdb')


# ---------------------------------------------------------------------------
# ANSI-92 query mode
# ---------------------------------------------------------------------------

##
# @brief ANSI-92 mode must be requested by default.
#
# The driver parses in ANSI-89 mode otherwise, which has no grammar for the
# ON DELETE actions peewee emits for ForeignKeyField(on_delete=...), so every
# such create_table() fails with "42000 Syntax error in CONSTRAINT clause".
#
def test_ansi_92_is_requested_by_default():
	db = pwaccess.AccessDatabase(r'C:\a.accdb', driver='D')
	assert 'ExtendedAnsiSQL=1' in db._build_connection_string(r'C:\a.accdb')


##
# @brief An explicit setting must replace the default, not join it.
#
# Naming the keyword twice would leave it to the driver which occurrence
# wins, so the caller's value has to be the only one present.
#
@pytest.mark.parametrize('keyword', ['ExtendedAnsiSQL', 'extendedansisql',
                                     'EXTENDEDANSISQL'])
def test_ansi_92_can_be_overridden(keyword):
	db = pwaccess.AccessDatabase(r'C:\a.accdb', driver='D', **{keyword: 0})
	built = db._build_connection_string(r'C:\a.accdb')
	assert '%s=0' % keyword in built
	assert built.lower().count('extendedansisql') == 1


##
# @brief The pooled subclass inherits the ANSI-92 default.
#
def test_pooled_database_requests_ansi_92():
	db = pwaccess.PooledAccessDatabase(r'C:\a.accdb', driver='D')
	assert 'ExtendedAnsiSQL=1' in db._build_connection_string(r'C:\a.accdb')


##
# @brief The redacted form must not contain the password.
#
# The unredacted string is embedded in the OperationalError raised when a
# connection fails. That message goes to stderr, into log aggregators and
# into bug reports, so the password has to be masked on the way.
#
def test_redacted_string_hides_the_password():
	db = pwaccess.AccessDatabase(r'C:\a.accdb', driver='D', password='s3cret')
	redacted = db._build_connection_string(r'C:\a.accdb', redact=True)
	assert 's3cret' not in redacted
	assert 'PWD=***' in redacted
	## Everything else must survive, or the message stops being useful.
	assert 'DBQ=C:\\a.accdb' in redacted


##
# @brief Redaction must not disturb a database that has no password.
#
def test_redaction_without_a_password_is_a_no_op():
	db = pwaccess.AccessDatabase(r'C:\a.accdb', driver='D')
	assert (db._build_connection_string(r'C:\a.accdb', redact=True) ==
	        db._build_connection_string(r'C:\a.accdb'))


##
# @brief A missing driver must name the redistributable, not just fail.
#
def test_missing_driver_message(monkeypatch):
	monkeypatch.setattr(pwaccess._drivers, 'detect_driver', lambda: None)
	with pytest.raises(pwaccess.DriverNotFoundError) as excinfo:
		pwaccess._drivers.require_driver()
	assert 'Database Engine' in str(excinfo.value)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

##
# @brief Forward slashes must be normalized to backslashes.
#
def test_normalize_path_uses_backslashes():
	assert '/' not in normalize_path('C:/data/app.accdb')


##
# @brief A Path object must be accepted, not only a string.
#
def test_normalize_path_accepts_path_objects(tmp_path):
	assert isinstance(normalize_path(tmp_path / 'x.accdb'), str)


# ---------------------------------------------------------------------------
# Date and time helpers
# ---------------------------------------------------------------------------

##
# @brief peewee date-part names map onto Access DatePart interval codes.
#
# Access spells these as one- or two-letter codes and has no EXTRACT at
# all, so passing peewee's name straight through produces a runtime error
# rather than a syntax error -- the worst kind to debug.
#
@pytest.mark.parametrize('part,code', [
	('year', 'yyyy'),
	('quarter', 'q'),
	('month', 'm'),
	('week', 'ww'),
	('day', 'd'),
	('weekday', 'w'),
	('hour', 'h'),
	('minute', 'n'),
	('second', 's'),
])
def test_extract_date_maps_interval_codes(offline_db, Thing, part, code):
	sql, params = Thing.select(offline_db.extract_date(part, Thing.n)).sql()
	assert 'DatePart' in sql
	## Written as a literal, not bound: Jet wants a string expression here
	## and ACE will not infer a parameter's type in this position.
	assert "DatePart('%s'," % code in sql
	assert code not in params


##
# @brief An unrecognised part must be bound, never interpolated.
#
# Inlining is only safe for the nine codes in _DATE_PART_MAP, which the
# backend controls. Anything else came from the caller and stays a
# parameter.
#
def test_extract_date_binds_unknown_parts(offline_db, Thing):
	sql, params = Thing.select(
		offline_db.extract_date('microsecond', Thing.n)).sql()
	assert 'microsecond' not in sql
	assert 'microsecond' in params


##
# @brief Access can truncate to year, month and day via DateSerial.
#
@pytest.mark.parametrize('part,expected', [
	('year', 'DateSerial'),
	('month', 'Month'),
	('day', 'Day'),
])
def test_truncate_date(offline_db, Thing, part, expected):
	sql = Thing.select(offline_db.truncate_date(part, Thing.n)).sql()[0]
	assert expected in sql


##
# @brief Any finer truncation must refuse; Access cannot express it.
#
@pytest.mark.parametrize('part', ['hour', 'minute', 'second', 'week'])
def test_truncate_date_refuses_finer_parts(offline_db, Thing, part):
	with pytest.raises(pwaccess.AccessNotSupportedError):
		offline_db.truncate_date(part, Thing.n)


##
# @brief The Access epoch offset must appear in timestamp conversion.
#
# Access counts days from 1899-12-30; Unix counts seconds from 1970-01-01.
# 25569 is the number of days between them, and 86400 the seconds in a day.
#
def test_to_timestamp_uses_the_access_epoch(offline_db, Thing):
	sql, params = Thing.select(offline_db.to_timestamp(Thing.n)).sql()
	assert 25569 in params
	assert 86400 in params


##
# @brief from_timestamp must invert to_timestamp through CDate.
#
def test_from_timestamp(offline_db, Thing):
	sql, params = Thing.select(offline_db.from_timestamp(Thing.n)).sql()
	assert 'CDate' in sql
	assert 25569 in params


##
# @brief Access spells random ordering Rnd(), not RANDOM().
#
def test_random_is_rnd(offline_db, Thing):
	sql = Thing.select().order_by(offline_db.random()).sql()[0]
	assert 'Rnd' in sql


# ---------------------------------------------------------------------------
# Miscellaneous dialect surface
# ---------------------------------------------------------------------------

##
# @brief Blobs come back as bytearray from the Access driver.
#
def test_binary_type(offline_db):
	assert offline_db.get_binary_type() is bytearray


##
# @brief repr must show the path and whether the connection is open.
#
def test_repr_reports_state(offline_db):
	assert 'offline.accdb' in repr(offline_db)
	assert '[closed]' in repr(offline_db)


##
# @brief The dialect flag must reach the SQL-generation context.
#
# Every patch is gated on this flag rather than on the database's type, so
# that a process talking to both Access and SQLite patches only the former.
#
def test_context_carries_the_dialect_flag(offline_db):
	assert offline_db.get_context_options()['access_dialect'] is True


##
# @brief Savepoints must refuse rather than emit SQL Jet cannot parse.
#
def test_savepoint_refuses(offline_db):
	with pytest.raises(pwaccess.AccessNotSupportedError):
		offline_db.savepoint()


##
# @brief Upserts must refuse with a pointer to get_or_create().
#
@pytest.mark.parametrize('method', ['conflict_statement', 'conflict_update'])
def test_conflict_methods_refuse(offline_db, method):
	with pytest.raises(pwaccess.AccessNotSupportedError) as excinfo:
		getattr(offline_db, method)(None, None)
	assert 'get_or_create' in str(excinfo.value)


##
# @brief ILIKE and the regex operators must collapse onto LIKE.
#
# Access LIKE is already case-insensitive and Access has no regex operator
# at all, so an unmapped ILIKE would be a syntax error.
#
@pytest.mark.parametrize('name', ['ILIKE', 'REGEXP', 'IREGEXP'])
def test_operator_remapping(name):
	assert pwaccess.OPERATIONS[name] == 'LIKE'


##
# @brief The dialect must advertise the features Access lacks.
#
@pytest.mark.parametrize('attribute', [
	'for_update', 'nulls_ordering', 'returning_clause', 'safe_create_index',
	'safe_drop_index', 'sequences', 'truncate_table',
])
def test_unsupported_features_are_disabled(offline_db, attribute):
	assert getattr(offline_db, attribute) is False


##
# @brief limit_max must stay None so peewee never invents a LIMIT.
#
def test_no_limit_max(offline_db):
	assert offline_db.limit_max is None
