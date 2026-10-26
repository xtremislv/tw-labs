from datetime import timedelta

import pytest
from sqlalchemy import select

from app import youtube as yt
from app.config import get_settings
from app.models import Channel, CommunityPost, Video
from tests.fakeyt import NOW, FakeYouTube


@pytest.fixture
def fy(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    monkeypatch.setenv("APIFY_API_TOKEN", "apify-token")
    get_settings.cache_clear()
    yield FakeYouTube()
    get_settings.cache_clear()


def test_parsers():
    assert yt.parse_duration("PT1H2M3S") == 3723 and yt.parse_duration("PT45S") == 45 and yt.parse_duration("bad") == 0
    assert yt.classify_format(45) == "short" and yt.classify_format(180) == "short" and yt.classify_format(181) == "long"
    assert yt.resolve_input("@beebomco") == (None, "@beebomco")
    assert yt.resolve_input("UCaaaaaaaaaaaaaaaaaaaaaa") == ("UCaaaaaaaaaaaaaaaaaaaaaa", None)
    assert yt.resolve_input("https://www.youtube.com/channel/UCaaaaaaaaaaaaaaaaaaaaaa") == ("UCaaaaaaaaaaaaaaaaaaaaaa", None)
    with pytest.raises(yt.YouTubeError):
        yt.resolve_input("not a handle!!")


def test_baselines_match_tw_labs_maths():
    t0 = NOW - timedelta(days=30)
    rows = [(f"v{i}", "long", t0 + timedelta(days=i), v) for i, v in enumerate([100, 200, 300, 400, 1000])]
    rows.append(("s0", "short", t0, 5))
    res = yt.compute_baselines(rows, window=10, min_videos=3)
    assert res["v0"].ratio is None and res["v2"].ratio is None  # < 3 prior videos
    assert res["v3"].avg == 200 and res["v3"].ratio == 2.0  # 400 / mean(100,200,300)
    assert res["v4"].median == 250 and res["v4"].ratio_median == 4.0  # 1000 / median(100..400)
    assert res["s0"].ratio is None  # shorts never mix with long-form


def test_add_channel_scrape_sponsor_and_velocity(db, fy):
    client = yt.YouTubeClient("test-key", client=fy.http())
    ch = yt.add_channel(db, client, "https://www.youtube.com/@gadgetnews", cohort="Tech", site_id=None)
    assert ch.name == "Gadget News TV" and ch.subscriber_count == 1_200_000 and ch.uploads_playlist_id
    with pytest.raises(yt.YouTubeError):
        yt.add_channel(db, client, "@gadgetnews", cohort=None, site_id=None)

    st = yt.scrape_all(db, client, sponsor_http=fy.http())
    assert st.channels == 1 and st.videos_new == 12 and not st.errors
    hit = db.get(Video, "hitvideo001")
    assert hit.format == "long" and hit.overperform_ratio > 5  # 60k vs ~10.5k average
    assert hit.has_sponsor_segment and hit.sponsor_segment_seconds == 65.5
    shorts = db.scalars(select(Video).where(Video.format == "short")).all()
    assert len(shorts) == 3 and all(s.overperform_ratio is None for s in shorts)  # only 2 priors each at most
    assert yt.usage_today(db, "youtube") >= 3

    # velocity: the hit is 2 h old → its 1 h checkpoint (grace 2 h) is due
    fy.videos["hitvideo001"]["views"] = 75_000
    captured = yt.capture_velocity(db, yt.YouTubeClient("test-key", client=fy.http()))
    db.refresh(hit)
    assert captured == 1 and hit.h1_views == 75_000 and hit.h3_views is None and hit.views == 75_000


def test_community_posts_normalised(db, fy):
    client = yt.YouTubeClient("test-key", client=fy.http())
    yt.add_channel(db, client, "@gadgetnews", cohort=None, site_id=None)
    new, errors = yt.scrape_posts(db, http=fy.http())
    assert new == 2 and not errors
    poll = db.get(CommunityPost, "UgkxPOST1")
    assert poll.post_type == "poll" and poll.poll_options == ["Pixel 11", "Galaxy S27"] and poll.likes == 1200
    assert poll.published_at is not None and abs((NOW - poll.published_at).total_seconds() - 2 * 86400) < 120
    img = db.get(CommunityPost, "UgkxPOST2")
    assert img.post_type == "image" and img.image_url == "https://yt3/post.jpg" and img.likes == 340
    # re-run updates instead of duplicating
    assert yt.scrape_posts(db, http=fy.http())[0] == 0
    assert db.scalar(select(Channel)).posts_scraped_at is not None


def test_normalize_post_tolerates_unknown_shapes():
    assert yt.normalize_post({"nothing": 1}, NOW) is None
    p = yt.normalize_post({"url": "https://www.youtube.com/post/UgkxABC", "contentText": [{"text": "Hi "}, {"text": "there"}],
                           "voteCount": "3.4M", "attachedVideo": {"videoId": "dQw4w9WgXcQ"}}, NOW)
    assert p["id"] == "UgkxABC" and p["text"] == "Hi  there" and p["likes"] == 3_400_000 and p["post_type"] == "video"


def test_youtube_api(client, db, fy):
    yclient = yt.YouTubeClient("test-key", client=fy.http())
    ch = yt.add_channel(db, yclient, "@gadgetnews", cohort="Tech", site_id=None)
    yt.scrape_all(db, yclient, sponsor_http=fy.http())
    r = client.get("/api/youtube/videos", params={"sort_by": "ratio", "metric": "average"}).json()
    assert r["total"] == 12 and r["items"][0]["id"] == "hitvideo001" and r["overperform_count"] >= 1
    assert client.get("/api/youtube/videos", params={"format": "short"}).json()["total"] == 3
    assert client.get("/api/youtube/videos", params={"has_sponsor": True}).json()["total"] == 1
    assert client.get("/api/youtube/videos", params={"views_threshold": 55000}).json()["total"] == 1
    assert client.get("/api/youtube/videos", params={"q": "galaxy"}).json()["total"] == 1
    for sort in ("views", "date", "engagement", "velocity"):
        assert client.get("/api/youtube/videos", params={"sort_by": sort}).status_code == 200
    chans = client.get("/api/youtube/channels").json()
    assert chans[0]["video_count"] == 12 and chans[0]["median_views_last10"]
    assert client.patch(f"/api/youtube/channels/{ch.id}", json={"cohort": "Rivals", "track_posts": False}).json()["cohort"] == "Rivals"
    st = client.get("/api/youtube/status").json()
    assert st["api_key_set"] and st["videos"] == 12
    assert client.post("/api/youtube/refresh").status_code == 202
    assert client.post("/api/youtube/refresh").status_code == 429
    assert client.delete(f"/api/youtube/channels/{ch.id}").status_code == 204
    assert client.get("/api/youtube/videos").json()["total"] == 0


def test_video_articles_endpoint(client, db, fy):
    from tests.test_insights import _art, _site
    yclient = yt.YouTubeClient("test-key", client=fy.http())
    yt.add_channel(db, yclient, "@gadgetnews", cohort=None, site_id=None)
    yt.scrape_all(db, yclient, sponsor_http=fy.http())
    _art(db, _site(db, "rival.com"), "S27 review", 3, youtube_ids=["hitvideo001"])
    r = client.get("/api/youtube/videos", params={"q": "galaxy"}).json()
    assert r["items"][0]["embedded_in"] == 1
    arts = client.get("/api/youtube/videos/hitvideo001/articles").json()
    assert len(arts) == 1 and arts[0]["site_name"] == "Rival"
