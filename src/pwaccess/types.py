"""Type maps and dialect constants for the Access backend."""

from peewee import (
    AutoField,
    BlobField,
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    DecimalField,
    DoubleField,
    FloatField,
    IntegerField,
    SmallIntegerField,
    TextField,
    TimeField,
    UUIDField,
)

__all__ = [
    'ACCESS_COLUMN_MAP',
    'ADOX_COL_FIXED',
    'ADOX_COL_NULLABLE',
    'ADOX_KEY_FOREIGN',
    'ADOX_KEY_PRIMARY',
    'ADOX_KEY_UNIQUE',
    'FIELD_TYPES',
    'IDENTITY_TYPES',
    'NO_MODIFIERS',
    'NO_NOT_NULL',
    'OPERATIONS',
    'SIZED_CHAR_TYPES',
    'SIZED_DECIMAL_TYPES',
]


# ===========================================================================

#: peewee ``FIELD.*`` names mapped onto Access SQL type names.
#:
#: Notable substitutions:
#:
#: * ``DECIMAL`` -> ``CURRENCY``. Access has no ``DECIMAL`` DDL type at all.
#:   ``CURRENCY`` is 8 bytes with a fixed 4 decimal places.
#: * ``BIGINT`` / ``BIGAUTO`` -> 32-bit types. Access has no 64-bit integer
#:   or autonumber, so values beyond 2**31-1 will overflow.
#: * ``TIME`` -> ``DATETIME``. Access has no standalone time type.
FIELD_TYPES = {
    'AUTO':     'AUTOINCREMENT',
    'BIGAUTO':  'AUTOINCREMENT',
    'BIGINT':   'LONG',
    'BLOB':     'LONGBINARY',
    'BOOL':     'BIT',
    'CHAR':     'TEXT',
    'DATE':     'DATE',
    'DATETIME': 'DATETIME',
    'DECIMAL':  'CURRENCY',
    'DOUBLE':   'DOUBLE',
    'FLOAT':    'SINGLE',
    'INT':      'LONG',
    'SMALLINT': 'SHORT',
    'TEXT':     'MEMO',
    'TIME':     'DATETIME',
    'UUID':     'TEXT(38)',
    'UUIDB':    'LONGBINARY',
    'VARCHAR':  'TEXT',
}

#: peewee operator names remapped for Access.
#:
#: Access ``LIKE`` is already case-insensitive, so ``ILIKE`` collapses onto
#: it. Access has no regular-expression operator; ``REGEXP`` is mapped to
#: ``LIKE`` so that queries fail predictably rather than with a syntax error,
#: but the semantics differ and regex queries should be avoided.
OPERATIONS = {
    'ILIKE': 'LIKE',
    'REGEXP': 'LIKE',
    'IREGEXP': 'LIKE',
}

#: Access types that reject ``(precision, scale)`` arguments in DDL.
NO_MODIFIERS = frozenset((
    'AUTOINCREMENT', 'BIT', 'CURRENCY', 'DATE', 'DATETIME', 'DOUBLE',
    'LONG', 'LONGBINARY', 'MEMO', 'SHORT', 'SINGLE',
))

#: Access types that reject an explicit ``NOT NULL`` clause in DDL.
#:
#: ``BIT`` and ``AUTOINCREMENT`` are implicitly non-nullable; ``MEMO`` and
#: ``LONGBINARY`` simply do not accept the constraint.
NO_NOT_NULL = frozenset((
    'AUTOINCREMENT', 'BIT', 'LONGBINARY', 'MEMO',
))

#: ODBC type names whose reported ``column_size`` is a character length.
#:
#: Used to rebuild the parameterized ``full_type`` string that peewee's
#: reflection needs in order to recover ``max_length``.
SIZED_CHAR_TYPES = frozenset((
    'CHAR', 'NCHAR', 'NVARCHAR', 'TEXT', 'VARCHAR',
))

#: ODBC type names whose size is a numeric precision rather than a length.
SIZED_DECIMAL_TYPES = frozenset((
    'DECIMAL', 'NUMERIC',
))

#: ODBC type names Access uses for an AUTOINCREMENT (autonumber) column.
IDENTITY_TYPES = frozenset((
    'AUTOINCREMENT', 'COUNTER',
))

#: ADOX ``KeyTypeEnum`` values. Used to tell a table's primary key from its
#: foreign keys when reading schema metadata through ADOX.
ADOX_KEY_PRIMARY = 1
ADOX_KEY_FOREIGN = 2
ADOX_KEY_UNIQUE = 3

#: ADOX ``ColumnAttributesEnum`` values, used as a bitmask on
#: ``Column.Attributes``. ``adColFixed`` marks a fixed-length column;
#: ``adColNullable`` is the only trustworthy source of a column's
#: nullability, since the Access ODBC driver reports every non-key column
#: as nullable whether or not NOT NULL was applied.
ADOX_COL_FIXED = 1
ADOX_COL_NULLABLE = 2


#: ODBC ``type_name`` strings reported by the Access driver, mapped onto
#: peewee field classes.
#:
#: The driver reports either Access's native type names (``COUNTER``,
#: ``LONGCHAR``, ``MEMO``...) or the ANSI equivalents (``INTEGER``,
#: ``VARCHAR``...) depending on driver version and on whether the table was
#: created through DAO or through ODBC, so both spellings are listed.
#:
#: Note that Access ``TEXT`` is a *short* text column (255 characters or
#: fewer), equivalent to VARCHAR -- it is not the unbounded type that
#: ``TEXT`` denotes in SQLite or PostgreSQL. The unbounded type is ``MEMO``
#: (``LONGCHAR`` over ODBC).
ACCESS_COLUMN_MAP = {
    'autoincrement':    AutoField,
    'binary':           BlobField,
    'bit':              BooleanField,
    'boolean':          BooleanField,
    'byte':             SmallIntegerField,
    'char':             CharField,
    'counter':          AutoField,
    'currency':         DecimalField,
    'date':             DateField,
    'datetime':         DateTimeField,
    'decimal':          DecimalField,
    'double':           DoubleField,
    'float':            DoubleField,
    'guid':             UUIDField,
    'hyperlink':        TextField,
    'image':            BlobField,
    'int':              IntegerField,
    'integer':          IntegerField,
    'long':             IntegerField,
    'longbinary':       BlobField,
    'longchar':         TextField,
    'longtext':         TextField,
    'memo':             TextField,
    'money':            DecimalField,
    'nchar':            CharField,
    'ntext':            TextField,
    'numeric':          DecimalField,
    'nvarchar':         CharField,
    'ole object':       BlobField,
    'real':             FloatField,
    'short':            SmallIntegerField,
    'single':           FloatField,
    'smallint':         SmallIntegerField,
    'text':             CharField,
    'time':             TimeField,
    'timestamp':        DateTimeField,
    'tinyint':          SmallIntegerField,
    'uniqueidentifier': UUIDField,
    'varbinary':        BlobField,
    'varchar':          CharField,
}
