import logging
import time

import requests

from datalayer.listing import Listing

SEARCH_URL = "https://api.wallapop.com/api/v3/search"
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36')
RETRIES = 3


class WallapopError(RuntimeError):
    pass


class WallapopClient:
    """Talks to Wallapop's own search API (the one the website uses). No login needed."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._session = requests.Session()
        self._session.headers.update({
            'X-DeviceOS': '0',
            'User-Agent': USER_AGENT,
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'es-ES,es;q=0.9',
            'Origin': 'https://es.wallapop.com',
            'Referer': 'https://es.wallapop.com/',
        })
        self.location_applied = True  # Wallapop always honours the coordinates we send

    @staticmethod
    def build_params(item):
        params = {
            'source': 'search_box',
            'keywords': item.search_query,
            'order_by': 'newest',
            'language': 'es_ES',
            'section_type': 'organic_search_results',
        }
        if item.has_coords():
            params['latitude'] = item.latitude
            params['longitude'] = item.longitude
        if item.radius_km and item.radius_km != '0':
            params['distance_in_km'] = item.radius_km
        if item.min_price:
            params['min_sale_price'] = item.min_price
        if item.max_price:
            params['max_sale_price'] = item.max_price
        if item.condition and item.condition != 'all':
            params['condition'] = item.condition
        return {k: v for k, v in params.items() if v not in (None, '')}

    def web_url(self, item):
        """Same search on the Wallapop website (for opening in the browser)."""
        from urllib.parse import urlencode
        p = self.build_params(item)
        web = {'keywords': p['keywords'], 'order_by': 'newest'}
        for k in ('latitude', 'longitude', 'distance_in_km', 'min_sale_price', 'max_sale_price',
                  'condition'):
            if k in p:
                web[k] = p[k]
        if 'distance_in_km' in web:
            web['distance'] = int(float(web.pop('distance_in_km')) * 1000)
        return "https://es.wallapop.com/app/search?" + urlencode(web)

    def search(self, item):
        params = self.build_params(item)
        last_err = None
        for attempt in range(RETRIES):
            try:
                r = self._session.get(SEARCH_URL, params=params, timeout=20)
                if r.status_code == 429:
                    raise WallapopError("Wallapop says too many requests - raise the check interval")
                r.raise_for_status()
                data = r.json()
                break
            except (requests.RequestException, ValueError, WallapopError) as e:
                last_err = e
                self.logger.warning(f"Wallapop request failed ({e}), retry {attempt + 1}/{RETRIES}")
                time.sleep(3 * (attempt + 1))
        else:
            raise WallapopError(f"Couldn't reach Wallapop: {last_err}")

        items = self._extract_items(data)
        listings = []
        for raw in items:
            listing = Listing.load_from_json(raw)
            if listing:
                listings.append(listing)
        return listings

    @staticmethod
    def _extract_items(data):
        # current format: data.section.payload.items  (older: search_objects)
        try:
            return data['data']['section']['payload']['items']
        except (KeyError, TypeError):
            pass
        if isinstance(data, dict) and isinstance(data.get('search_objects'), list):
            return data['search_objects']
        raise WallapopError("Unexpected reply from Wallapop (the API may have changed)")

    def fetch_description(self, listing):
        return listing.description  # already included in search results

    def close(self):
        self._session.close()
