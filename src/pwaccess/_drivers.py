"""ODBC driver discovery, database-file creation, and ADOX metadata."""

import os

from .exceptions import (
    AccessConfigurationError,
    DriverNotFoundError,
    FileCreationError,
)
from .types import ADOX_COL_NULLABLE, ADOX_KEY_FOREIGN

try:
    import pyodbc
except ImportError:  # pragma: no cover
    pyodbc = None

try:
    import win32com.client as _win32com
except ImportError:  # pragma: no cover
    _win32com = None

__all__ = [
    'adox_provider',
    'adox_providers',
    'create_database_file',
    'detect_driver',
    'iter_access_drivers',
    'list_access_drivers',
    'normalize_path',
    'read_adox_table_schema',
    'require_driver',
]


def normalize_path(path):
    """Return *path* as an absolute, backslash-separated string."""
    return os.path.abspath(str(path)).replace('/', '\\')


def iter_access_drivers():
    """Yield the names of every installed Access ODBC driver."""
    if pyodbc is None:
        return []
    return [d for d in pyodbc.drivers() if 'access' in d.lower()]


def detect_driver():
    """
    Return the best available Access ODBC driver name, or ``None``.

    The ACE driver is preferred because it handles both ``.mdb`` and
    ``.accdb``; the legacy JET driver (``.mdb`` only) is the fallback.
    """
    if pyodbc is None:
        return None
    drivers = pyodbc.drivers()
    for driver in drivers:
        if 'access' in driver.lower() and '*.mdb, *.accdb' in driver.lower():
            return driver
    for driver in drivers:
        if 'access' in driver.lower() and '*.mdb' in driver.lower():
            return driver
    return None


def require_driver():
    """
    Return the best available driver name, raising if none is installed.

    :raises DriverNotFoundError: when no Access ODBC driver is present.
    """
    driver = detect_driver()
    if driver:
        return driver
    raise DriverNotFoundError(
        'No Microsoft Access ODBC driver was found.\n'
        'Install the "Microsoft Access Database Engine Redistributable" '
        'matching your Python interpreter\'s bitness, then retry.\n'
        'Run pwaccess.list_access_drivers() to inspect what is installed.')


def list_access_drivers():
    """
    Print the installed Access ODBC drivers, then every ODBC driver.

    Intended for interactive troubleshooting of connection failures.
    """
    import sys

    if pyodbc is None:
        print('pyodbc is not installed.  Run:  pip install pyodbc')
        return

    bits = 64 if sys.maxsize > 2 ** 32 else 32
    print('Python interpreter: %d-bit '
          '(the ODBC driver must match this)' % bits)
    print()

    access = iter_access_drivers()
    if access:
        print('Installed Access ODBC drivers:')
        for driver in access:
            print('  -', driver)
    else:
        print('No Access ODBC drivers found.')
        print('Install the Microsoft Access Database Engine Redistributable.')

    print()
    print('All ODBC drivers on this machine:')
    for driver in pyodbc.drivers():
        print('  -', driver)


def create_database_file(filepath):
    """
    Create an empty Access database file at *filepath*.

    Uses the ADOX COM interface supplied by ``pywin32``. For legacy
    ``.mdb`` files the JET ``CREATE_DB`` connection-string option is
    attempted as a fallback when ``pywin32`` is unavailable.

    :param filepath: Destination path; parent directories are created.
    :returns: The normalized path that was created.
    :raises FileCreationError: when the file could not be created.
    """
    filepath = normalize_path(filepath)
    dirpath = os.path.dirname(filepath)
    if dirpath and not os.path.isdir(dirpath):
        os.makedirs(dirpath, exist_ok=True)

    extension = filepath.rsplit('.', 1)[-1].lower()

    failures = []

    # -- Strategy 1: ADOX via pywin32 ------------------------------------
    # Each candidate provider is tried in turn. A .mdb on 64-bit Windows
    # must go through ACE: Microsoft.Jet.OLEDB.4.0 has no 64-bit build and
    # fails with "Class not registered". An earlier version picked the
    # provider by extension alone and raised immediately on failure, which
    # made .mdb creation impossible on a 64-bit interpreter and left
    # Strategy 2 unreachable.
    if _win32com is not None:
        for provider in adox_providers(filepath):
            catalog = None
            try:
                catalog = _win32com.Dispatch('ADOX.Catalog')
                catalog.Create('Provider=%s;Data Source=%s;'
                               % (provider, filepath))
            except Exception as exc:
                # ADOX can raise while releasing the COM object even though
                # the file was written; only treat this as a failure if the
                # file really is absent.
                if os.path.isfile(filepath):
                    return filepath
                failures.append('ADOX/%s: %s' % (provider, exc))
                continue
            finally:
                try:
                    if catalog is not None:
                        del catalog
                except Exception:
                    pass
            return filepath
    else:
        failures.append(
            'ADOX: pywin32 is not installed (pip install pywin32)')

    # -- Strategy 2: JET CREATE_DB (legacy .mdb only) --------------------
    if pyodbc is not None and extension == 'mdb':
        driver = detect_driver()
        if driver:
            try:
                conn_str = ('Driver={%s};DBQ=%s;CREATE_DB=%s;'
                            % (driver, filepath, filepath))
                pyodbc.connect(conn_str, autocommit=True).close()
                return filepath
            except Exception as exc:
                failures.append('CREATE_DB/%s: %s' % (driver, exc))
        else:
            failures.append('CREATE_DB: no Access ODBC driver found')

    raise FileCreationError(
        'Could not create the Access database %r. Every strategy failed:\n'
        '  %s\n'
        'Install pywin32 (pip install pywin32) and the Microsoft Access '
        'Database Engine redistributable matching your Python bitness, and '
        'confirm the target directory is writable.'
        % (filepath, '\n  '.join(failures)))


