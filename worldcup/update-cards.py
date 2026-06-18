#!/usr/bin/env python3
"""
Fetches card data from AiScore for finished WC2026 matches.
Updates wc2026-config.json with per-match events + team totals.
"""

import json, re, sys, os, time, socket
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

CONFIG_PATH = os.environ.get('CONFIG_PATH', 'worldcup/wc2026-config.json')
TIMEOUT = 10  # seconds per request

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'identity',
    'Connection': 'close',
}

def fetch_html(url):
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=TIMEOUT) as r:
            return r.read().decode('utf-8', errors='replace')
    except HTTPError as e:
        print(f'  HTTP {e.code}')
    except URLError as e:
        print(f'  URLError: {e.reason}')
    except socket.timeout:
        print(f'  Timed out after {TIMEOUT}s')
    except Exception as e:
        print(f'  Error: {type(e).__name__}: {e}')
    return None

def parse_cards(html, t1, t2):
    home_cards, away_cards = [], []

    # Find all card image references and surrounding context
    img_re = re.compile(r'<img[^>]+src=["\']([^"\']*(?:yellow|red)[^"\']*card[^"\']*)["\']', re.I)

    for m in img_re.finditer(html):
        src = m.group(1).lower()
        is_yellow = 'yellow' in src
        is_red = 'red' in src or 'second' in src
        if not is_yellow and not is_red:
            continue
        card_type = 'red' if is_red else 'yellow'

        # Look at surrounding 600 chars for minute + player name
        start = max(0, m.start() - 600)
        context_html = html[start:m.end() + 100]
        context = re.sub(r'<[^>]+>', ' ', context_html)
        context = re.sub(r'\s+', ' ', context).strip()

        # Find minute
        min_match = re.search(r'(\d{1,3})(?:\+\d+)?\s*\'', context)
        if not min_match:
            continue
        minute = int(min_match.group(1))
        if minute > 120:
            continue

        # Extract player name - look for Title Case words
        cleaned = re.sub(r'\d{1,3}(?:\+\d+)?\s*\'', ' ', context)
        cleaned = re.sub(r'\b(In|Out|Assist|Goal|Corner|HT|FT|Full Time|Half Time|Substitution|Penalty|VAR)\b', ' ', cleaned, flags=re.I)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        name_match = re.search(
            r'([A-ZÁÉÍÓÚÀÈÌÒÙÜÑČŠŽĆĐ][a-záéíóúàèìòùüñčšžćđ\-]+(?:\s+[A-ZÁÉÍÓÚÀÈÌÒÙÜÑČŠŽĆĐ][a-záéíóúàèìòùüñčšžćđ\-]+)+)',
            cleaned
        )
        if not name_match:
            continue
        name = name_match.group(1).strip()
        if len(name) < 4 or len(name) > 45:
            continue

        event = {'name': name, 'minute': minute, 'type': card_type}

        # Determine home/away from div class context before the img
        pre = html[start:m.start()]
        last_300 = pre[-300:]
        if re.search(r'class=["\'][^"\']*\bright\b[^"\']*["\']', last_300, re.I):
            away_cards.append(event)
        else:
            home_cards.append(event)

    def dedup(cards):
        seen, out = set(), []
        for c in sorted(cards, key=lambda x: x['minute']):
            k = (c['name'][:8], c['minute'], c['type'])
            if k not in seen:
                seen.add(k)
                out.append(c)
        return out

    return {'home': dedup(home_cards), 'away': dedup(away_cards)}


def build_slug(match_key):
    slug = match_key.lower().replace(' vs ', '-')
    replacements = [
        ('ü','u'),('ç','c'),('é','e'),('è','e'),('ê','e'),
        ('à','a'),('á','a'),('ã','a'),('â','a'),
        ('ó','o'),('ô','o'),('ú','u'),('ñ','n'),
        ('&',' and '),("'",''),('ş','s'),('ğ','g'),
    ]
    for old, new in replacements:
        slug = slug.replace(old, new)
    slug = re.sub(r'[^a-z0-9-]', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug


def main():
    print(f'Loading {CONFIG_PATH}...')
    with open(CONFIG_PATH) as f:
        config = json.load(f)

    ai_ids = config.get('aiScoreIds', {})
    if not ai_ids:
        print('No aiScoreIds in config — nothing to do')
        sys.exit(0)

    print(f'Found {len(ai_ids)} match IDs in config')

    match_cards = config.get('matchCards', {})
    errors = 0
    fetched = 0
    skipped = 0

    for match_key, aid in sorted(ai_ids.items()):
        parts = match_key.split(' vs ')
        if len(parts) != 2:
            continue
        t1, t2 = parts

        slug = build_slug(match_key)
        url = f'https://m.aiscore.com/match-{slug}/{aid}'
        print(f'\n[{fetched+skipped+errors+1}/{len(ai_ids)}] {match_key}')

        html = fetch_html(url)
        if not html:
            errors += 1
            continue

        if len(html) < 1000:
            print(f'  Too short ({len(html)} chars) — skipping')
            skipped += 1
            continue

        # Check if finished
        is_finished = 'Full Time' in html or '>FT<' in html or 'FT 1' in html or 'FT 2' in html or 'FT 0' in html
        if not is_finished:
            print(f'  Not finished yet — skipping')
            skipped += 1
            continue

        cards = parse_cards(html, t1, t2)
        total = len(cards['home']) + len(cards['away'])
        print(f'  ✓ {len(cards["home"])} home cards, {len(cards["away"])} away cards')

        match_cards[match_key] = {
            'homeTeam': t1, 'awayTeam': t2,
            'home': cards['home'], 'away': cards['away'],
            '_fetched': int(time.time() * 1000)
        }
        fetched += 1
        time.sleep(0.3)

    # Tally totals
    card_totals = {'_updated': int(time.time() * 1000)}
    for mc in match_cards.values():
        for team_key, events in [('homeTeam', 'home'), ('awayTeam', 'away')]:
            team = mc[team_key]
            if team not in card_totals:
                card_totals[team] = {'yellow': 0, 'red': 0}
            for e in mc.get(events, []):
                card_totals[team]['red' if e['type'] == 'red' else 'yellow'] += 1

    config['matchCards'] = match_cards
    config['cardTotals'] = card_totals

    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    total_y = sum(v.get('yellow', 0) for k, v in card_totals.items() if isinstance(v, dict))
    total_r = sum(v.get('red', 0) for k, v in card_totals.items() if isinstance(v, dict))
    print(f'\n{"="*50}')
    print(f'Done: {fetched} fetched, {skipped} skipped, {errors} errors')
    print(f'Totals: {total_y} yellows, {total_r} reds across {len(match_cards)} matches')

if __name__ == '__main__':
    main()
