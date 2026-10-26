"""Tests. Run with: python3 -m unittest -v"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gta6digest import http  # noqa: E402
from gta6digest.classifier import Classifier, stronger_status  # noqa: E402
from gta6digest.clustering import is_same_story  # noqa: E402
from gta6digest.digest import build_digest, html_to_console  # noqa: E402
from gta6digest.models import Post  # noqa: E402
from gta6digest.sources import NewsRssSource, RedditApiSource, RedditRssSource  # noqa: E402
from gta6digest.sources.reddit_api import parse_listing  # noqa: E402
from gta6digest.sources.reddit_rss import parse_reddit_feed  # noqa: E402
from gta6digest.storage import Storage  # noqa: E402
from gta6digest.telegram import split_message  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
CLS = Classifier(["rockstargames.com", "take2games.com"])
EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


def post(title, text="", link=None, pid=None):
    return Post(source="test", external_id=pid or title, title=title, url="https://x/" + title[:5],
                published=datetime.now(timezone.utc), text=text, link_url=link)


def assert_no_author(test, posts):
    for p in posts:
        blob = " ".join(str(v) for v in vars(p).values())
        for needle in ("user_", "_user", "/u/", "[deleted]"):
            test.assertNotIn(needle, blob, p)


class RedditRssTest(unittest.TestCase):
    def setUp(self):
        self.posts = parse_reddit_feed((FIX / "reddit_new.xml").read_bytes())

    def test_parses_all(self):
        self.assertEqual(len(self.posts), 5)

    def test_no_usernames_anywhere(self):
        assert_no_author(self, self.posts)

    def test_external_link(self):
        by_id = {p.external_id: p for p in self.posts}
        self.assertIn("rockstargames.com", by_id["t3_aaa111"].link_url)
        self.assertIsNone(by_id["t3_bbb222"].link_url)  # text post

    def test_text_extracted(self):
        by_id = {p.external_id: p for p in self.posts}
        self.assertIn("Epsilon poster", by_id["t3_bbb222"].text)


class FakeReddit:
    """Stands in for http.request and records every call."""

    def __init__(self, info_children=None, remaining="595"):
        self.calls = []
        self.info_children = info_children or []
        self.remaining = remaining

    def __call__(self, method, url, user_agent, headers=None, data=None, **kw):
        self.calls.append((method, url, user_agent, headers or {}))
        if "access_token" in url:
            body = {"access_token": "tok", "expires_in": 3600}
        elif "/api/info" in url:
            body = {"data": {"children": self.info_children}}
        else:
            body = json.loads((FIX / "reddit_listing.json").read_text())
        return http.Response(200, {"x-ratelimit-remaining": self.remaining,
                                   "x-ratelimit-reset": "300"}, json.dumps(body).encode())


def api_source(**kw):
    return RedditApiSource("GTA6", "gta6-digest/0.2 by u/test_app", ["new"],
                           "cid", "secret", "test_app", "pw", min_interval=0, **kw)


class RedditApiTest(unittest.TestCase):
    def test_parse_listing(self):
        posts = parse_listing(json.loads((FIX / "reddit_listing.json").read_text()))
        self.assertEqual([p.external_id for p in posts], ["t3_fff666", "t3_ggg777"])  # removed one skipped
        first = posts[0]
        self.assertEqual(first.score, 4210)
        self.assertEqual(first.flair, "News")
        self.assertIn("rockstargames.com", first.link_url)
        self.assertIsNone(posts[1].link_url)  # self post
        assert_no_author(self, posts)

    def test_read_only_and_user_agent(self):
        fake = FakeReddit()
        with mock.patch.object(http, "request", side_effect=fake):
            api_source().fetch()
        methods = [(m, u) for m, u, _, _ in fake.calls]
        # only the OAuth token request is a POST; everything else is a GET
        self.assertTrue(all(m == "GET" for m, u in methods if "access_token" not in u))
        self.assertTrue(all(ua == "gta6-digest/0.2 by u/test_app" for _, _, ua, _ in fake.calls))
        self.assertTrue(any("oauth.reddit.com/r/GTA6/new" in u for _, u in methods))

    def test_token_reused(self):
        fake = FakeReddit()
        src = api_source()
        with mock.patch.object(http, "request", side_effect=fake):
            src.fetch()
            src.fetch()
        self.assertEqual(sum("access_token" in u for _, u, _, _ in fake.calls), 1)

    def test_rate_limit_pause(self):
        fake = FakeReddit(remaining="2")
        src = api_source()
        with mock.patch.object(http, "request", side_effect=fake), \
                mock.patch("gta6digest.sources.reddit_api.time.sleep") as sleep:
            src.fetch()
            src.fetch()
        self.assertTrue(any(c.args[0] > 200 for c in sleep.call_args_list))

    def test_find_removed(self):
        children = [
            {"kind": "t3", "data": {"name": "t3_a", "author": "x", "selftext": "hi"}},
            {"kind": "t3", "data": {"name": "t3_b", "author": "[deleted]", "selftext": "[deleted]"}},
            {"kind": "t3", "data": {"name": "t3_c", "author": "y", "removed_by_category": "moderator"}},
        ]
        fake = FakeReddit(info_children=children)
        with mock.patch.object(http, "request", side_effect=fake):
            removed = api_source().find_removed(["t3_a", "t3_b", "t3_c", "t3_d"])
        self.assertEqual(sorted(removed), ["t3_b", "t3_c", "t3_d"])  # t3_d is gone entirely

    def test_missing_credentials(self):
        with self.assertRaises(ValueError):
            RedditApiSource("GTA6", "ua", ["new"], "", "", "", "")


class ClassifierTest(unittest.TestCase):
    def test_official_by_domain(self):
        c = CLS.classify(post("TRAILER 3 IS HERE!!!", link="https://www.rockstargames.com/newswire/x"))
        self.assertEqual((c.category, c.status), ("official", "official"))

    def test_find(self):
        self.assertEqual(CLS.classify(post("Easter egg I noticed in Trailer 3 gas station scene")).category,
                         "finds")

    def test_rumor_technical(self):
        c = CLS.classify(post("Rumor: GTA 6 PC version release date leaked, one year after"))
        self.assertEqual((c.category, c.status), ("technical", "rumor"))

    def test_meme(self):
        self.assertEqual(CLS.classify(post("Me waiting for the release be like (meme)")).category, "memes")

    def test_meme_flair(self):
        p = post("Funny NPC moment")
        p.flair = "Meme / Humor"
        self.assertEqual(CLS.classify(p).category, "memes")

    def test_business(self):
        self.assertEqual(CLS.classify(post("Take-Two earnings: GTA VI pre-orders break records")).category,
                         "business")

    def test_map(self):
        self.assertEqual(CLS.classify(post("New Vice City map comparison with real Miami")).category, "map")

    def test_spoiler(self):
        self.assertTrue(CLS.classify(post("Spoilers: what happens to Lucia at the ending")).spoiler)

    def test_debunked(self):
        self.assertEqual(CLS.classify(post("That map leak is fake, debunked")).status, "debunked")

    def test_theory(self):
        self.assertEqual(CLS.classify(post("Theory: Jason is an undercover cop")).status, "theory")

    def test_default(self):
        c = CLS.classify(post("How hyped are you all today?"))
        self.assertEqual((c.category, c.status), ("discussion", "none"))

    def test_insiders(self):
        cls = Classifier(["rockstargames.com"], insiders=["SomeInsider"])
        self.assertEqual(cls.classify(post("New info", "according to SomeInsider ...")).status, "insider")

    def test_status_upgrade(self):
        self.assertEqual(stronger_status("rumor", "official"), "confirmed")
        self.assertEqual(stronger_status("official", "rumor"), "official")
        self.assertEqual(stronger_status("none", "theory"), "theory")


class ClusteringTest(unittest.TestCase):
    def test_same_link(self):
        self.assertTrue(is_same_story("a", "b", "https://r.com/x/", "https://r.com/x"))

    def test_similar_titles(self):
        self.assertTrue(is_same_story("GTA 6 PC version release date leaked",
                                      "Rumor: GTA 6 PC version release date leaked, one year after consoles"))

    def test_different(self):
        self.assertFalse(is_same_story("Easter egg in gas station scene",
                                       "Take-Two earnings call highlights"))


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Storage(str(Path(self.tmp.name) / "t.db"))

    def tearDown(self):
        self.st.close()
        self.tmp.cleanup()

    def save(self, title, pid, link=None):
        p = post(title, pid=pid, link=link)
        return self.st.save_post(p, CLS.classify(p))

    def test_dedupe_and_cluster(self):
        new, s1 = self.save("GTA 6 PC version release date leaked", "1")
        self.assertTrue(new)
        new, _ = self.save("GTA 6 PC version release date leaked", "1")
        self.assertFalse(new)  # same post again is not new
        _, s2 = self.save("Rumor: GTA 6 PC version release date leaked, one year after consoles", "2")
        self.assertEqual(s1, s2)  # merged into one story
        self.assertEqual(self.st.stories_since(EPOCH)[0]["mentions"], 2)

    def test_rumor_confirmed_alert(self):
        self.save("GTA 6 PC version release date leaked", "1")
        self.st.mark_all_alerted()
        self.save("Rockstar confirms GTA 6 PC version release date", "2",
                  link="https://www.rockstargames.com/newswire/pc")
        alerts = self.st.stories_to_alert()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["status"], "confirmed")
        self.assertIn("rockstargames.com", alerts[0]["best_url"])

    def test_purge(self):
        old = post("Old post about the map", pid="old")
        old.published = datetime(2020, 1, 1, tzinfo=timezone.utc)
        self.st.save_post(old, CLS.classify(old))
        self.assertEqual(self.st.purge_older_than(30), 1)
        self.assertEqual(self.st.counts(), {"posts": 0, "stories": 0, "by_category": {}})

    def test_delete_only_post_removes_story(self):
        self.save("Easter egg in the gas station scene", "1")
        self.st.delete_post("test", "1")
        self.assertEqual(self.st.counts()["stories"], 0)

    def test_delete_one_of_two_keeps_story_with_other_title(self):
        self.save("GTA 6 PC version release date leaked", "1")
        self.save("Rumor: GTA 6 PC version release date leaked, one year after consoles", "2")
        self.st.delete_post("test", "1")
        story = self.st.stories_since(EPOCH)[0]
        self.assertEqual(story["mentions"], 1)
        self.assertTrue(story["title"].startswith("Rumor:"))  # deleted post's title is gone


class EndToEndTest(unittest.TestCase):
    def test_sources_to_digest(self):
        reddit = (FIX / "reddit_new.xml").read_bytes()
        news = (FIX / "news.xml").read_bytes()

        def fake_get(url, *a, **k):
            return reddit if "reddit.com" in url else news

        with mock.patch.object(http, "get", side_effect=fake_get), \
                tempfile.TemporaryDirectory() as tmp:
            st = Storage(str(Path(tmp) / "e.db"))
            sources = [RedditRssSource("GTA6", "test-agent", ["new"]),
                       NewsRssSource("Example", "https://example-games.com/feed", "test-agent",
                                     ["gta 6", "gta vi"])]
            for src in sources:
                for p in src.fetch():
                    st.save_post(p, CLS.classify(p))
            counts = st.counts()
            self.assertEqual(counts["posts"], 7)    # 5 reddit + 2 GTA news (headphones filtered out)
            self.assertEqual(counts["stories"], 5)  # duplicates merged
            console = html_to_console(build_digest(st.stories_since(EPOCH), 5, False, "Test"))
            self.assertIn("Official announcements", console)
            self.assertIn("×2", console)
            self.assertNotIn("Memes", console)  # memes hidden by default
            st.close()
        print("\n--- sample digest ---\n" + console)


class TelegramSplitTest(unittest.TestCase):
    def test_split(self):
        text = "\n".join("line %d " % i + "x" * 100 for i in range(200))
        parts = split_message(text)
        self.assertTrue(all(len(p) <= 4000 for p in parts))
        self.assertEqual("\n".join(parts), text)


if __name__ == "__main__":
    unittest.main()
