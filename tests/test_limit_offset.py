##
# @file test_limit_offset.py
# @brief The LIMIT-to-TOP rewrite, including the paths that must refuse.
#
# Access has no LIMIT and no OFFSET. peewee binds both as parameters, but
# Jet will not accept a parameter marker in a TOP clause, so the values are
# popped off the parameter list and inlined at execution time.
#
# Getting this wrong is quiet rather than loud: a rewrite that strips the
# clause without replacing it turns a limited query into a full-table scan
# that returns the right-looking rows on a small table and the wrong ones
# on a large one. Most of these tests exist to pin down the failure paths
# rather than the happy one.
#

import pytest
from peewee import IntegerField, Model, TextField

import pwaccess
from pwaccess._sql import rewrite_limit_to_top


@pytest.fixture
def Thing(offline_db):
	class Thing(Model):
		n = IntegerField()
		label = TextField(null=True)

		class Meta:
			database = offline_db
			table_name = 'thing'

	return Thing


# ---------------------------------------------------------------------------
# The rewrite itself
# ---------------------------------------------------------------------------

##
# @brief LIMIT becomes TOP, and the bound parameter is consumed.
#
def test_limit_becomes_top(Thing):
	sql, params = rewrite_limit_to_top(*Thing.select().limit(5).sql())
	assert 'TOP 5' in sql
	assert 'LIMIT' not in sql
	## The 5 was inlined, so it must no longer be bound.
	assert params == []


##
# @brief TOP must follow DISTINCT, not precede it.
#
def test_distinct_survives_the_rewrite(Thing):
	sql, _ = rewrite_limit_to_top(
		*Thing.select(Thing.n).distinct().limit(3).sql())
	assert 'SELECT DISTINCT TOP 3' in sql


##
# @brief Other bound parameters must be left in place and in order.
#
def test_where_parameters_are_preserved(Thing):
	sql, params = rewrite_limit_to_top(
		*Thing.select().where(Thing.n > 10).limit(5).sql())
	assert 'TOP 5' in sql
	assert params == [10]


##
# @brief A statement with no LIMIT is returned untouched.
#
def test_statement_without_limit_untouched(Thing):
	original = Thing.select().where(Thing.n > 1).sql()
	assert rewrite_limit_to_top(*original) == original


##
# @brief None parameters must not become a list.
#
def test_none_params_pass_through():
	assert rewrite_limit_to_top('SELECT 1', None) == ('SELECT 1', None)


# ---------------------------------------------------------------------------
# OFFSET
# ---------------------------------------------------------------------------

##
# @brief A non-zero OFFSET must refuse, with keyset guidance.
#
def test_offset_refuses(Thing):
	with pytest.raises(pwaccess.AccessNotSupportedError) as excinfo:
		rewrite_limit_to_top(*Thing.select().limit(5).offset(10).sql())
	assert 'keyset' in str(excinfo.value)


##
# @brief OFFSET 0 is a no-op and must not refuse.
#
def test_zero_offset_is_allowed(Thing):
	sql, params = rewrite_limit_to_top(
		*Thing.select().limit(5).offset(0).sql())
	assert 'TOP 5' in sql
	assert 'OFFSET' not in sql
	assert params == []


##
# @brief .offset() with no .limit() must refuse, not reach the driver.
#
# peewee only pairs an offset with a LIMIT when the dialect declares a
# limit_max, and Access declares none because it has no LIMIT clause at
# all. So this arrives as a bare "OFFSET ?" that the main LIMIT pattern
# cannot see. Left alone it reaches Jet intact and fails with the generic
# "Missing semicolon (;) at end of SQL statement", which names no cause.
#
def test_bare_offset_refuses(Thing):
	sql, params = Thing.select().offset(10).sql()
	assert 'OFFSET' in sql and 'LIMIT' not in sql, sql
	with pytest.raises(pwaccess.AccessNotSupportedError):
		rewrite_limit_to_top(sql, params)


##
# @brief A bare OFFSET 0 is dropped rather than refused.
#
def test_bare_zero_offset_is_dropped(Thing):
	sql, params = rewrite_limit_to_top(*Thing.select().offset(0).sql())
	assert 'OFFSET' not in sql
	assert params == []


# ---------------------------------------------------------------------------
# Paths that must not silently drop the clause
# ---------------------------------------------------------------------------

##
# @brief An unparseable limit must leave the statement alone.
#
# Stripping "LIMIT ?" and failing to add a TOP would hand Jet a query that
# runs perfectly well and returns every row in the table.
#
def test_unparseable_limit_is_left_intact():
	sql, params = rewrite_limit_to_top('SELECT [a] FROM [t] LIMIT ?', ['abc'])
	assert sql == 'SELECT [a] FROM [t] LIMIT ?'
	assert params == ['abc']


##
# @brief A statement that does not start with SELECT is left alone.
#
def test_non_select_is_left_intact():
	original = ('(SELECT [a] FROM [t]) LIMIT ?', [5])
	assert rewrite_limit_to_top(*original) == original


##
# @brief A LIMIT with no matching parameter is left alone.
#
def test_missing_parameter_is_left_intact():
	original = ('SELECT [a] FROM [t] LIMIT ?', [])
	assert rewrite_limit_to_top(*original) == original


##
# @brief An OFFSET with only one parameter is left alone.
#
def test_offset_with_short_params_is_left_intact():
	original = ('SELECT [a] FROM [t] LIMIT ? OFFSET ?', [5])
	assert rewrite_limit_to_top(*original) == original


# ---------------------------------------------------------------------------
# Compound selects
# ---------------------------------------------------------------------------

##
# @brief A limited UNION must refuse rather than mislead.
#
# Jet binds TOP to the individual SELECT it is written on, not to the
# combined result. Rewriting "a UNION b LIMIT 5" to "SELECT TOP 5 a UNION
# b" therefore returns five rows from the first branch plus every row of
# the second -- a wrong answer that looks like a right one.
#
@pytest.mark.parametrize('operator', ['|', '&', '-'])
def test_limited_compound_refuses(Thing, operator):
	left = Thing.select(Thing.n)
	right = Thing.select(Thing.n).where(Thing.n > 5)
	compound = {'|': left | right,
	            '&': left & right,
	            '-': left - right}[operator].limit(5)

	with pytest.raises(pwaccess.AccessNotSupportedError) as excinfo:
		rewrite_limit_to_top(*compound.sql())
	assert 'TOP' in str(excinfo.value)


##
# @brief An unlimited compound select is fine and must not refuse.
#
def test_unlimited_compound_is_allowed(Thing):
	compound = Thing.select(Thing.n) | Thing.select(Thing.n)
	sql, params = rewrite_limit_to_top(*compound.sql())
	assert 'UNION' in sql


##
# @brief A bracketed identifier named "union" must not trip the check.
#
# The compound pattern is deliberately case-sensitive and requires
# surrounding whitespace, because peewee upper-cases keywords, brackets
# every identifier and binds every value.
#
def test_bracketed_union_column_is_not_a_compound():
	sql, params = rewrite_limit_to_top(
		'SELECT [union] FROM [t] LIMIT ?', [3])
	assert sql == 'SELECT TOP 3 [union] FROM [t]'
