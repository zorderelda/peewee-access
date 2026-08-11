##
# @file test_paginate.py
# @brief Argument handling and refusals in pwaccess.paginate().
#
# The row-slicing behaviour needs real rows and lives in
# test_live_orm_utils.py. What can be checked without a driver is the
# validation: paginate() must reject nonsense arguments and refuse to page
# an unordered query, rather than returning plausible-looking wrong pages.
#

import pytest
from peewee import IntegerField, Model

import pwaccess


@pytest.fixture
def Row(offline_db):
	class Row(Model):
		n = IntegerField()

		class Meta:
			database = offline_db
			table_name = 'row'

	return Row


##
# @brief Page numbers are 1-based; anything lower is a caller error.
#
@pytest.mark.parametrize('page', [0, -1])
def test_page_must_be_positive(Row, page):
	with pytest.raises(ValueError):
		pwaccess.paginate(Row.select().order_by(Row.n), page, 10)


##
# @brief A page size below one cannot describe a page.
#
@pytest.mark.parametrize('size', [0, -5])
def test_paginate_by_must_be_positive(Row, size):
	with pytest.raises(ValueError):
		pwaccess.paginate(Row.select().order_by(Row.n), 1, size)


##
# @brief Page one is returned as an unevaluated limited query.
#
# It needs no offset, so the ordinary TOP rewrite covers it and there is
# no reason to execute anything -- which is what lets this be tested
# without a driver at all.
#
def test_page_one_defers(Row):
	result = pwaccess.paginate(Row.select().order_by(Row.n), 1, 10)
	assert not isinstance(result, list)
	sql = result.sql()[0]
	assert 'LIMIT' in sql


##
# @brief Paging past page one without an ORDER BY must refuse.
#
# Jet leaves row order undefined without an ordering, so page boundaries
# move between requests and a record can appear on two pages or on none.
#
def test_unordered_paging_refuses(Row):
	with pytest.raises(pwaccess.AccessNotSupportedError) as excinfo:
		pwaccess.paginate(Row.select(), 2, 10)
	assert 'ORDER BY' in str(excinfo.value)


##
# @brief Page one of an unordered query is still fine.
#
# There is no boundary to be unstable about, so the ordering requirement
# does not apply.
#
def test_unordered_page_one_allowed(Row):
	assert pwaccess.paginate(Row.select(), 1, 10) is not None


##
# @brief The page-one limit must be the page size, not the offset window.
#
def test_page_one_limit_is_the_page_size(Row):
	result = pwaccess.paginate(Row.select().order_by(Row.n), 1, 7)
	assert result._limit == 7
