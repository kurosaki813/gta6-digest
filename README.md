# GTA 6 News Digest

A personal, non-commercial tool that keeps track of Grand Theft Auto VI news. It reads posts from r/GTA6 and articles from gaming news sites, sorts them into topics, merges duplicates and sends a private daily digest to my own Telegram chat.

No third-party packages: only Python 3.9+ is required.

## Reddit data handling

This project only **reads** public posts from a single subreddit (r/GTA6). These rules are built into the code, and the matching places are marked with `PRIVACY`, `RATE LIMITS`, `RETENTION` or `DELETION SYNC` comments.

| Rule | Where it is enforced |
|---|---|
| **Read-only.** No posting, commenting, voting or messaging. The only non-GET request is the OAuth token request. | `sources/reddit_api.py`, test `test_read_only_and_user_agent` |
| **No usernames are stored.** There is no author field in the data model or the database. The `author` field is read only to detect deleted posts and is then discarded. | `models.py`, `storage.py`, `reddit_api.parse_post`, `reddit_rss._strip_author_trailer`, test `test_no_usernames_anywhere` |
| **No user profiling.** Posts are classified by topic only; nothing is inferred about the people who wrote them. | `classifier.py` |
| **Deleted and removed posts are deleted locally.** Every 6 hours stored posts are re-checked via `/api/info`, and posts that were deleted by their author or removed by moderators are removed from the database. | `App.sync_deletions`, `RedditApiSource.find_removed`, `Storage.delete_post` |
| **Limited retention.** Posts older than `retention_days` (default 14, hard cap 30) are deleted every cycle. | `Storage.purge_older_than`, `config.py` |
| **Rate limits are respected.** One poll every 20 minutes (minimum 15), at least 1 second between requests, the `X-Ratelimit-*` headers are honoured and 429 responses are retried with back-off. Expected usage is well under 500 requests per day. | `RedditApiSource._wait_for_slot`, `http.request` |
| **Identifiable User-Agent.** `gta6-digest/<version> by u/<app account>`. | `config.ini` → `user_agent` |
| **No third parties.** Classification is rule-based and local. Reddit data is not sent to any external service, not used to train models, not sold or shared. | `classifier.py` |
| **Private output.** The digest goes to one private Telegram chat and is not published anywhere. | `telegram.py` |

## Quick start (macOS / Linux)

```bash
cd gta6-digest
cp config.example.ini config.ini
python3 main.py once
```

`once` runs one collection cycle and prints the digest to the console.

### Reddit modes

- `mode = rss` (default) works without an API key. Reddit retires RSS feeds on 2026-11-13.
- `mode = api` uses the official Data API. Create a "script" app at https://www.reddit.com/prefs/apps after access is approved, then fill in `client_id`, `client_secret`, `username` and `password` in `config.ini`. Deletion sync only works in this mode.

### Telegram

1. Message @BotFather in Telegram → `/newbot` → copy the token.
2. Put the token into `config.ini` (`[telegram]` → `token`).
3. Send any message to your bot.
4. Run `python3 main.py chat-id` and copy the number into `chat_id`.
5. Set `enabled = true`.
6. Run `python3 main.py test-telegram`. You should receive "GTA 6 Digest is up and running!".

### Running continuously

```bash
python3 main.py run
```

Every 20 minutes it collects new posts and sends official news and confirmed rumors immediately. Once a day (10:00 by default) it sends the digest. Stop it with Ctrl+C. The log is written to `data/parser.log`.

To keep it running after closing the terminal:

```bash
nohup python3 main.py run > /dev/null 2>&1 &
```

## Commands

| Command | What it does |
|---|---|
| `python3 main.py run` | run continuously |
| `python3 main.py once` | one collection cycle + digest in the console |
| `python3 main.py digest` | print the digest from the database |
| `python3 main.py digest --send` | send the digest to Telegram |
| `python3 main.py digest --hours 72` | digest for the last 3 days |
| `python3 main.py sync-deletions` | check for deleted posts right now (API mode) |
| `python3 main.py stats` | counts by category |
| `python3 main.py chat-id` | find your Telegram chat_id |
| `python3 main.py test-telegram` | send a test message |
| `python3 -m unittest` | run the tests |

## How it works

```
sources ──► classifier ──► SQLite ──► duplicate merging ──► digest / alerts
                              ▲
                deletion sync + retention purge
```

- `gta6digest/sources/`: every source implements the `Source` interface (`fetch()`, optional `find_removed()`).
  - `reddit_api.py`: official Data API (OAuth script app, read-only).
  - `reddit_rss.py`: RSS fallback, no key needed.
  - `news_rss.py`: gaming news sites, only GTA 6 articles are kept.
- `classifier.py`: rules for topic, reliability status and spoiler flag. Add words to `KEYWORDS` to tune it.
- `clustering.py`: merges posts about the same news into one "story".
- `storage.py`: the database, retention and deletion handling.
- `digest.py`, `telegram.py`: formatting and delivery.

### Topics

Official announcements · Story & characters · Map & locations · Gameplay & mechanics · Player finds · Technical · Online · Reviews & impressions · Business & sales · Discussion · Memes (hidden by default)

### Reliability statuses

✅ official · ✅ rumor confirmed · ❌ debunked · 🕵️ insider · ❓ rumor · 💭 theory

When a post linking to rockstargames.com joins a story that started as a rumor, the story becomes "rumor confirmed" and an alert is sent.

## License

MIT, see [LICENSE](LICENSE).
