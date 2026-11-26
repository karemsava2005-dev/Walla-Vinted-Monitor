"""Subito.it (Italy's biggest second-hand site). Reads the listings embedded in the public search page
(__NEXT_DATA__ -> props.pageProps.initialState.items.originalList, ~30 ads per page).
Subito uses bot protection; curl_cffi (Chrome fingerprint) is used when installed, plain requests otherwise.
From data-centre servers like GitHub it may still be refused (HTTP 403)."""
import json
import random
import time
import logging
import re
from urllib.parse import urlencode

from datalayer.listing import Listing

try:
    from curl_cffi import requests as creq
    _HAVE_CFFI = True
except ImportError:  # pragma: no cover
    import requests as creq
    _HAVE_CFFI = False


_LAST = 0.0


class SubitoError(Exception):
    pass


def _dig(d, *path):
    for p in path:
        if isinstance(d, dict):
            d = d.get(p)
        elif isinstance(d, list) and isinstance(p, int) and len(d) > p:
            d = d[p]
        else:
            return None
    return d


class SubitoClient:
    BASE = "https://www.subito.it"

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        kw = {'impersonate': 'chrome'} if _HAVE_CFFI else {}
        self.s = creq.Session(**kw)
        self.s.headers.update({'Accept-Language': 'it-IT,it;q=0.9,en;q=0.8'})
        if not _HAVE_CFFI:
            self.s.headers['User-Agent'] = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                                            '(KHTML, like Gecko) Chrome/131.0 Safari/537.36')

    def build_url(self, item):
        # e.g. region "lazio", province "roma", category "informatica" or "arredamento-casalinghi" or "usato"
        region = getattr(item, 'subito_region', 'lazio') or 'lazio'
        province = getattr(item, 'subito_province', 'roma') or ''
        cat = getattr(item, 'subito_category', 'usato') or 'usato'
        path = f"/annunci-{region}/vendita/{cat}/" + (f"{province}/" if province else "")
        q = {'q': item.search_query, 'order': 'datedesc'}
        if item.min_price:
            q['ps'] = item.min_price
        if item.max_price:
            q['pe'] = item.max_price
        return self.BASE + path + '?' + urlencode(q)

    def search(self, item):
        global _LAST
        url = self.build_url(item)
        wait = _LAST + random.uniform(3, 6) - time.time()   # be gentle: a few seconds between searches
        if wait > 0:
            time.sleep(wait)
        r = self.s.get(url, timeout=25)
        _LAST = time.time()
        if r.status_code != 200:
            raise SubitoError(f"Subito answered HTTP {r.status_code} (403 = blocked by bot protection)")
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
        if not m:
            raise SubitoError("Subito page had no listing data (probably a bot check page)")
        data = json.loads(m.group(1))
        lst = _dig(data, 'props', 'pageProps', 'initialState', 'items', 'originalList')
        if lst is None:
            lst = _dig(data, 'props', 'pageProps', 'initialState', 'items', 'list') or []
        out = [l for l in (self._parse(e) for e in lst) if l]
        if not out:
            self.logger.info(f"Subito returned no ads for {url}")
        return out

    def _parse(self, e):
        it = e.get('item', e) if isinstance(e, dict) else None
        if not isinstance(it, dict):
            return None
        urn = str(it.get('urn') or it.get('id') or '')
        m = re.search(r'(\d{6,})', urn)
        url = _dig(it, 'urls', 'default') or it.get('url') or ''
        if not m:
            m = re.search(r'-(\d{6,})\.htm', url)
        if not m:
            return None
        aid = m.group(1)
        price = None
        pv = _dig(it, 'features', '/price', 'values', 0, 'key')
        if pv is None:
            pv = it.get('price')
        try:
            price = float(str(pv).replace('€', '').replace('.', '').replace(',', '.').strip()) if pv not in (None, '') else None
        except ValueError:
            price = None
        town = _dig(it, 'geo', 'town', 'value') or _dig(it, 'geo', 'city', 'value') or ''
        img = _dig(it, 'images', 0, 'cdnBaseUrl') or _dig(it, 'images', 0, 'url')
        if img and 'rule=' not in img and 'cdnBaseUrl' in json.dumps(it.get('images', [{}])[0]):
            img = img + '?rule=gallery-desktop-1x-auto'
        shipping = bool(_dig(it, 'features', '/item_shippable', 'values', 0, 'key') in ('1', 1, True))
        return Listing(id=f"sb{aid}", title=it.get('subject') or it.get('title') or '',
                       description=it.get('body') or '', price=price, currency='EUR',
                       location=town or 'Subito', allows_shipping=shipping, slug=aid,
                       image_url=img, url=url or f"{self.BASE}/{aid}.htm", site='subito')

    def fetch_description(self, listing):
        return listing.description

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass
