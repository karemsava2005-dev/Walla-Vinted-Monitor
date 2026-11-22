"""One place that knows which client handles which site."""

SITES = {"wallapop": "Wallapop", "vinted": "Vinted", "milanuncios": "Milanuncios", "linkedin": "LinkedIn", "indeed": "Indeed", "remotive": "Remotive", "subito": "Subito"}


def make_client(item):
    site = getattr(item, 'site', 'wallapop') or 'wallapop'
    if site == 'vinted':
        from managers.vinted_client import VintedClient
        return VintedClient(item.vinted_domain)
    if site == 'linkedin':
        from managers.jobs_client import LinkedInClient
        return LinkedInClient()
    if site == 'subito':
        from managers.subito_client import SubitoClient
        return SubitoClient()
    if site == 'remotive':
        from managers.jobs_client import RemotiveClient
        return RemotiveClient()
    if site == 'indeed':
        from managers.jobs_client import IndeedClient
        return IndeedClient(getattr(item, 'indeed_domain', 'www') or 'www')
    if site == 'milanuncios':
        from managers.milanuncios_client import MilanunciosClient
        return MilanunciosClient()
    from managers.wallapop_client import WallapopClient
    return WallapopClient()
