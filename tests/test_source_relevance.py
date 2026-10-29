import asyncio

from learning import sources
from learning.db import Store
from learning.engine import Engine


def test_course_view_groups_existing_duplicate_urls_and_flags_irrelevant_auto_source(tmp_path):
    db = Store(tmp_path / 'sources.sqlite')
    for id in ('a', 'b'):
        db.put('sources', id, {'id': id, 'title': '微信，是一个生活方式',
                             'url': 'https://weixin.qq.com/#'+id,
                             'text': '微信下载与公众平台', 'search_snippet': 'Calculus tutorial',
                             'review_status': 'needs_human_review'})
    # Distinct pages with the same title must remain distinct.
    db.put('sources', 'chapter', {'id': 'chapter', 'title': '微信，是一个生活方式',
                                'url': 'https://example.com/limits', 'text': 'Calculus notes',
                                'review_status': 'needs_human_review'})
    original = {'id': 'c', 'topic': '微积分', 'source_ids': ['a', 'b', 'chapter']}
    db.put('courses', 'c', original)
    view = Engine(db, None).view('c')
    assert len(view['sources']) == 2
    assert view['sources'][0]['record_ids'] == ['a', 'b']
    assert view['sources'][0]['relevance_note']
    assert 'relevance_note' not in view['sources'][1]
    assert db.get('courses', 'c') == original
    assert len(db.list('sources')) == 3


def test_search_excludes_unrelated_redirect_landing_page(monkeypatch):
    html = b'<li class="b_algo"><h2><a href="https://example.com/result">Calculus</a></h2></li>'

    async def download(url):
        return url, 'text/html', html

    async def fetch(url):
        return {'id': 'wechat', 'url': 'https://weixin.qq.com/',
                'title': '微信，是一个生活方式', 'text': '微信下载与公众平台',
                'review_status': 'needs_human_review'}

    monkeypatch.setattr(sources, '_download', download)
    monkeypatch.setattr(sources, 'fetch_source', fetch)
    assert asyncio.run(sources.search_sources('微积分 university tutorial')) == []


def test_search_deduplicates_final_url_after_redirects(monkeypatch):
    html = b''.join(
        f'<li class="b_algo"><h2><a href="https://example.com/{n}">Limits</a></h2></li>'.encode()
        for n in range(3)
    )

    async def download(url):
        return url, 'text/html', html

    async def fetch(url):
        return {'id': url, 'url': 'https://example.com/calculus#section',
                'title': 'Limits explained', 'text': 'Limits of continuous functions',
                'review_status': 'needs_human_review'}

    monkeypatch.setattr(sources, '_download', download)
    monkeypatch.setattr(sources, 'fetch_source', fetch)
    found = asyncio.run(sources.search_sources('limits university tutorial'))
    assert len(found) == 1
    assert found[0]['review_status'] == 'ai_reviewed'


def test_search_accepts_chinese_topic_with_english_textbook(monkeypatch):
    html = b'<li class="b_algo"><h2><a href="https://example.com/chapter">Book</a></h2></li>'

    async def download(url):
        return url, 'text/html', html

    async def fetch(url):
        return {'id': 'textbook', 'url': url, 'title': 'Calculus Volume 1',
                'text': 'Differentiation and integration', 'review_status': 'needs_human_review'}

    monkeypatch.setattr(sources, '_download', download)
    monkeypatch.setattr(sources, 'fetch_source', fetch)
    assert len(asyncio.run(sources.search_sources('微积分 university tutorial'))) == 1
