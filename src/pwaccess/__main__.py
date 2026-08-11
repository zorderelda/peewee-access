"""
Command-line entry point: peewee's ``pwiz`` with Access support enabled.

``python -m pwiz -e access file.accdb`` does not work on its own. pwiz
builds the ``-e`` choice list from its ``DATABASE_MAP`` while parsing
arguments, and nothing in that code path imports :mod:`pwaccess`, so the
``access`` engine has not been registered yet and the option is rejected.
Importing this package is what registers it.

Running ``python -m pwaccess`` performs the import first and then
delegates, so the equivalent command is::

    python -m pwaccess -e access C:/data/app.accdb > models.py

Every pwiz option is accepted unchanged.
"""

import sys


def main():
    """Import the backend, then hand off to ``pwiz.main()``."""
    try:
        import pwiz
    except ImportError:  # pragma: no cover
        sys.exit('pwiz could not be imported. It ships inside peewee, so '
                 'reinstall peewee to use the model generator.')
    pwiz.main()


if __name__ == '__main__':
    main()
