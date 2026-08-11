##
# @file test_url.py
# @brief Database-URL scheme registration and Windows path recovery.
#
# Windows paths do not survive urlparse() intact: the canonical spelling
# puts the whole path in the URL's path component (three slashes), and the
# two-slash form leaves the drive letter in the authority, lower-cased.
#

import playhouse.db_url as db_url
import pytest

import pwaccess


##
# @brief Every scheme pwaccess registers must be present.
#
@pytest.mark.parametrize('scheme', ['access', 'msaccess',
                                    'access+pool', 'msaccess+pool'])
def test_scheme_registered(scheme):
	assert scheme in db_url.schemes


##
# @brief All three accepted spellings must yield the same path.
#
@pytest.mark.parametrize('url,expected', [
	('access:///C:/data/app.accdb', 'C:/data/app.accdb'),
	('access://C:/data/app.accdb', 'C:/data/app.accdb'),
	('access:///C|/data/app.accdb', 'C:/data/app.accdb'),
])
def test_path_spellings(url, expected):
	assert db_url.connect(url).database == expected


##
# @brief A multi-character authority is treated as a UNC server name.
#
def test_unc_path():
	assert pwaccess.access_url_to_path('share/app.accdb', 'server') == \
	       '//server/share/app.accdb'


##
# @brief The drive letter is re-cased after urlparse() lower-cases it.
#
def test_drive_letter_recased():
	assert pwaccess.access_url_to_path('data/app.accdb', 'c') == \
	       'C:/data/app.accdb'


##
# @brief A path with no authority and no bar is passed through unchanged.
#
def test_plain_path_unchanged():
	assert pwaccess.access_url_to_path('data/app.accdb') == 'data/app.accdb'


##
# @brief The scheme must select the right class.
#
def test_scheme_selects_class():
	plain = db_url.connect('access:///C:/a.accdb')
	pooled = db_url.connect('access+pool:///C:/a.accdb')
	assert type(plain).__name__ == 'AccessDatabase'
	assert type(pooled).__name__ == 'PooledAccessDatabase'


##
# @brief Query-string parameters must reach the constructor.
#
def test_pool_params_forwarded():
	pooled = db_url.connect(
		'access+pool:///C:/a.accdb?max_connections=8&stale_timeout=300')
	assert pooled._max_connections == 8
	assert pooled._stale_timeout == 300
