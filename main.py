"""GTA 6 News Digest — entry point.

Commands:
  python3 main.py run            — run continuously (collect every N minutes + daily digest)
  python3 main.py once           — collect once and print the digest
  python3 main.py digest         — print the digest from the database (no downloads)
  python3 main.py digest --send  — send the digest to Telegram
  python3 main.py sync-deletions — check now for posts deleted on Reddit (API mode)
  python3 main.py stats          — what has been collected so far
  python3 main.py chat-id        — find your Telegram chat_id
  python3 main.py test-telegram  — send a test message
"""
from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler

from gta6digest import config as config_mod
from gta6digest.app import App
from gta6digest.classifier import CATEGORIES
from gta6digest.digest import html_to_console
from gta6digest.telegram import Telegram


def setup_logging(log_path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    file = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file.setFormatter(fmt)
    root.addHandler(console)
    root.addHandler(file)


def main() -> None:
    ap = argparse.ArgumentParser(description="GTA 6 News Digest")
    ap.add_argument("command", choices=["run", "once", "digest", "sync-deletions", "stats",
                                        "chat-id", "test-telegram"])
    ap.add_argument("--config", default="config.ini")
    ap.add_argument("--hours", type=int, default=24, help="digest period in hours")
    ap.add_argument("--send", action="store_true", help="send the digest to Telegram")
    args = ap.parse_args()

    cfg = config_mod.load(args.config)
    setup_logging(cfg.log_path)

    if args.command == "chat-id":
        if not cfg.telegram_token:
            sys.exit("Put your bot token into config.ini first")
        ids = Telegram.find_chat_ids(cfg.telegram_token)
        if not ids:
            print("No chats found. Send any message to your bot and run this command again.")
        for i in ids:
            print("chat_id:", i)
        return

    app = App(cfg)

    if args.command == "test-telegram":
        if not app.telegram:
            sys.exit("Telegram is not configured: check enabled, token and chat_id in config.ini")
        app.telegram.send("✅ GTA 6 Digest is up and running!")
        print("Sent.")
    elif args.command == "run":
        app.run_forever()
    elif args.command == "once":
        stats = app.collect()
        print(f"\nNew: {stats['new']}, updated: {stats['updated']}, deleted: {stats['deleted']}, "
              f"source errors: {stats['errors']}\n")
        print(html_to_console(app.make_digest(args.hours)))
    elif args.command == "digest":
        text = app.send_digest(args.hours) if args.send else app.make_digest(args.hours)
        print(html_to_console(text))
    elif args.command == "sync-deletions":
        n = app.sync_deletions(force=True)
        print(f"Removed {n} posts deleted at the source.")
    elif args.command == "stats":
        c = app.storage.counts()
        print(f"Posts: {c['posts']}, stories: {c['stories']}")
        for key, label in CATEGORIES.items():
            if c["by_category"].get(key):
                print(f"  {label}: {c['by_category'][key]}")


if __name__ == "__main__":
    main()
