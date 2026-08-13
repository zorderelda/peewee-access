"""
pwaccess -- Microsoft Access (JET/ACE) backend for the peewee ORM.

Use peewee exactly as you normally would; only the Database class changes::

    from peewee import *
    from pwaccess import AccessDatabase

    db = AccessDatabase(r'C:\\data\\myapp.accdb')

    class User(Model):
        username = TextField(unique=True)

        class Meta:
            database = db

Connection pooling reuses peewee's own generic pool mixin::

    from pwaccess import PooledAccessDatabase
    db = PooledAccessDatabase(r'C:\\data\\app.accdb', max_connections=8)

Requirements
------------
    pip install pyodbc pywin32

* pyodbc  -- the DB-API driver; peewee itself has no ODBC support.
* pywin32 -- supplies the ADOX COM interface, used both to create a
             database file that does not yet exist and to read the schema
             metadata the Access ODBC driver refuses to report.

Importing this package applies the peewee SQL-generation patches and wires
up playhouse's tooling. Both steps are idempotent, so a reimport or an
``importlib.reload()`` is harmless.
"""

from ._drivers import (
    adox_provider,
    adox_providers,
    create_database_file,
    detect_driver,
    iter_access_drivers,
    list_access_drivers,
    normalize_path,
    read_adox_table_schema,
    require_driver,
)
from ._patches import install as _install_patches
from ._patches import is_installed, uninstall
from .database import AccessContext, AccessDatabase
from .exceptions import (
    AccessConfigurationError,
    AccessNotSupportedError,
    DriverNotFoundError,
    FileCreationError,
)
from .orm_utils import AccessKeyValue, AccessPaginatedQuery, paginate
from .pool import PooledAccessDatabase
from .tools import (
    IGNORED_URL_PARAMS,
    AccessMetadata,
    AccessMigrator,
    access_pool_url_connect,
    access_url_connect,
    access_url_to_path,
    register_tooling,
    tooling_registered,
)
from .types import FIELD_TYPES, OPERATIONS

__version__ = '1.0.2'

__all__ = [
    'AccessConfigurationError',
    'AccessContext',
    'AccessDatabase',
    'AccessKeyValue',
    'AccessMetadata',
    'AccessMigrator',
    'AccessNotSupportedError',
    'AccessPaginatedQuery',
    'DriverNotFoundError',
    'FIELD_TYPES',
    'FileCreationError',
    'IGNORED_URL_PARAMS',
    'OPERATIONS',
    'PooledAccessDatabase',
    'access_pool_url_connect',
    'access_url_connect',
    'access_url_to_path',
    'adox_provider',
    'adox_providers',
    'create_database_file',
    'detect_driver',
    'is_installed',
    'iter_access_drivers',
    'list_access_drivers',
    'normalize_path',
    'paginate',
    'read_adox_table_schema',
    'register_tooling',
    'require_driver',
    'tooling_registered',
    'uninstall',
    '__version__',
]

# Apply the peewee patches, then wire reflection, migrations, db_url and
# pwiz. Both are idempotent, so reimport or reload is harmless.
_install_patches()
register_tooling()
