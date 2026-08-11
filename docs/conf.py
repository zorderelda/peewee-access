##
# @file conf.py
# @brief Sphinx configuration for the peewee-access documentation.
#
# Build with:
#     pip install sphinx
#     cd docs
#     sphinx-build -b html . _build/html
#
# The theme is Alabaster, which ships with Sphinx, so the docs build with
# no dependency beyond Sphinx itself and match the look of peewee's own
# documentation.

import os
import sys

# Put src/ on the path so autodoc and the version import below resolve
# against the working tree rather than an installed copy. The package
# imports pyodbc and pywin32 at module scope, so this only works on a
# machine that has them; see autodoc_mock_imports below for the
# alternative.
sys.path.insert(0, os.path.abspath('../src'))


# -- Project information -----------------------------------------------------

project = 'peewee-access'
author = 'Jeff Walsh'
copyright = '2026, Jeff Walsh'

# Read the version from the package rather than restating it here, so
# there is one place to change it. Falls back to a literal when the
# package cannot be imported, which is the usual case on a docs-only
# build machine without the Access driver.
try:
    from pwaccess import __version__ as release
except Exception:                                  # pragma: no cover
    release = '0.1.0'

version = '.'.join(release.split('.')[:2])


# -- General configuration ---------------------------------------------------

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.intersphinx',
    'sphinx.ext.viewcode',
    'sphinx.ext.napoleon',
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# Treat a bare `foo` as Python code, so the .rst can use single backticks
# without every one of them needing an explicit role.
default_role = 'py:obj'

nitpicky = False


# -- Cross-references to peewee ----------------------------------------------

# Lets :py:class:`~peewee.Database` and friends link to peewee's own docs
# rather than rendering as dead literal text. Requires network access at
# build time; drop this dict to build offline.
intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'peewee': ('http://docs.peewee-orm.com/en/latest', None),
}


# -- Autodoc -----------------------------------------------------------------

# pwaccess imports pyodbc and pywin32 at module scope. On a build machine
# without them -- a Linux CI runner, say -- autodoc would fail on import.
# Mocking lets the docstrings be extracted anyway.
autodoc_mock_imports = ['pyodbc', 'win32com', 'pythoncom']

autodoc_member_order = 'bysource'
autodoc_typehints = 'description'


# -- HTML output -------------------------------------------------------------

html_theme = 'alabaster'
html_static_path = ['_static']

html_theme_options = {
    'description': 'Microsoft Access backend for the peewee ORM',
    'github_user': 'zorderelda',
    'github_repo': 'peewee-access',
    'github_button': True,
    'github_type': 'star',
    'fixed_sidebar': True,
    'page_width': '1000px',
}

html_sidebars = {
    '**': [
        'about.html',
        'navigation.html',
        'relations.html',
        'searchbox.html',
    ]
}