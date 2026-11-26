"""Job boards: LinkedIn (public guest job search) and Indeed. Each job becomes a Listing
(price = None, location = company · place) so the normal filters and seen-tracking work."""
import html
import json
import logging
import re
import random
import time
from urllib.parse import urlencode

import requests

from datalayer.listing import Listing

_LAST_LI = 0.0

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")


class JobsError(Exception):
    pass


def _word_in(words, text):
    return any(re.search(r'(?<![a-z])' + re.escape(w) + r'(?![a-z])', text) for w in words)


def region_filter(item, listings, logger):
    """Keep only jobs whose location/title fits the wanted regions.
    region_exclude: dropped if the location or title mentions any of these (e.g. india, "us only").
    region_include: if set, the location must mention one of these (e.g. europe, united kingdom)."""
    inc, exc = getattr(item, 'region_include', []), getattr(item, 'region_exclude', [])
    out = []
    for l in listings:
        loc = (l.location or '').lower()
        title = (l.title or '').lower()
        if exc and (_word_in(exc, loc) or _word_in(exc, title)):
            logger.info(f"excluded (region): {l.title} | {l.location}")
            continue
        if inc and not _word_in(inc, loc):
            logger.info(f"excluded (not an allowed region): {l.title} | {l.location}")
            continue
        out.append(l)
    return out


def _clean(s):
    return html.unescape(re.sub(r'<[^>]+>', '', s or '')).strip()


class LinkedInClient:
    """Uses the logged-out job search LinkedIn shows to visitors. No account, no cookies."""
    URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.s = requests.Session()
        self.s.headers.update({'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9'})

    def search(self, item):
        p = {'keywords': item.search_query, 'location': item.location or 'Worldwide',
             'f_TPR': 'r86400', 'sortBy': 'DD', 'start': '0'}   # posted in the last 24 h, newest first
        if getattr(item, 'remote', True):
            p['f_WT'] = '2'                                       # remote only
        global _LAST_LI
        last = None
        for attempt in range(3):
            # LinkedIn answers 429 when searches come back to back: keep ~12-20 s between requests.
            wait = _LAST_LI + random.uniform(12, 20) - time.time()
            if wait > 0:
                time.sleep(wait)
            r = self.s.get(f"{self.URL}?{urlencode(p)}", timeout=20)
            _LAST_LI = time.time()
            if r.status_code == 200:
                return region_filter(item, self._parse(r.text), self.logger)
            last = r.status_code
            time.sleep(20 * (attempt + 1))
        raise JobsError(f"LinkedIn answered HTTP {last} (429 = too many requests, 999 = blocked)")

    def _parse(self, text):
        out = []
        for card in re.split(r'<li[ >]', text)[1:]:
            m = re.search(r'jobPosting:(\d+)', card) or re.search(r'/view/[^"?]*?-(\d+)', card)
            if not m:
                continue
            jid = m.group(1)
            title = _clean((re.search(r'base-search-card__title[^>]*>(.*?)</h3>', card, re.S) or [None, ''])[1])
            company = _clean((re.search(r'base-search-card__subtitle[^>]*>(.*?)</h4>', card, re.S) or [None, ''])[1])
            place = _clean((re.search(r'job-search-card__location[^>]*>(.*?)</span>', card, re.S) or [None, ''])[1])
            out.append(Listing(id=f"li{jid}", title=title, description='', price=None, currency='',
                               location=" · ".join(x for x in (company, place) if x), allows_shipping=None,
                               slug=jid, url=f"https://www.linkedin.com/jobs/view/{jid}", site='linkedin'))
        return out

    def fetch_description(self, listing):
        """Open the job's public page: full description + LinkedIn's criteria (seniority, type, industry)."""
        global _LAST_LI
        jid = listing.slug
        for attempt in range(2):
            wait = _LAST_LI + random.uniform(8, 14) - time.time()
            if wait > 0:
                time.sleep(wait)
            try:
                r = self.s.get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}", timeout=20)
            except requests.RequestException as e:
                self.logger.warning(f"LinkedIn job page failed: {e}")
                return listing.description
            _LAST_LI = time.time()
            if r.status_code == 200:
                break
            self.logger.warning(f"LinkedIn job page HTTP {r.status_code} for {jid}, retry {attempt + 1}/2")
            time.sleep(20)
        else:
            return listing.description
        t = r.text
        desc = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', t, re.S)
        desc = _clean(re.sub(r'<br\s*/?>|</li>|</p>', '\n', desc.group(1))) if desc else ''
        crit = {_clean(h): _clean(v) for h, v in re.findall(
            r'description__job-criteria-subheader[^>]*>(.*?)</h3>.*?description__job-criteria-text[^>]*>(.*?)</span>', t, re.S)}
        applicants = re.search(r'num-applicants__caption[^>]*>(.*?)</', t, re.S)
        info = [crit.get('Employment type'), crit.get('Seniority level'), crit.get('Industries'),
                _clean(applicants.group(1)) if applicants else None]
        listing.location = " · ".join(x for x in [listing.location] + info if x and x != 'Not Applicable')
        return re.sub(r'[ \t]+', ' ', desc)

    def close(self):
        self.s.close()


