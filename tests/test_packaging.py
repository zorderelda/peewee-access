##
# @file test_packaging.py
# @brief Guards on the things that break a release rather than a query.
#
# A package can pass every functional test and still ship broken: a
# version that disagrees with its metadata, an __all__ that promises names
# the module does not have, or a hard import of an optional dependency
# that makes the whole package unimportable on a machine without it.
#

import ast
import importlib
import pathlib
import sys

import pytest

import pwaccess


##
# @brief The declared version must be a released-looking triple.
#
def test_version_is_a_release_triple():
	parts = pwaccess.__version__.split('.')
	assert len(parts) == 3
	assert all(p.isdigit() for p in parts)


##
# @brief pyproject.toml must read its version from the package.
#
# The version is declared dynamic, sourced from pwaccess.__version__, so
# the two cannot drift. This asserts the wiring is still in place -- a
# reverted "dynamic" line would silently republish the old number.
#
def test_pyproject_version_is_dynamic():
	tomllib = pytest.importorskip('tomllib')

	root = pathlib.Path(__file__).resolve().parent.parent
	pyproject = root / 'pyproject.toml'
	if not pyproject.exists():           # installed sdist, not a checkout
		pytest.skip('not running from a source checkout')

	with pyproject.open('rb') as handle:
		config = tomllib.load(handle)

	assert 'version' in config['project'].get('dynamic', [])
	assert config['tool']['setuptools']['dynamic']['version'] == \
	       {'attr': 'pwaccess.__version__'}


##
# @brief Every name in __all__ must actually exist.
#
def test_all_names_resolve():
	missing = [name for name in pwaccess.__all__
	           if not hasattr(pwaccess, name)]
	assert missing == []


##
# @brief Every public class and function must be exported.
#
# A name reachable as pwaccess.foo but absent from __all__ is invisible to
# "from pwaccess import *" and to the documentation build.
#
def test_public_names_are_exported():
	exported = set(pwaccess.__all__)
	unexported = [
		name for name in dir(pwaccess)
		if not name.startswith('_')
		and not isinstance(getattr(pwaccess, name), type(pwaccess))
		and name not in exported
	]
	assert unexported == []


##
# @brief Importing the package must not require pyodbc.
#
# pyodbc is a hard dependency, but an unguarded import of it turns a
# missing driver into "the package will not import at all", which
# pre-empts the specific installation guidance _connect() exists to give
# and makes the driver-free half of this suite unrunnable. Every module
# that touches pyodbc has to guard the import.
#
@pytest.mark.parametrize('module', [
	'pwaccess.database',
	'pwaccess.pool',
	'pwaccess._drivers',
])
def test_modules_guard_the_pyodbc_import(module):
	source = pathlib.Path(sys.modules[module].__file__).read_text()
	tree = ast.parse(source)

	guarded = {node for handler in ast.walk(tree)
	           if isinstance(handler, ast.Try)
	           for node in ast.walk(handler)}

	for node in ast.walk(tree):
		if isinstance(node, ast.Import) and \
				any(a.name == 'pyodbc' for a in node.names):
			assert node in guarded, '%s imports pyodbc unguarded' % module


##
# @brief A reload must not stack a second layer of patches.
#
# The patches are applied to peewee's classes at import time. A reload
# re-executes the module; without the marker each wrapper carries, the
# already-patched method would be captured as the "original" and every
# call would go through two wrappers.
#
def test_reload_does_not_double_patch():
	from peewee import Field

	before = Field.ddl
	importlib.reload(pwaccess)
	after = Field.ddl

	assert getattr(after, '_pwaccess_patch', False)
	## Whatever the reload rebound, the original underneath must still be
	## peewee's own method rather than another wrapper.
	original = after._pwaccess_original
	assert not getattr(original, '_pwaccess_patch', False)
	assert pwaccess.is_installed()
	assert before is not None


##
# @brief The console-script entry point must be importable and callable.
#
def test_entry_point_resolves():
	from pwaccess.__main__ import main
	assert callable(main)
