"""One pass over all searches, then exit. Meant to be started by GitHub Actions every few minutes.

Searches come from the SEARCHES_JSON secret (or a local searches.json when testing).
Telegram settings come from TELEGRAM_TOKEN and TELEGRAM_CHANNEL.
Already-seen listings are kept in ./data (the workflow caches that folder between runs).
"""
import json
import logging
import os
import sys
import time

from managers.geocode import geocode
from managers.sources import make_client
from managers.telegram_manager import TelegramManager
from managers.worker import Worker


class OnceNotifier:
    """Wraps Telegram so a listing found by several searches is only sent once (remembered across runs)."""
    PATH = os.path.join('data', 'notified.json')

    def __init__(self, telegram):
        self.telegram = telegram
        try:
            with open(self.PATH, encoding='utf-8') as f:
                self.ids = json.load(f)
        except (OSError, ValueError):
            self.ids = []
        self._set = set(self.ids)

    def send_listing(self, listing, search_name=None):
        if listing.id in self._set:
            logging.info(f"skip duplicate (already sent by another search): {listing.title}")
            return
        self.telegram.send_listing(listing, search_name)
        self._set.add(listing.id)
        self.ids.append(listing.id)

    def save(self):
        os.makedirs('data', exist_ok=True)
        with open(self.PATH, 'w', encoding='utf-8') as f:
            json.dump(self.ids[-5000:], f)

    def __getattr__(self, name):
        return getattr(self.telegram, name)


def load_searches():
    """searches.json in the repo is the main list (easy to edit). The SEARCHES_JSON secret is only a fallback."""
    if os.path.exists('searches.json'):
        with open('searches.json', encoding='utf-8') as f:
            return json.load(f)
    raw = os.environ.get('SEARCHES_JSON', '').strip()
    if raw:
        return json.loads(raw)
    raise SystemExit("No searches found: add searches.json to the repo.")


def resolve_locations(searches):
    """Wallapop wants coordinates. If a search has a place name ("location") but no coordinates,
    look the place up once (OpenStreetMap) and remember it in data/geo.json."""
    path = os.path.join('data', 'geo.json')
    try:
        with open(path, encoding='utf-8') as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    for s in searches:
        place = str(s.get('location', '')).strip()
        if s.get('site', 'wallapop') != 'wallapop' or not place or s.get('latitude'):
            continue
        if place not in cache:
            try:
                lat, lng, label = geocode(place)
                cache[place] = [lat, lng, label]
                logging.info(f'Location "{place}" -> {lat}, {lng} ({label})')
            except Exception as e:
                logging.error(f'Could not find location "{place}": {e}. Searching without a location.')
                continue
        s['latitude'], s['longitude'] = str(cache[place][0]), str(cache[place][1])
    os.makedirs('data', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cache, f)


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    for noisy in ("httpx", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    searches = [s for s in load_searches() if s.get('enabled', True)]
    resolve_locations(searches)
    token, channel = os.environ.get('TELEGRAM_TOKEN'), os.environ.get('TELEGRAM_CHANNEL')
    telegram = TelegramManager(token, channel) if token and channel else None
    notifier = OnceNotifier(telegram) if telegram else None
    if not telegram:
        logging.warning("No Telegram settings found: alerts will only appear in this log.")

    # Optional "every_min" per search (e.g. job boards every 30 min instead of every run).
    stamp_path = os.path.join('data', 'last_run.json')
    try:
        with open(stamp_path, encoding='utf-8') as f:
            stamps = json.load(f)
    except (OSError, ValueError):
        stamps = {}
    now = time.time()
    due = []
    for s in searches:
        key = s.get('id') or f"{s.get('site')}:{s.get('search_query')}"
        every = float(s.get('every_min', 0) or 0) * 60
        if every and now - stamps.get(key, 0) < every - 60:
            continue
        stamps[key] = now
        due.append(s)
    os.makedirs('data', exist_ok=True)
    with open(stamp_path, 'w', encoding='utf-8') as f:
        json.dump(stamps, f)
    searches = due

    failures = 0
    for s in searches:
        w = Worker(s, telegram=notifier, data_dir='data')
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
    if notifier:
        notifier.save()
    # Only fail the run if every search failed, so you get GitHub's failure email for real outages.
    sys.exit(1 if searches and failures == len(searches) else 0)


if __name__ == '__main__':
    main()
