import logging
import time

import requests

from datalayer.listing import Listing

USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36')

# our condition names -> Vinted status ids
STATUS_IDS = {
    'new': [6, 1],              # new with tags, new without tags
    'as_good_as_new': [2],      # very good
    'good': [3],
    'fair': [4],                # satisfactory
    'has_given_it_all': [4],
}

DOMAINS = {"Spain": "es", "Italy": "it", "Portugal": "pt", "France": "fr", "Germany": "de",
           "Belgium": "be", "Netherlands": "nl", "Austria": "at", "Poland": "pl", "UK": "co.uk"}


class VintedError(RuntimeError):
    pass


class VintedClient:
    """Uses Vinted's own catalogue API (the one the website uses).
    Vinted needs an anonymous session cookie, which we get by opening the home page first."""

    def __init__(self, domain='es'):
        self.logger = logging.getLogger(__name__)
        self.domain = domain or 'es'
        self.base = f"https://www.vinted.{self.domain}"
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': USER_AGENT,
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
            'Referer': self.base + '/',
        })
        self._has_cookie = False
        self.location_applied = True

    def _get_cookie(self):
        r = self._session.get(self.base + '/', headers={'Accept': 'text/html'}, timeout=20)
        if r.status_code >= 400:
            raise VintedError(f"Vinted refused the connection (HTTP {r.status_code})")
        self._has_cookie = True

    def build_params(self, item):
        params = [('search_text', item.search_query), ('order', 'newest_first'),
                  ('per_page', '96'), ('page', '1')]
        if item.min_price:
            params.append(('price_from', item.min_price))
        if item.max_price:
            params.append(('price_to', item.max_price))
        if item.min_price or item.max_price:
            params.append(('currency', 'EUR'))
        for sid in STATUS_IDS.get(item.condition, []):
            params.append(('status_ids[]', str(sid)))
        return params

    def search(self, item):
        if not self._has_cookie:
            self._get_cookie()
        url = self.base + '/api/v2/catalog/items'
        params = self.build_params(item)
        data = None
        for attempt in range(3):
            try:
                r = self._session.get(url, params=params, timeout=20)
                if r.status_code in (401, 403):
                    self.logger.info("Vinted session expired, getting a new one")
                    self._session.cookies.clear()
                    self._get_cookie()
                    raise VintedError(f"HTTP {r.status_code}")
                if r.status_code == 429:
                    raise VintedError("Vinted says too many requests - raise the check interval")
                r.raise_for_status()
                data = r.json()
                break
            except (requests.RequestException, ValueError, VintedError) as e:
                self.logger.warning(f"Vinted request failed ({e}), retry {attempt + 1}/3")
                time.sleep(3 * (attempt + 1))
        if data is None:
            raise VintedError("Couldn't get results from Vinted (it may be blocking automated requests)")
        items = data.get('items')
        if not isinstance(items, list):
            raise VintedError("Unexpected reply from Vinted (the API may have changed)")
        return [l for l in (self._parse(i) for i in items) if l]

    def _parse(self, it):
        if not it.get('id') or it.get('title') is None:
            return None
        price, currency = it.get('price'), it.get('currency') or 'EUR'
        if isinstance(price, dict):
            currency = price.get('currency_code') or currency
            price = price.get('amount')
        try:
            price = float(price)
        except (TypeError, ValueError):
            price = None
        photo = it.get('photo') or {}
        image = photo.get('url')
        for th in photo.get('thumbnails') or []:
            if th.get('type') in ('thumb310x430', 'thumb310'):
                image = th.get('url') or image
        created = (photo.get('high_resolution') or {}).get('timestamp')
        details = " · ".join(str(x) for x in (it.get('brand_title'), it.get('size_title'),
                                               it.get('status')) if x)
        url = it.get('url') or f"{self.base}/items/{it['id']}"
        if url.startswith('/'):
            url = self.base + url
        user = it.get('user') or {}
        return Listing(
            id=f"v{it['id']}", title=it.get('title'), description=details, price=price, currency=currency,
            location=f"Vinted {self.domain.upper()}" + (f" · {user.get('login')}" if user.get('login') else ""),
            allows_shipping=True, slug=str(it['id']), image_url=image,
            is_reserved=bool(it.get('is_reserved')), is_sold=bool(it.get('is_closed')),
            created_at=created, url=url, site='vinted')

    def fetch_description(self, listing):
        return listing.description  # brand · size · condition (search results have no full description)

    def close(self):
        self._session.close()