def adox_providers(filepath):
    """
    Return the OLE DB providers to try for *filepath*, best first.

    ACE is tried first for every extension, including ``.mdb``. The ACE
    provider reads and writes the legacy Jet format perfectly well, and
    unlike Jet it exists as a 64-bit component: ``Microsoft.Jet.OLEDB.4.0``
    was never shipped for 64-bit Windows, so on a 64-bit interpreter it
    fails with "Class not registered". Jet is kept as a fallback only for
    ``.mdb``, where it may be the only provider present on an old 32-bit
    machine.

    :param filepath: Path to a ``.accdb`` or ``.mdb`` file.
    :returns: A tuple of provider names in the order they should be tried.
    """
    extension = str(filepath).rsplit('.', 1)[-1].lower()
    if extension == 'accdb':
        return ('Microsoft.ACE.OLEDB.12.0',)
    return ('Microsoft.ACE.OLEDB.12.0', 'Microsoft.Jet.OLEDB.4.0')


def adox_provider(filepath):
    """
    Return the preferred OLE DB provider for *filepath*.

    :param filepath: Path to a ``.accdb`` or ``.mdb`` file.
    :returns: The first candidate from :func:`adox_providers`.
    """
    return adox_providers(filepath)[0]


def read_adox_table_schema(filepath, table):
    """
    Read schema facts about *table* that ODBC cannot report.

    The Access ODBC driver does not implement ``SQLPrimaryKeys`` -- it
    answers IM001, "Driver does not support this function" -- so a table's
    primary key is invisible over ODBC. ``SQLStatistics`` does list the
    indexes, but a primary-key index and an ordinary unique index are
    indistinguishable through it: both report ``non_unique = 0``, and the
    primary key is *not* reliably named ``PrimaryKey``. A table created by
    ``CREATE TABLE ... PRIMARY KEY``, which is what peewee emits, gets an
    auto-generated name such as ``Index_0F35A601_B1F5_4928``.

    ADOX exposes the distinction directly through ``Index.PrimaryKey``,
    and also exposes each column's ``Autoincrement`` property, which is
    what peewee needs in order to promote a reflected primary key to
    :class:`~peewee.AutoField`.

    This opens a short-lived OLE DB connection separate from the ODBC one.
    It is read-only and closed before returning, but it is a second
    connection to a single-writer file, so callers should cache the result
    rather than calling this per column.

    :param filepath: Path to the ``.accdb`` / ``.mdb`` file.
    :param table: Name of the table to inspect.
    :returns: A dict with keys ``primary_keys`` (list of column names, in
        index order), ``autoincrement`` (set of column names),
        ``nullable`` (dict of column name -> bool), ``indexes`` (list of
        ``(name, columns, unique, primary)`` tuples) and ``foreign_keys``
        (list of ``(column, dest_table, dest_column)`` tuples).
    :raises AccessConfigurationError: If pywin32 is not installed.
    """
    if _win32com is None:
        raise AccessConfigurationError(
            'pywin32 is required to read primary-key metadata from an '
            'Access database, because the ODBC driver does not implement '
            'SQLPrimaryKeys.\nInstall it with:  pip install pywin32')

    catalog = None
    failures = []
    for provider in adox_providers(filepath):
        candidate = _win32com.Dispatch('ADOX.Catalog')
        try:
            candidate.ActiveConnection = ('Provider=%s;Data Source=%s;'
                                          % (provider, filepath))
            # Touch the collection to force the connection to open now,
            # so an unusable provider is rejected here rather than later.
            candidate.Tables.Refresh()
        except Exception as exc:
            failures.append('%s: %s' % (provider, exc))
            continue
        catalog = candidate
        break

    if catalog is None:
        raise AccessConfigurationError(
            'No usable OLE DB provider for %r. Tried:\n  %s\n'
            'Install the Microsoft Access Database Engine redistributable '
            'matching your Python bitness.'
            % (filepath, '\n  '.join(failures)))

    try:
        adox_table = catalog.Tables(table)

        primary_keys = []
        indexes = []
        for index in adox_table.Indexes:
            columns = [column.Name for column in index.Columns]
            is_primary = bool(index.PrimaryKey)
            indexes.append((index.Name, columns, bool(index.Unique),
                            is_primary))
            if is_primary:
                primary_keys = columns

        autoincrement = set()
        nullable = {}
        for column in adox_table.Columns:
            try:
                if column.Properties('Autoincrement').Value:
                    autoincrement.add(column.Name)
            except Exception:
                # Not every provider exposes the property; a missing value
                # simply means "not an autonumber column".
                pass
            try:
                nullable[column.Name] = bool(int(column.Attributes) &
                                             ADOX_COL_NULLABLE)
            except Exception:
                pass

        # adKeyForeign == 2. Each foreign key's Columns collection carries
        # the local column name plus the RelatedColumn it points at; the
        # target table is on the Key itself.
        foreign_keys = []
        for key in adox_table.Keys:
            if int(key.Type) != ADOX_KEY_FOREIGN:
                continue
            related_table = key.RelatedTable
            for column in key.Columns:
                related_column = getattr(column, 'RelatedColumn', None)
                foreign_keys.append((column.Name, related_table,
                                     related_column))

        return {'primary_keys': primary_keys,
                'autoincrement': autoincrement,
                'nullable': nullable,
                'indexes': indexes,
                'foreign_keys': foreign_keys}
    finally:
        try:
            catalog.ActiveConnection = None
        except Exception:
            pass
        del catalog
