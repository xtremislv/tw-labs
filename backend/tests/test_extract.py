from app.extract import compare_versions, extract_page
from tests.fakesite import FakeSite


def _page(site: FakeSite, slug: str) -> str:
    import httpx

    return site.handler(httpx.Request("GET", site.url(slug))).text


def test_extract_reads_jsonld_and_body():
    s = FakeSite()
    slug = "galaxy-s27-ultra-launched-in-india-price-specs"
    pd = extract_page(_page(s, slug), s.url(slug))
    assert pd.title == "Galaxy S27 Ultra launched in India: price, specs"
    assert pd.author == "Riya Sharma"
    assert pd.section == "Mobiles"
    assert pd.tags == ["samsung", "android"]
    assert pd.published_at is not None and pd.modified_at is not None
    assert pd.thumbnail_url.endswith(f"{slug}.jpg")
    assert pd.word_count > 100
    assert pd.youtube_ids == ["dQw4w9WgXcQ"]
    assert pd.affiliate_link_count == 1
    assert pd.headings == ["Specifications", "Price in India"]
    assert len(pd.paragraph_hashes) == 8 and pd.content_hash
    assert pd.content_type == "news"


def test_compare_versions():
    base = dict(old_hash="a", old_paras=["p1", "p2"], old_headings=["H1"], old_title="T", old_words=100)
    same = compare_versions(**base, new_hash="a", new_paras=["p1", "p2"], new_headings=["H1"], new_title="T", new_words=100)
    assert not same.is_real_change
    edited = compare_versions(**base, new_hash="b", new_paras=["p1", "p2", "p3"], new_headings=["H1", "Price"], new_title="T", new_words=160)
    assert edited.is_real_change and edited.paragraphs_added == 1 and edited.headings_added == ["Price"]
    assert "+60 words" in edited.summary and "new sections: Price" in edited.summary
    retitled = compare_versions(**base, new_hash="a", new_paras=["p1", "p2"], new_headings=["H1"], new_title="T2", new_words=100)
    assert retitled.is_real_change and "title changed" in retitled.summary
