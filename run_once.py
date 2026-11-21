"""One pass over all searches, then exit. Meant to be started by GitHub Actions every few minutes.

Searches come from the SEARCHES_JSON secret (or a local searches.json when testing).
Telegram settings come from TELEGRAM_TOKEN and TELEGRAM_CHANNEL.
Already-seen listings are kept in ./data (the workflow caches that folder between runs).
"""
import json
import logging
import os
import sys

from managers.sources import make_client
from managers.telegram_manager import TelegramManager
from managers.worker import Worker


def load_searches():
    raw = os.environ.get('SEARCHES_JSON', '').strip()
    if raw:
        return json.loads(raw)
    with open('searches.json', encoding='utf-8') as f:
        return json.load(f)


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    for noisy in ("httpx", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    searches = [s for s in load_searches() if s.get('enabled', True)]
    token, channel = os.environ.get('TELEGRAM_TOKEN'), os.environ.get('TELEGRAM_CHANNEL')
    telegram = TelegramManager(token, channel) if token and channel else None
    if not telegram:
        logging.warning("No Telegram settings found: alerts will only appear in this log.")

    failures = 0
    for s in searches:
        w = Worker(s, telegram=telegram, data_dir='data')
        client = None
        try:
            client = make_client(w._item)
            w._check(client)
        except Exception as e:  # one broken search must not stop the others
            failures += 1
            logging.error(f"[{w.name}] failed: {e}")
        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass
    # Only fail the run if every search failed, so you get GitHub's failure email for real outages.
    sys.exit(1 if searches and failures == len(searches) else 0)


if __name__ == '__main__':
    main()
