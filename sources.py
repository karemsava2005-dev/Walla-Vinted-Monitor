"""One place that knows which client handles which site."""

SITES = {"wallapop": "Wallapop", "vinted": "Vinted", "milanuncios": "Milanuncios"}


def make_client(item):
    site = getattr(item, 'site', 'wallapop') or 'wallapop'
    if site == 'vinted':
        from managers.vinted_client import VintedClient
        return VintedClient(item.vinted_domain)
    if site == 'milanuncios':
        from managers.milanuncios_client import MilanunciosClient
        return MilanunciosClient()
    from managers.wallapop_client import WallapopClient
    return WallapopClient()
