##
# @file test_live_join.py
# @brief Multi-table joins executed against a real Access database.
#
# Access does not accept the flat "FROM a JOIN b ON ... JOIN c ON ..."
# spelling that every other SQL dialect uses. Jet requires each additional
# join to be parenthesised against everything to its left:
#
#     FROM ([a] INNER JOIN [b] ON ...) INNER JOIN [c] ON ...
#
# The offline suite pins the shape of the generated SQL, but shape is not
# proof: a string can look correct and still be rejected by the driver.
# These tests execute the statements, which is the only way to know the
# parenthesisation is one Jet actually accepts.
#
# The fixture builds its own three-table chain rather than borrowing
# live_models, so it cannot disturb the session-scoped note/comment
# tables or their drop ordering.
#

import pytest

pytestmark = pytest.mark.driver


##
# @brief A three-table chain: Author <- Article <- Remark.
#
# Returns an (Author, Article, Remark) tuple with tables created and
# populated. The data is shaped so an incorrect join silently returning
# a cartesian product would produce the wrong row count rather than the
# right one by luck: two authors, three articles, four remarks.
#
@pytest.fixture(scope='module')
def chain(live_db):
	from peewee import CharField, ForeignKeyField, Model, TextField

	_db = live_db

	class Author(Model):
		name = CharField()

		class Meta:
			database = _db
			table_name = 'j_author'

	class Article(Model):
		author = ForeignKeyField(Author, backref='articles')
		title = CharField()

		class Meta:
			database = _db
			table_name = 'j_article'

	class Remark(Model):
		article = ForeignKeyField(Article, backref='remarks')
		body = TextField(null=True)

		class Meta:
			database = _db
			table_name = 'j_remark'

	models = [Remark, Article, Author]
	live_db.drop_tables(models, safe=True)
	live_db.create_tables([Author, Article, Remark])

	ada = Author.create(name='Ada')
	grace = Author.create(name='Grace')

	notes = Article.create(author=ada, title='On Notation')
	engines = Article.create(author=ada, title='On Engines')
	compilers = Article.create(author=grace, title='On Compilers')

	Remark.create(article=notes, body='first')
	Remark.create(article=notes, body='second')
	Remark.create(article=engines, body='third')
	Remark.create(article=compilers, body='fourth')

	yield Author, Article, Remark

	live_db.drop_tables(models, safe=True)


##
# @brief The generated SQL must parenthesise the second join.
#
# Deliberately loose: Jet accepts "([a] JOIN [b] ON ...) JOIN [c]" and
# does not require an outer pair wrapping the whole clause, so asserting
# an exact paren count would pin an implementation detail rather than a
# requirement. What matters is that a group opens after FROM.
#
def test_three_table_join_sql_is_nested(chain):
	Author, Article, Remark = chain

	query = (Remark
	         .select()
	         .join(Article)
	         .join(Author))
	sql = query.sql()[0]

	from_clause = sql[sql.index('FROM'):]
	assert from_clause.startswith('FROM ('), sql
	assert from_clause.count('JOIN') == 2, sql


##
# @brief The three-table join must execute rather than merely generate.
#
# This is the assertion the whole file exists for. A driver that rejects
# the parenthesisation raises here with a syntax error in the FROM clause.
#
def test_three_table_join_executes(chain):
	Author, Article, Remark = chain

	rows = list(Remark
	            .select()
	            .join(Article)
	            .join(Author))
	assert len(rows) == 4


##
# @brief Joined columns must resolve to the right related rows.
#
# Row count alone would pass under a mistaken cross join if the numbers
# happened to line up, so this checks the actual author behind each
# remark. Ada wrote two of the three articles, carrying three remarks.
#
def test_three_table_join_resolves_relations(chain):
	Author, Article, Remark = chain

	query = (Remark
	         .select(Remark, Article, Author)
	         .join(Article)
	         .join(Author))

	by_author = {}
	for remark in query:
		name = remark.article.author.name
		by_author[name] = by_author.get(name, 0) + 1

	assert by_author == {'Ada': 3, 'Grace': 1}


##
# @brief A join filtered on the far table must execute and select correctly.
#
# The WHERE references a column two joins away, which is where a
# mis-parenthesised FROM clause tends to fail even when the unfiltered
# form happens to work.
#
def test_join_with_where_on_far_table(chain):
	Author, Article, Remark = chain

	rows = list(Remark
	            .select()
	            .join(Article)
	            .join(Author)
	            .where(Author.name == 'Grace'))
	assert len(rows) == 1
	assert rows[0].body == 'fourth'


##
# @brief LIMIT becomes SELECT TOP, which must survive the nested FROM.
#
# TOP is injected at the head of the statement while the parenthesised
# joins sit at the tail; this confirms the two patches compose.
#
def test_join_with_top(chain):
	Author, Article, Remark = chain

	rows = list(Remark
	            .select()
	            .join(Article)
	            .join(Author)
	            .order_by(Remark.id)
	            .limit(2))
	assert len(rows) == 2


##
# @brief An ORDER BY across the joined tables must execute.
#
def test_join_with_order_by_joined_column(chain):
	Author, Article, Remark = chain

	rows = list(Remark
	            .select(Remark, Article, Author)
	            .join(Article)
	            .join(Author)
	            .order_by(Author.name, Remark.id))
	assert [r.article.author.name for r in rows] == \
	       ['Ada', 'Ada', 'Ada', 'Grace']


##
# @brief A LEFT OUTER join across three tables must execute.
#
# Jet spells outer joins LEFT JOIN and is stricter about them inside
# nested parentheses than it is about inner joins, so this is a distinct
# risk from the INNER case above.
#
def test_three_table_left_join_executes(chain):
	Author, Article, Remark = chain
	from peewee import JOIN

	rows = list(Author
	            .select()
	            .join(Article, JOIN.LEFT_OUTER)
	            .join(Remark, JOIN.LEFT_OUTER))
	assert len(rows) == 4


##
# @brief Mixing INNER and LEFT OUTER in one nested FROM must execute.
#
# Jet historically rejects some mixed-join nestings outright. If this
# ever fails while the pure-INNER and pure-LEFT cases pass, the fault is
# the driver's rather than the parenthesisation's, and the limitation
# belongs in the README.
#
def test_mixed_join_kinds_execute(chain):
	Author, Article, Remark = chain
	from peewee import JOIN

	rows = list(Author
	            .select()
	            .join(Article)
	            .join(Remark, JOIN.LEFT_OUTER))
	assert len(rows) == 4


##
# @brief A four-table join must nest to two levels.
#
# Three joins means the parenthesisation has to recurse rather than
# special-case a single extra table: (((a J b) J c) J d). Remark is
# joined back to Article a second time under an alias so a fourth
# relation exists without a fourth table.
#
def test_four_table_join_executes(chain):
	Author, Article, Remark = chain

	other = Article.alias()

	rows = list(Remark
	            .select()
	            .join(Article)
	            .join(Author)
	            .join(other, on=(other.author == Author.id))
	            .where(Author.name == 'Grace'))
	assert len(rows) == 1
