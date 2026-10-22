"""Тесты. Запуск: python3 -m unittest -v"""
from __future__ import annotations

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
from gta6digest.sources import NewsRssSource, RedditRssSource  # noqa: E402
from gta6digest.sources.reddit_rss import parse_reddit_feed  # noqa: E402
from gta6digest.storage import Storage  # noqa: E402
from gta6digest.telegram import split_message  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
CLS = Classifier(["rockstargames.com", "take2games.com"])


def post(title, text="", link=None, pid=None):
    return Post(source="test", external_id=pid or title, title=title, url="https://x/" + title[:5],
                published=datetime.now(timezone.utc), text=text, link_url=link)


class RedditRssTest(unittest.TestCase):
    def setUp(self):
        self.posts = parse_reddit_feed((FIX / "reddit_new.xml").read_bytes())

    def test_parses_all(self):
        self.assertEqual(len(self.posts), 5)

    def test_no_usernames_anywhere(self):
        # обещание в заявке: ники не сохраняем
        for p in self.posts:
            blob = " ".join(str(v) for v in vars(p).values())
            self.assertNotIn("user_", blob, p)
            self.assertNotIn("/u/", blob, p)

    def test_external_link(self):
        by_id = {p.external_id: p for p in self.posts}
        self.assertIn("rockstargames.com", by_id["t3_aaa111"].link_url)
        self.assertIsNone(by_id["t3_bbb222"].link_url)  # текстовый пост

    def test_text_extracted(self):
        by_id = {p.external_id: p for p in self.posts}
        self.assertIn("Epsilon poster", by_id["t3_bbb222"].text)


class ClassifierTest(unittest.TestCase):
    def test_official_by_domain(self):
        c = CLS.classify(post("TRAILER 3 IS HERE!!!", link="https://www.rockstargames.com/newswire/x"))
        self.assertEqual((c.category, c.status), ("official", "official"))

    def test_find(self):
        c = CLS.classify(post("Easter egg I noticed in Trailer 3 gas station scene"))
        self.assertEqual(c.category, "finds")

    def test_rumor_technical(self):
        c = CLS.classify(post("Rumor: GTA 6 PC version release date leaked, one year after"))
        self.assertEqual(c.status, "rumor")
        self.assertEqual(c.category, "technical")

    def test_meme(self):
        self.assertEqual(CLS.classify(post("Me waiting for the release be like (meme)")).category, "memes")

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

    def test_dedupe_and_cluster(self):
        p1 = post("GTA 6 PC version release date leaked", pid="1")
        new, s1 = self.st.save_post(p1, CLS.classify(p1))
        self.assertTrue(new)
        new, _ = self.st.save_post(p1, CLS.classify(p1))
        self.assertFalse(new)  # тот же пост второй раз — не новый
        p2 = post("Rumor: GTA 6 PC version release date leaked, one year after consoles", pid="2")
        _, s2 = self.st.save_post(p2, CLS.classify(p2))
        self.assertEqual(s1, s2)  # склеилось в одну историю
        row = self.st.stories_since(datetime(2000, 1, 1, tzinfo=timezone.utc))[0]
        self.assertEqual(row["mentions"], 2)

    def test_rumor_confirmed_alert(self):
        p1 = post("GTA 6 PC version release date leaked", pid="1")
        self.st.save_post(p1, CLS.classify(p1))
        self.st.mark_all_alerted()
        p2 = post("Rockstar confirms GTA 6 PC version release date", pid="2",
                  link="https://www.rockstargames.com/newswire/pc")
        self.st.save_post(p2, CLS.classify(p2))
        alerts = self.st.stories_to_alert()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["status"], "confirmed")
        self.assertIn("rockstargames.com", alerts[0]["best_url"])

    def test_purge(self):
        old = post("Old post about the map", pid="old")
        old.published = datetime(2020, 1, 1, tzinfo=timezone.utc)
        self.st.save_post(old, CLS.classify(old))
        self.assertEqual(self.st.purge_older_than(30), 1)
        self.assertEqual(self.st.counts()["posts"], 0)


class EndToEndTest(unittest.TestCase):
    def test_sources_to_digest(self):
        fixtures = {"reddit": (FIX / "reddit_new.xml").read_bytes(),
                    "example": (FIX / "news.xml").read_bytes()}

        def fake_get(url, *a, **k):
            return fixtures["reddit"] if "reddit.com" in url else fixtures["example"]

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
            self.assertEqual(counts["posts"], 7)  # 5 reddit + 2 новости про GTA (наушники отсеяны)
            # Два поста про трейлер с одной ссылкой + утечка PC с Reddit и сайта склеились
            self.assertEqual(counts["stories"], 5)
            text = build_digest(st.stories_since(datetime(2000, 1, 1, tzinfo=timezone.utc)),
                                5, False, "Тест")
            console = html_to_console(text)
            self.assertIn("Официальные анонсы", console)
            self.assertIn("×2", console)
            self.assertNotIn("Мемы", console)  # мемы скрыты по умолчанию
            st.close()
        print("\n--- пример дайджеста ---\n" + console)


class TelegramSplitTest(unittest.TestCase):
    def test_split(self):
        text = "\n".join("строка %d " % i + "x" * 100 for i in range(200))
        parts = split_message(text)
        self.assertTrue(all(len(p) <= 4000 for p in parts))
        self.assertEqual("\n".join(parts), text)


if __name__ == "__main__":
    unittest.main()
