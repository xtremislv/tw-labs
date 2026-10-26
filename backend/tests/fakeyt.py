"""Simulated YouTube Data API + SponsorBlock + Apify + Slack/Telegram for tests."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeYouTube:
    def __init__(self):
        self.channels = {
            "UCaaaaaaaaaaaaaaaaaaaaaa": {"handle": "@gadgetnews", "title": "Gadget News TV", "subs": 1_200_000},
        }
        # 8 long videos (older ones ~10k views), 3 shorts, then one hit.
        self.videos: dict[str, dict] = {}
        for i in range(8):
            self.add_video(f"long{i:07d}", "UCaaaaaaaaaaaaaaaaaaaaaa", f"Phone review {i}", hours_ago=24 * (20 - i), views=10_000 + i * 100, duration="PT12M3S")
        for i in range(3):
            self.add_video(f"shrt{i:07d}", "UCaaaaaaaaaaaaaaaaaaaaaa", f"Quick tip {i}", hours_ago=24 * (10 - i), views=50_000, duration="PT45S")
        self.add_video("hitvideo001", "UCaaaaaaaaaaaaaaaaaaaaaa", "Galaxy S27 Ultra review: the camera king", hours_ago=2, views=60_000, duration="PT15M")
        self.requests: list[str] = []
        self.units = 0

    def add_video(self, vid, ch, title, *, hours_ago, views, duration):
        self.videos[vid] = {"ch": ch, "title": title, "published": NOW - timedelta(hours=hours_ago), "views": views, "duration": duration}

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(str(req.url))
        p = req.url.params
        path = req.url.path
        if req.url.host == "www.googleapis.com":
            self.units += 1
            if path.endswith("/channels"):
                items = []
                for cid, c in self.channels.items():
                    if p.get("id") == cid or (p.get("forHandle") or "").lower() == c["handle"]:
                        items.append({"id": cid, "snippet": {"title": c["title"], "thumbnails": {"high": {"url": "https://yt3/avatar.jpg"}}},
                                      "statistics": {"subscriberCount": str(c["subs"])},
                                      "contentDetails": {"relatedPlaylists": {"uploads": "UU" + cid[2:]}}})
                return httpx.Response(200, json={"items": items})
            if path.endswith("/playlistItems"):
                cid = "UC" + p["playlistId"][2:]
                vids = sorted((v for v in self.videos.items() if v[1]["ch"] == cid), key=lambda kv: kv[1]["published"], reverse=True)
                return httpx.Response(200, json={"items": [{"contentDetails": {"videoId": k}} for k, _ in vids]})
            if path.endswith("/videos"):
                items = []
                for vid in p["id"].split(","):
                    v = self.videos.get(vid)
                    if v:
                        items.append({"id": vid, "snippet": {"title": v["title"], "publishedAt": iso(v["published"]), "thumbnails": {"medium": {"url": f"https://i.ytimg/{vid}.jpg"}}},
                                      "statistics": {"viewCount": str(v["views"]), "likeCount": "100", "commentCount": "10"},
                                      "contentDetails": {"duration": v["duration"]}})
                return httpx.Response(200, json={"items": items})
        if req.url.host == "sponsor.ajay.app":
            if p.get("videoID") == "hitvideo001":
                return httpx.Response(200, json=[{"category": "sponsor", "segment": [30.0, 95.5]}])
            return httpx.Response(404)
        if req.url.host == "api.apify.com":
            body = json.loads(req.content)
            assert body["urls"] and body["maxPostsPerChannel"]
            return httpx.Response(201, json=[
                {"postId": "UgkxPOST1", "channelId": "UCaaaaaaaaaaaaaaaaaaaaaa", "text": "Which phone should we review next?",
                 "pollOptions": [{"text": "Pixel 11"}, {"text": "Galaxy S27"}], "likes": "1.2K", "comments": 87, "publishedTimeText": "2 days ago"},
                {"id": "UgkxPOST2", "channelUrl": "https://www.youtube.com/@gadgetnews", "content": "New video is live!",
                 "images": [{"url": "https://yt3/post.jpg"}], "likeCount": 340, "publishedTime": "5 hours ago"},
            ])
        if req.url.host == "hooks.slack.com":
            self.requests.append("SLACK:" + req.content.decode())
            return httpx.Response(200, text="ok")
        if req.url.host == "api.telegram.org":
            self.requests.append("TELEGRAM:" + req.content.decode())
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    def http(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))
