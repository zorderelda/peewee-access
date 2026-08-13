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


# ---------------------------------------------------------------------------
# Parameters db_url produces that Access cannot use
# ---------------------------------------------------------------------------
#
# db_url.connect() merges the URL with the caller's **connect_params and
# hands the whole dict to whichever class the scheme selects. That dict is
# shaped for a network database. Anything AccessDatabase does not recognize
# becomes a KEY=VALUE pair in the ODBC connection string, so a stray 'user'
# or 'port' would be sent to the driver verbatim.
#

##
# @brief user and port must not reach the ODBC connection string.
#
@pytest.mark.parametrize('params', [
	{'user': 'jeff'},
	{'port': 1234},
	{'user': 'jeff', 'port': 1234},
])
def test_unusable_params_are_ignored(params):
	db = db_url.connect('access:///C:/a.accdb', driver='D', **params)
	built = db._build_connection_string(db.database)
	assert 'user' not in built
	assert 'port' not in built
	assert db.connect_params == {}


##
# @brief The same parameters carried in the URL itself must also be dropped.
#
# urlparse() puts a userinfo component into 'user' and 'password', and an
# authority port into 'port', so a URL alone can carry them.
#
def test_unusable_params_in_the_url_are_ignored():
	db = db_url.connect('access:///C:/a.accdb?user=jeff&port=1234',
	                    driver='D')
	built = db._build_connection_string(db.database)
	assert 'user' not in built
	assert 'port' not in built


##
# @brief Ignoring must not extend to the parameters Access does use.
#
# password is sent as PWD, host is how a drive letter or UNC server is
# recovered, and an unrecognized keyword is still a legitimate way to reach
# the ODBC connection string -- that is what Exclusive='Yes' relies on.
#
def test_usable_params_still_reach_the_driver():
	db = db_url.connect('access:///C:/a.accdb', driver='D',
	                    password='s3cret', Exclusive='Yes')
	built = db._build_connection_string(db.database)
	assert 'PWD=s3cret' in built
	assert 'Exclusive=Yes' in built


##
# @brief The pooled scheme must ignore them too, and keep its own params.
#
def test_pooled_scheme_ignores_unusable_params():
	pooled = db_url.connect('access+pool:///C:/a.accdb?max_connections=8',
	                        driver='D', user='jeff', port=1234)
	assert pooled._max_connections == 8
	assert pooled.connect_params == {}


##
# @brief One parameter dict must serve Access and another backend alike.
#
# This is the point of ignoring rather than raising: code that builds a
# single set of connection parameters and opens several databases with it
# should not need an Access special case.
#
def test_shared_params_work_across_backends():
	params = {'user': 'jeff', 'password': 's3cret', 'port': 1234}

	access = db_url.connect('access:///C:/a.accdb', driver='D', **params)
	sqlite = db_url.connect('sqlite:///:memory:', **params)

	assert access.database == 'C:/a.accdb'
	## The other backend keeps what it was given; nothing is patched
	## globally, only the Access factories filter.
	assert sqlite.connect_params['user'] == 'jeff'


##
# @brief The ignored names must be inspectable rather than buried.
#
def test_ignored_params_are_published():
	assert 'user' in pwaccess.IGNORED_URL_PARAMS
	assert 'port' in pwaccess.IGNORED_URL_PARAMS
	assert 'password' not in pwaccess.IGNORED_URL_PARAMS
	assert 'database' not in pwaccess.IGNORED_URL_PARAMS
