"""Turns a place name into coordinates using OpenStreetMap (free, no key)."""
import requests


def geocode(query):
    """Returns (lat, lng, label) or raises ValueError if nothing was found."""
    r = requests.get('https://nominatim.openstreetmap.org/search',
                     params={'q': query, 'format': 'json', 'limit': 1, 'accept-language': 'en'},
                     headers={'User-Agent': 'MarketplaceMonitor/1.0 (personal desktop app)'}, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not data:
        raise ValueError(f'No place called "{query}" found')
    hit = data[0]
    parts = [p.strip() for p in hit.get('display_name', query).split(',')
             if p.strip() and not any(ch.isdigit() for ch in p)]
    label = ', '.join(dict.fromkeys([parts[0]] + parts[-2:])) if len(parts) > 2 else ', '.join(parts)
    return round(float(hit['lat']), 6), round(float(hit['lon']), 6), label
