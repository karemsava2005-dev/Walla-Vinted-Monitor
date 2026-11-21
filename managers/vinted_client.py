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
        self._token = ''
        self._anon_id = ''
        self.location_applied = True

    def _get_cookie(self):
        r = self._session.get(self.base + '/', headers={'Accept': 'text/html'}, timeout=20)
        if r.status_code >= 400:
            raise VintedError(f"Vinted refused the connection (HTTP {r.status_code})")
        self._anon_id = r.headers.get('x-anon-id') or r.headers.get('X-Anon-Id') or ''
        self._token = self._session.cookies.get('access_token_web') or ''
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
            params.append(('attribute_ids[status]', str(sid)))
        return params  # empty values are never sent: the new API answers 400 to blank ones

    # ---- new catalogue API (Vinted retired /api/v2/catalog/items and now answers 404) ----
    def _search_api(self, item):
        url = f"https://api.vinted.{self.domain}/svc-catalogue/items"
        headers = {'Origin': self.base, 'Referer': self.base + '/'}
        if self._token:
            headers['Authorization'] = f'Bearer {self._token}'
        if self._anon_id:
            headers['x-anon-id'] = self._anon_id
        r = self._session.get(url, params=self.build_params(item), headers=headers, timeout=20)
        if r.status_code in (401, 403):
            self._session.cookies.clear()
            self._get_cookie()
            raise VintedError(f"HTTP {r.status_code}")
        if r.status_code >= 400:
            raise VintedError(f"HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        items = data.get('items')
        if items is None and isinstance(data.get('data'), dict):
            items = data['data'].get('items')
        if not isinstance(items, list):
            raise VintedError("Unexpected reply from Vinted (keys: %s)" % list(data)[:8])
        return [l for l in (self._parse(i) for i in items) if l]

    # ---- fallback: read the public catalogue web page (embedded ld+json list) ----
    def _search_page(self, item):
        import json as _json
        import re
        from urllib.parse import urlencode
        q = {'search_text': item.search_query, 'order': 'newest_first'}
        if item.min_price:
            q['price_from'] = item.min_price
        if item.max_price:
            q['price_to'] = item.max_price
        r = self._session.get(f"{self.base}/catalog?{urlencode(q)}", headers={'Accept': 'text/html'}, timeout=25)
        if r.status_code >= 400:
            raise VintedError(f"HTTP {r.status_code} on the catalogue page")
        out = []
        for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', r.text, re.S):
            try:
                data = _json.loads(block)
            except ValueError:
                continue
            for d in (data if isinstance(data, list) else [data]):
                elements = d.get('itemListElement') if isinstance(d, dict) else None
                for el in elements or []:
                    it = el.get('item', el) if isinstance(el, dict) else {}
                    url = it.get('url') or ''
                    m = re.search(r'/items/(\d+)', url)
                    if not m:
                        continue
                    offer = it.get('offers') or {}
                    if isinstance(offer, list):
                        offer = offer[0] if offer else {}
                    try:
                        price = float(offer.get('price'))
                    except (TypeError, ValueError):
                        price = None
                    img = it.get('image')
                    img = img[0] if isinstance(img, list) and img else img
                    out.append(Listing(
                        id=f"v{m.group(1)}", title=it.get('name'), description=it.get('description') or '',
                        price=price, currency=offer.get('priceCurrency') or 'EUR',
                        location=f"Vinted {self.domain.upper()}", allows_shipping=True, slug=m.group(1),
                        image_url=img if isinstance(img, str) else None, url=url, site='vinted'))
        if not out:
            raise VintedError("No listings found on the catalogue page")
        return out

    def search(self, item):
        if not self._has_cookie:
            self._get_cookie()
        last = None
        for attempt in range(2):
            try:
                return self._search_api(item)
            except (requests.RequestException, ValueError, VintedError) as e:
                last = e
                self.logger.warning(f"Vinted API failed ({e}), retry {attempt + 1}/2")
                time.sleep(2 * (attempt + 1))
        try:
            self.logger.warning("Vinted API unavailable, trying the catalogue web page instead")
            return self._search_page(item)
        except (requests.RequestException, ValueError, VintedError) as e:
            raise VintedError(f"Couldn't get results from Vinted: API said \"{last}\", page said \"{e}\"")

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