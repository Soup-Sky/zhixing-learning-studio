from learning.db import Store

def test_requests_are_idempotent_and_persist_after_reopen(tmp_path):
    path=tmp_path/'db.sqlite'
    db=Store(path)
    one,new=db.create_task('course-a:submit-1','answers','course-a')
    two,new2=db.create_task('course-a:submit-1','answers','course-a')
    assert one['id']==two['id'] and new and not new2
    db.put('courses','a',{'id':'a','title':'a'})
    assert Store(path).get('courses','a')['title']=='a'

def test_retention_keeps_materials_and_notebook_of_courses_in_use(tmp_path):
    db=Store(tmp_path/'db.sqlite')
    db.put('courses','active',{'id':'active','source_ids':['openstax-c1','used-search']})
    db.put('courses','idle',{'id':'idle','source_ids':[]})
    db.put('sources','openstax-c1',{'id':'openstax-c1'})
    db.put('sources','upload',{'id':'upload','owner_id':'u'})
    db.put('sources','used-search',{'id':'used-search','search_snippet':'s'})
    db.put('sources','unused-search',{'id':'unused-search','search_snippet':'s'})
    db.put('notebook','keep',{'id':'keep','course_id':'active'})
    db.put('reviews','idle-review',{'id':'idle-review','course_id':'idle'})
    db.put('reviews','orphan',{'id':'orphan','course_id':'gone'})
    old='2000-01-01T00:00:00+00:00'
    with db.connection() as c:
        c.execute("UPDATE documents SET updated_at=? WHERE NOT (kind='courses' AND id='active')",(old,))
    db.prune(90)
    assert {s['id'] for s in db.list('sources')}=={'openstax-c1','upload','used-search'}
    assert [n['id'] for n in db.list('notebook')]==['keep']
    # An idle course goes with its records; records of deleted courses are cleaned up too.
    assert [c['id'] for c in db.list('courses')]==['active'] and db.list('reviews')==[]

def test_course_delete_removes_associated_private_records(tmp_path):
    db=Store(tmp_path/'db.sqlite')
    db.put('courses','a',{'id':'a'})
    db.put('reviews','r',{'id':'r','course_id':'a'})
    db.put('notebook','n',{'id':'n','course_id':'a'})
    db.delete_course('a')
    assert db.list('reviews')==[] and db.list('notebook')==[]
