import json
import logging
import os
import random
import re
import threading
import time
import traceback

from datalayer.item_monitor import ItemMonitor
from managers.sources import make_client, SITES

NOTIFIED_LIMIT = 500
MAX_DESCRIPTIONS_PER_CYCLE = 10  # item pages opened per cycle when description filters are used
ERROR_SLEEP_TIME = 60


def _has_words(text, words):
    return any(w in text for w in words)


def filter_reason(item, listing):
    """None if the listing passes the title/price filters, otherwise a short reason."""
    title = listing.title.lower()
    if listing.is_sold:
        return "sold"
    if listing.is_pending:
        return "reserved"
    if item.days_since_listed and getattr(listing, 'created_at', None):
        if time.time() - listing.created_at > float(item.days_since_listed) * 86400:
            return f"older than {item.days_since_listed} day(s)"
    if listing.price is not None:
        if item.min_price and listing.price < float(item.min_price):
            return "below min price"
        if item.max_price and listing.price > float(item.max_price):
            return "above max price"
    if item.title_must_include and not _has_words(title, item.title_must_include):
        return "title missing required word"
    hit = next((w for w in item.title_exclude if w in title), None)
    if hit:
        return f'title contains "{hit}"'
    words = title.split()
    if words and words[0] in item.title_first_word_exclude:
        return f'title starts with "{words[0]}"'
    return None


def desc_reason(item, listing):
    """None if the description passes the description filters, otherwise a short reason."""
    desc = (listing.description or '').lower()
    if item.description_must_include and not _has_words(desc, item.description_must_include):
        return "description missing required word"
    hit = next((w for w in item.description_exclude if w in desc), None)
    if hit:
        return f'description contains "{hit}"'
    return None


class Worker:
    """Monitors one search. Runs in its own thread until stop_event is set.

    emit(event: dict) is called with status updates and found listings so a GUI
    (or the console runner) can show them.
    """

    def __init__(self, search_cfg, telegram=None, interval_seconds=300,
                 data_dir='data', stop_event=None, emit=None):
        self.logger = logging.getLogger(__name__)
        self._item = ItemMonitor.load_from_json(search_cfg)
        self.name = search_cfg.get('name') or self._item.search_query
        slug = re.sub(r'[^a-z0-9]+', '_', self._item.search_query.lower()).strip('_')
        self.id = search_cfg.get('id') or slug
        self._telegram = telegram
        self._interval = max(60, int(interval_seconds))
        self._seen_file = os.path.join(data_dir, f"seen_{self.id}.json")
        self._data_dir = data_dir
        self._stop = stop_event or threading.Event()
        self._emit_cb = emit
        self._seen = self._load_seen()
        self._total_new = 0

    # ---------- events ----------
    def _emit(self, **event):
        event.setdefault('type', 'status')
        event['id'] = self.id
        event['name'] = self.name
        if self._emit_cb:
            try:
                self._emit_cb(event)
            except Exception:
                pass

    # ---------- seen-listings persistence (survives restarts) ----------
    def _load_seen(self):
        try:
            with open(self._seen_file, encoding='utf-8') as f:
                return list(json.load(f))
        except (OSError, ValueError):
            return None  # None = first run, don't spam old listings

    def _save_seen(self):
        os.makedirs(self._data_dir, exist_ok=True)
        with open(self._seen_file, 'w', encoding='utf-8') as f:
            json.dump(self._seen[:NOTIFIED_LIMIT], f)

    def _mark_seen(self, listing_id):
        if listing_id not in self._seen:
            self._seen.insert(0, listing_id)
            self._seen = self._seen[:NOTIFIED_LIMIT]

    # ---------- filters ----------
    def _passes_title_and_price(self, listing):
        return filter_reason(self._item, listing) is None

    def _passes_description(self, listing):
        it = self._item
        desc = listing.description.lower()
        if it.description_must_include and not _has_words(desc, it.description_must_include):
            return False
        return not _has_words(desc, it.description_exclude)

    # ---------- one check ----------
    def _check(self, client, notify=True):
        self._emit(state='checking', message='Checking Facebook…')
        listings = client.search(self._item)
        if self._stop.is_set():
            return

        if self._seen is None:  # first ever run for this search
            self._seen = [l.id for l in listings]
            self._save_seen()
            self.logger.info(f"[{self.name}] first run: {len(listings)} existing listings marked as seen")
            self._emit(state='waiting', listings=len(listings), new=0, total_new=self._total_new,
                       last_check=time.time(),
                       message=f'First run - {len(listings)} existing listings saved, alerts start next check')
            return

        new_count = 0
        descriptions_fetched = 0
        for listing in listings:
            if self._stop.is_set():
                break
            if listing.id in self._seen:
                continue
            reason = filter_reason(self._item, listing)
            if reason:
                self.logger.info(f"[{self.name}] excluded ({reason}): {listing.title}")
                self._mark_seen(listing.id)
                continue

            if self._item.needs_description():
                if not listing.description and descriptions_fetched >= MAX_DESCRIPTIONS_PER_CYCLE:
                    continue  # check it next cycle, don't mark as seen
                listing.description = client.fetch_description(listing)
                descriptions_fetched += 1
                reason = desc_reason(self._item, listing)
                if reason:
                    self.logger.info(f"[{self.name}] excluded ({reason}): {listing.title}")
                    self._mark_seen(listing.id)
                    continue

            self._mark_seen(listing.id)
            new_count += 1
            self._total_new += 1
            self.logger.info(f"[{self.name}] NEW: {listing.title} - {listing.formatted_price}")
            self._emit(type='found', listing={
                'id': listing.id, 'title': listing.title, 'price': listing.formatted_price
                or (f"{listing.price:g} {listing.currency}" if listing.price is not None else ''),
                'location': listing.location, 'url': listing.url, 'image': listing.image_url,
                'search': self.name, 'found_at': time.time(),
                'shipping': listing.allows_shipping, 'description': listing.description[:300],
                'site': self._item.site})
            if notify and self._telegram:
                try:
                    self._telegram.send_listing(listing, f"{self.name} · {SITES.get(self._item.site, '')}")
                except Exception as e:
                    self.logger.error(f"[{self.name}] Telegram send failed: {e}")

        self._save_seen()
        msg = f'{len(listings)} listings checked, {new_count} new'
        if not listings:
            msg = f'{SITES.get(self._item.site, "The site")} returned 0 listings - try a wider search'
            self.logger.warning(f"[{self.name}] {msg}")
        self._emit(state='waiting', listings=len(listings), new=new_count, total_new=self._total_new,
                   last_check=time.time(), message=msg)

    # ---------- main loop ----------
    def run(self):
        while not self._stop.is_set():
            client = None
            try:
                self._emit(state='starting', message='Starting browser…')
                client = make_client(self._item)
                while not self._stop.is_set():
                    self._check(client)
                    wait = self._interval + random.randint(0, 30)  # jitter looks less bot-like
                    self._emit(next_check=time.time() + wait)
                    if self._stop.wait(wait):
                        break
            except Exception as e:
                self.logger.error(f"[{self.name}] crashed: {e}\n" +
                                  ''.join(traceback.format_exception(None, e, e.__traceback__)))
                self._emit(state='error', message=f'Error: {e} - retrying in 1 min',
                           next_check=time.time() + ERROR_SLEEP_TIME)
                self._stop.wait(ERROR_SLEEP_TIME)
            finally:
                if client:
                    try:
                        client.close()
                    except Exception:
                        pass
        self._emit(state='stopped', message='Stopped', next_check=None)
