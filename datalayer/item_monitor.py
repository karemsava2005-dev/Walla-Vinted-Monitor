
# Maps the friendly condition names (same as Wallamonitor) to Facebook's values
CONDITION_MAP = {
    "new": "new",
    "as_good_as_new": "used_like_new",
    "good": "used_good",
    "fair": "used_fair",
    "has_given_it_all": "used_fair",
}


def _as_list(value):
    """Accept either a list or a single string ("" = nothing)."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _to_float(v):
    try:
        return float(str(v).replace(',', '.')) if str(v).strip() not in ('', 'None') else None
    except ValueError:
        return None


class ItemMonitor:
    def __init__(self, search_query, location, radius_km, condition, min_price, max_price,
                 days_since_listed, title_exclude, description_exclude, title_must_include,
                 description_must_include, title_first_word_exclude, latitude=None, longitude=None,
                 site='wallapop', vinted_domain='es', province=''):
        self.search_query = search_query
        self.location = location
        self.radius_km = radius_km
        self.site = site or 'wallapop'
        self.vinted_domain = vinted_domain or 'es'
        self.province = province or ''
        self.latitude = _to_float(latitude)
        self.longitude = _to_float(longitude)
        self.condition = condition
        self.min_price = min_price
        self.max_price = max_price
        self.days_since_listed = days_since_listed
        self.title_exclude = [w.lower() for w in _as_list(title_exclude)]
        self.description_exclude = [w.lower() for w in _as_list(description_exclude)]
        self.title_must_include = [w.lower() for w in _as_list(title_must_include)]
        self.description_must_include = [w.lower() for w in _as_list(description_must_include)]
        self.title_first_word_exclude = [w.lower() for w in _as_list(title_first_word_exclude)]

    @classmethod
    def load_from_json(cls, d):
        return cls(
            search_query=d['search_query'],
            location=str(d.get('location', '')).strip(),
            radius_km=str(d.get('radius_km', d.get('max_distance', '0'))),
            condition=d.get('condition', 'all'),
            min_price=str(d.get('min_price', '')),
            max_price=str(d.get('max_price', '')),
            days_since_listed=str(d.get('days_since_listed', '')),
            title_exclude=d.get('title_exclude', []),
            description_exclude=d.get('description_exclude', []),
            title_must_include=d.get('title_must_include', []),
            description_must_include=d.get('description_must_include', []),
            title_first_word_exclude=d.get('title_first_word_exclude', []),
            latitude=d.get('latitude'),
            longitude=d.get('longitude'),
            site=d.get('site', 'wallapop'),
            vinted_domain=d.get('vinted_domain', 'es'),
            province=d.get('province', ''),
        )

    def has_coords(self):
        return self.latitude is not None and self.longitude is not None

    def fb_condition(self):
        return None if not self.condition or self.condition == "all" else self.condition

    def needs_description(self):
        return bool(self.description_exclude or self.description_must_include)
