from peewee import IntegerField, Model
from pwaccess import AccessDatabase

db = AccessDatabase(r'C:\__PythonProjects\peewee-access\pagetest.accdb')

class Row(Model):
    n = IntegerField()
    class Meta:
        database = db
        table_name = 'row_t'

db.drop_tables([Row], safe=True)
db.create_tables([Row])

Row.insert_many([{'n': i} for i in range(5)]).execute()
print('dicts ->', [r.n for r in Row.select().order_by(Row.n)])

Row.insert_many([(100,), (200,)], fields=[Row.n]).execute()
print('tuples ->', [r.n for r in Row.select().order_by(Row.n)])

with db.atomic():
    Row.insert_many([{'n': 999}, {'n': 1000}]).execute()
print('in atomic ->', Row.select().count())