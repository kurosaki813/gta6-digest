"""GTA 6 News Digest — точка входа.

Команды:
  python3 main.py run            — работать постоянно (сбор каждые N минут + дайджест)
  python3 main.py once           — один сбор и вывести дайджест в консоль
  python3 main.py digest         — показать дайджест из базы (ничего не скачивает)
  python3 main.py digest --send  — отправить дайджест в Telegram
  python3 main.py stats          — сколько всего собрано
  python3 main.py chat-id        — узнать свой chat_id для Telegram
  python3 main.py test-telegram  — отправить тестовое сообщение
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
    ap.add_argument("command", choices=["run", "once", "digest", "stats", "chat-id",
                                        "test-telegram"])
    ap.add_argument("--config", default="config.ini")
    ap.add_argument("--hours", type=int, default=24, help="за сколько часов дайджест")
    ap.add_argument("--send", action="store_true", help="отправить дайджест в Telegram")
    args = ap.parse_args()

    cfg = config_mod.load(args.config)
    setup_logging(cfg.log_path)

    if args.command == "chat-id":
        if not cfg.telegram_token:
            sys.exit("Сначала впиши token бота в config.ini")
        ids = Telegram.find_chat_ids(cfg.telegram_token)
        if not ids:
            print("Чатов не найдено. Напиши своему боту любое сообщение и запусти команду снова.")
        for i in ids:
            print("chat_id:", i)
        return

    app = App(cfg)

    if args.command == "test-telegram":
        if not app.telegram:
            sys.exit("Telegram не настроен: проверь enabled, token и chat_id в config.ini")
        app.telegram.send("✅ GTA 6 Digest на связи!")
        print("Отправлено.")
    elif args.command == "run":
        app.run_forever()
    elif args.command == "once":
        stats = app.collect()
        print(f"\nНовых: {stats['new']}, обновлено: {stats['updated']}, "
              f"ошибок источников: {stats['errors']}\n")
        print(html_to_console(app.make_digest(args.hours)))
    elif args.command == "digest":
        text = app.send_digest(args.hours) if args.send else app.make_digest(args.hours)
        print(html_to_console(text))
    elif args.command == "stats":
        c = app.storage.counts()
        print(f"Постов: {c['posts']}, историй: {c['stories']}")
        for key, label in CATEGORIES.items():
            if c["by_category"].get(key):
                print(f"  {label}: {c['by_category'][key]}")


if __name__ == "__main__":
    main()
