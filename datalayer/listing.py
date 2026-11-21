
class Listing:
    def __init__(self, id, title, description, price, currency, location, allows_shipping,
                 slug, image_url=None, is_reserved=False, is_sold=False, created_at=None, url=None, site='wallapop'):
        self.id = str(id)
        self.title = title or ""
        self.description = description or ""
        self.price = price
        self.currency = currency or "EUR"
        self.location = location or ""
        self.allows_shipping = allows_shipping
        self.slug = slug or self.id
        self.image_url = image_url
        self.is_pending = is_reserved   # name shared with the filter code
        self.is_sold = is_sold
        self.created_at = created_at  # seconds since epoch, if the site sent it
        self._url = url
        self.site = site

    @property
    def url(self):
        return self._url or f"https://es.wallapop.com/item/{self.slug}"

    @property
    def formatted_price(self):
        if self.price is None:
            return ""
        symbol = "€" if self.currency.upper() == "EUR" else self.currency
        return f"{self.price:g} {symbol}"

    @staticmethod
    def _image(item):
        images = item.get('images') or []
        if not images:
            return None
        img = images[0]
        if isinstance(img, str):
            return img
        urls = img.get('urls') or img
        for key in ('medium', 'small', 'big', 'original', 'url'):
            if isinstance(urls.get(key), str):
                return urls[key]
        return None

    @classmethod
    def load_from_json(cls, item):
        """Build from one item of Wallapop's /api/v3/search response. None if unusable."""
        if not item.get('id') or item.get('title') is None:
            return None
        price = item.get('price') or {}
        try:
            amount = float(price.get('amount'))
        except (TypeError, ValueError):
            amount = None
        reserved = item.get('reserved') or {}
        reserved = reserved.get('flag') if isinstance(reserved, dict) else bool(reserved)
        shipping = item.get('shipping') or {}
        location = item.get('location') or {}
        return cls(
            id=item['id'],
            title=item.get('title'),
            description=item.get('description'),
            price=amount,
            currency=price.get('currency', 'EUR'),
            location=location.get('city') or location.get('postal_code') or '',
            allows_shipping=shipping.get('user_allows_shipping'),
            slug=item.get('web_slug'),
            image_url=cls._image(item),
            is_reserved=bool(reserved),
            is_sold=bool((item.get('sold') or {}).get('flag')) if isinstance(item.get('sold'), dict) else False,
            created_at=cls._timestamp(item.get('created_at') or item.get('creation_date')),
        )

    @staticmethod
    def _timestamp(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return v / 1000 if v > 1e11 else v  # Wallapop uses milliseconds

    def __eq__(self, other):
        return isinstance(other, Listing) and self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def __str__(self):
        return f"Listing(id={self.id}, title='{self.title}', price={self.formatted_price}, url='{self.url}')"
