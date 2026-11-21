import html
import logging

import requests

ITEM_TEXT = ("<b>Artículo</b>: {title}\n"
             "<b>Precio</b>: {price}\n"
             "<b>Localidad</b>: {location}\n"
             "{shipping}"
             "{description}"
             '<a href="{url}">Ir al anuncio</a>')


class TelegramManager:
    def __init__(self, token, channel):
        self.logger = logging.getLogger(__name__)
        self._token = token.strip()
        self._channel = channel.strip()
        self._api = f"https://api.telegram.org/bot{self._token}"

    @classmethod
    def from_yaml(cls, path='config.yaml'):
        import yaml
        with open(path, encoding='utf-8') as f:
            c = yaml.safe_load(f)
        return cls(str(c['telegram_token']), str(c['telegram_channel']))

    def _post(self, method, data):
        r = requests.post(f"{self._api}/{method}", data={'chat_id': self._channel, **data}, timeout=30)
        if not r.ok:
            try:
                desc = r.json().get('description', r.text)
            except ValueError:
                desc = r.text
            raise RuntimeError(f"Telegram: {desc[:200]}")
        return r

    def send_test(self):
        self._post('sendMessage', {'text': '✅ Marketplace Monitor is connected to this channel.'})

    def send_listing(self, listing, search_name=None):
        e = html.escape
        if getattr(listing, 'site', '') in ('linkedin', 'indeed'):
            board = 'LinkedIn' if listing.site == 'linkedin' else 'Indeed'
            text = (f"💼 <b>{e(listing.title)}</b>\n{e(listing.location or '')}\n"
                    + (f"{e(listing.description[:300])}\n" if listing.description else "")
                    + f'<a href="{listing.url}">Open on {board}</a>')
            if search_name:
                text = f"🔎 <i>{e(search_name)}</i>\n" + text
            self._post('sendMessage', {'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': True})
            return
        price = listing.formatted_price or (f"{listing.price:g} {listing.currency}" if listing.price is not None else "?")
        shipping = ""
        if listing.allows_shipping is not None:
            shipping = f"<b>Acepta envíos</b>: {'Sí' if listing.allows_shipping else 'No'}\n"
        description = ""
        if listing.description:
            desc = listing.description if len(listing.description) <= 500 else listing.description[:500] + "…"
            description = f"<b>Descripción</b>: {e(desc)}\n"

        text = ITEM_TEXT.format(title=e(listing.title), price=e(price), location=e(listing.location or "?"),
                                shipping=shipping, description=description, url=listing.url)
        if search_name:
            text = f"🔎 <i>{e(search_name)}</i>\n" + text

        if listing.image_url:
            try:
                self._post('sendPhoto', {'photo': listing.image_url, 'caption': text[:1024], 'parse_mode': 'HTML'})
                return
            except RuntimeError as err:
                self.logger.warning(f"sendPhoto failed ({err}), falling back to text")
        self._post('sendMessage', {'text': text, 'parse_mode': 'HTML'})