class IndeedClient:
    """Indeed protects its site with Cloudflare; from data-centre servers (GitHub) it often refuses.
    If it does, the search fails on its own and the others keep running."""

    def __init__(self, domain='www'):
        self.logger = logging.getLogger(__name__)
        self.base = f"https://{domain}.indeed.com"
        self.s = requests.Session()
        self.s.headers.update({'User-Agent': UA, 'Accept': 'text/html', 'Accept-Language': 'en-US,en;q=0.9'})

    def search(self, item):
        p = {'q': item.search_query, 'l': item.location or 'Remote', 'sort': 'date', 'fromage': '1'}
        r = self.s.get(f"{self.base}/jobs?{urlencode(p)}", timeout=25)
        if r.status_code != 200:
            raise JobsError(f"Indeed answered HTTP {r.status_code} (403 = blocked by Cloudflare)")
        m = re.search(r'mosaic-provider-jobcards"\]\s*=\s*(\{.*?\});\s*\n', r.text, re.S)
        if not m:
            raise JobsError("Indeed page had no job list (probably a bot check page)")
        data = json.loads(m.group(1))
        results = (data.get('metaData', {}).get('mosaicProviderJobCardsModel', {}).get('results')) or []
        out = []
        for j in results:
            key = j.get('jobkey')
            if not key:
                continue
            out.append(Listing(id=f"in{key}", title=j.get('displayTitle') or j.get('title'),
                               description=_clean(j.get('snippet')), price=None, currency='',
                               location=" · ".join(x for x in (j.get('company'), j.get('formattedLocation')) if x),
                               allows_shipping=None, slug=key, url=f"{self.base}/viewjob?jk={key}", site='indeed'))
        return region_filter(item, out, self.logger)

    def fetch_description(self, listing):
        return listing.description

    def close(self):
        self.s.close()


class RemotiveClient:
    """Remotive's free public API. It shows each job's allowed candidate location, so region filtering
    is reliable here. Remotive asks API users to call it only a few times a day: keep every_min >= 360."""
    URL = "https://remotive.com/api/remote-jobs"

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.s = requests.Session()
        self.s.headers.update({'User-Agent': UA})

    def search(self, item):
        r = self.s.get(self.URL, params={'category': 'sales-business', 'search': item.search_query, 'limit': 100}, timeout=25)
        if r.status_code != 200:
            raise JobsError(f"Remotive answered HTTP {r.status_code}")
        out = []
        for j in r.json().get('jobs', []):
            loc = j.get('candidate_required_location') or ''
            out.append(Listing(id=f"rm{j.get('id')}", title=j.get('title') or '',
                               description=_clean(j.get('description'))[:400], price=None, currency='',
                               location=" · ".join(x for x in (j.get('company_name'), loc) if x),
                               allows_shipping=None, slug=str(j.get('id')), url=j.get('url'), site='remotive'))
        return region_filter(item, out, self.logger)

    def fetch_description(self, listing):
        return listing.description

    def close(self):
        self.s.close()
