import asyncio
import io
import zipfile
import pytest
import httpx
from learning import sources


def test_text_upload_and_unknown_license():
    s = sources.extract_upload('notes.md', '# 原创\n极限说明'.encode())
    assert '极限说明' in s['text']
    assert s['license'] == 'unknown'
    assert s['review_status'] == 'ai_reviewed'
    assert s['ai_review']['verdict'] == 'uncertain'
    with pytest.raises(ValueError):
        sources.extract_upload('program.exe', b'abc')


@pytest.mark.parametrize('url', ['http://127.0.0.1/a', 'http://[::1]/', 'http://169.254.169.254/', 'file:///a', 'https://user:pass@example.com', 'http://10.2.3.4/'])
def test_unsafe_url_blocked(url):
    with pytest.raises(ValueError):
        asyncio.run(sources.fetch_source(url))


def test_docx_upload():
    from docx import Document
    doc = Document(); doc.add_paragraph('连续性需满足三个条件')
    data = io.BytesIO(); doc.save(data)
    assert '三个条件' in sources.extract_upload('a.docx',data.getvalue())['text']


def test_redirect_private_ip_blocked(monkeypatch):
    async def public(url): return url
    monkeypatch.setattr(sources, '_validate_url', public)
    transport = httpx.MockTransport(lambda req: httpx.Response(302, headers={'location':'http://127.0.0.1/a'}))
    original = httpx.AsyncClient
    monkeypatch.setattr(sources.httpx,'AsyncClient',lambda **kw: original(transport=transport, **kw))
    with pytest.raises(ValueError): asyncio.run(sources.fetch_source('https://example.com/a'))


def test_html_original_text(monkeypatch):
    async def public(url): return url
    monkeypatch.setattr(sources,'_validate_url',public)
    transport = httpx.MockTransport(lambda req: httpx.Response(200,headers={'content-type':'text/html'},text='<title>Limits</title><script>secret</script><main>Actual limits explanation</main>'))
    original = httpx.AsyncClient
    monkeypatch.setattr(sources.httpx,'AsyncClient',lambda **kw: original(transport=transport, **kw))
    s = asyncio.run(sources.fetch_source('https://example.com/a'))
    assert s['title'] == 'Limits'
    assert 'Actual limits' in s['text'] and 'secret' not in s['text']


def test_search_uses_result_link_and_fetches_original(monkeypatch):
    async def public(url): return url
    monkeypatch.setattr(sources,'_validate_url',public)
    def respond(req):
        if req.url.host=='www.bing.com':
            return httpx.Response(200,headers={'content-type':'text/html'},text='<li class="b_algo"><h2><a href="https://example.com/chapter">Chapter</a></h2><div class="b_caption"><p>Search-only snippet</p></div></li>')
        return httpx.Response(200,headers={'content-type':'text/html'},text='<title>Original limits chapter</title><p>Actual verified retrieval body on limits</p>')
    original=httpx.AsyncClient
    monkeypatch.setattr(sources.httpx,'AsyncClient',lambda **kw: original(transport=httpx.MockTransport(respond),**kw))
    found=asyncio.run(sources.search_sources('limits',1))
    assert len(found)==1 and found[0]['url']=='https://example.com/chapter'
    assert 'Actual verified retrieval' in found[0]['text']
    assert found[0]['search_snippet']=='Search-only snippet'
    assert 'Search-only snippet' not in found[0]['text']


def test_size_and_unsupported_response_are_rejected(monkeypatch):
    async def public(url): return url
    monkeypatch.setattr(sources,'_validate_url',public)
    original=httpx.AsyncClient
    for headers,body in [({'content-type':'image/png'},b'abc'),({'content-type':'text/plain','content-length':str(sources.MAX_BYTES+1)},b'a'),({'content-type':'text/plain'},b'a'*(sources.MAX_BYTES+1))]:
        monkeypatch.setattr(sources.httpx,'AsyncClient',lambda **kw: original(transport=httpx.MockTransport(lambda req: httpx.Response(200,headers=headers,content=body)),**kw))
        with pytest.raises(ValueError): asyncio.run(sources.fetch_source('https://example.com/a'))


def test_mixed_public_private_dns_is_rejected(monkeypatch):
    monkeypatch.setattr(sources.socket,'getaddrinfo',lambda *a,**kw: [(2,1,6,'',('93.184.216.34',443)),(2,1,6,'',('10.0.0.1',443))])
    with pytest.raises(ValueError): asyncio.run(sources.fetch_source('https://example.com/a'))


def test_dns_address_is_pinned_with_origin_host(monkeypatch):
    monkeypatch.setattr(sources.socket,'getaddrinfo',lambda *a,**kw: [(2,1,6,'',('93.184.216.34',443))])
    def respond(req):
        assert req.url.host=='93.184.216.34'
        assert req.headers['host']=='example.com'
        assert req.extensions['sni_hostname']=='example.com'
        return httpx.Response(200,headers={'content-type':'text/plain'},text='Public original')
    original=httpx.AsyncClient
    monkeypatch.setattr(sources.httpx,'AsyncClient',lambda **kw: original(transport=httpx.MockTransport(respond),**kw))
    assert asyncio.run(sources.fetch_source('https://example.com/a'))['url']=='https://example.com/a'


def test_fake_ip_dns_uses_trusted_public_resolution(monkeypatch):
    monkeypatch.setattr(sources.socket,'getaddrinfo',lambda *a,**kw: [(2,1,6,'',('198.18.0.64',443))])
    async def resolve(host):
        assert host=='example.com'
        return ['93.184.216.34']
    monkeypatch.setattr(sources,'_trusted_dns',resolve)
    assert asyncio.run(sources._validate_url('https://example.com/a'))=='93.184.216.34'


def test_fake_ip_doh_private_answer_still_blocked(monkeypatch):
    monkeypatch.setattr(sources.socket,'getaddrinfo',lambda *a,**kw: [(2,1,6,'',('198.18.0.64',443))])
    async def resolve(host): return ['127.0.0.1']
    monkeypatch.setattr(sources,'_trusted_dns',resolve)
    with pytest.raises(ValueError): asyncio.run(sources._validate_url('https://example.com/a'))


def test_pdf_extract_and_scan_rejection():
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject,NameObject,DictionaryObject
    writer=PdfWriter(); page=writer.add_blank_page(width=200,height=200)
    stream=DecodedStreamObject(); stream.set_data(b'BT /F1 12 Tf 10 100 Td (Limits text) Tj ET')
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    page[NameObject('/Contents')]=writer._add_object(stream)
    buffer=io.BytesIO(); writer.write(buffer)
    source=sources.extract_upload('notes.pdf',buffer.getvalue())
    assert 'Limits text' in source['text'] and '1' in source['locator'] or '[第 1 页]' in source['text']
    blank=PdfWriter(); blank.add_blank_page(width=100,height=100); data=io.BytesIO(); blank.write(data)
    with pytest.raises(ValueError): sources.extract_upload('scan.pdf',data.getvalue())


def test_docx_zip_bomb_and_invalid_archive_rejected():
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('word/document.xml',b'a'*(16*1024*1024+1))
    with pytest.raises(ValueError,match='DOCX'):
        sources.extract_upload('oversized.docx',data.getvalue())
    with pytest.raises(ValueError): sources.extract_upload('invalid.docx',b'not a zip')
    with pytest.raises(ValueError): sources.extract_upload('too-large.txt',b'a'*(sources.MAX_BYTES+1))


def test_redirect_revalidates_dns(monkeypatch):
    def resolve(host,*args,**kwargs):
        return [(2,1,6,'',('93.184.216.34' if host=='example.com' else '10.0.0.1',443))]
    monkeypatch.setattr(sources.socket,'getaddrinfo',resolve)
    requests=[]
    def respond(req):
        requests.append(req)
        return httpx.Response(302,headers={'location':'https://private.example/page'})
    original=httpx.AsyncClient
    monkeypatch.setattr(sources.httpx,'AsyncClient',lambda **kw: original(transport=httpx.MockTransport(respond),**kw))
    with pytest.raises(ValueError): asyncio.run(sources.fetch_source('https://example.com/a'))
    assert len(requests)==1
