#!/usr/bin/env python3
"""
Fetches card data from AiScore for finished WC2026 matches.
AiScore is a Vue SSR app — card data is in window.__NUXT__ JSON payload.
"""

import json, re, sys, os, time, socket
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

CONFIG_PATH = os.environ.get('CONFIG_PATH', 'worldcup/wc2026-config.json')
TIMEOUT = 10

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml',
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


def extract_nuxt_data(html):
    """Extract the __NUXT__ state object embedded by Vue SSR."""
    # Vue SSR embeds state as: window.__NUXT__={"state":...}
    # or as a script tag with type application/json and id __NUXT_DATA__
    
    # Try __NUXT_DATA__ script tag first (newer Nuxt 3)
    nuxt_data_match = re.search(
        r'<script[^>]+id=["\']__NUXT_DATA__["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.I
    )
    if nuxt_data_match:
        try:
            return json.loads(nuxt_data_match.group(1))
        except Exception:
            pass

    # Try window.__NUXT__ assignment (Nuxt 2 / older)
    nuxt_match = re.search(
        r'window\.__NUXT__\s*=\s*(\{.+?\});?\s*(?:</script>|window\.)',
        html, re.DOTALL
    )
    if nuxt_match:
        try:
            return json.loads(nuxt_match.group(1))
        except Exception:
            pass

    # Try any script tag containing NUXT data
    for script in re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
        if '__NUXT__' in script or 'nuxtState' in script:
            # Try to extract JSON object
            obj_match = re.search(r'(\{.{100,}\})', script, re.DOTALL)
            if obj_match:
                try:
                    return json.loads(obj_match.group(1))
                except Exception:
                    pass

    return None


def find_cards_in_data(data, t1, t2):
    """
    Recursively search the NUXT data structure for card events.
    Card events typically have fields like: type, minute, player, team
    """
    home_cards = []
    away_cards = []

    # Card type codes used by sports data APIs
    YELLOW = {1, 'yellow', 'Y', 'YC', 41, '41'}
    RED = {2, 'red', 'R', 'RC', 42, '42', 'second_yellow', 'SY'}

    def walk(obj, depth=0):
        if depth > 15:
            return
        if isinstance(obj, dict):
            # Look for event objects with card indicators
            keys = set(str(k).lower() for k in obj.keys())
            has_minute = any(k in keys for k in ['minute', 'min', 'time', 'match_time'])
            has_player = any(k in keys for k in ['player', 'name', 'player_name', 'playerName'])
            has_type = any(k in keys for k in ['type', 'event_type', 'eventType', 'incident_type'])

            if has_minute and has_player:
                # Try to extract event type
                event_type = None
                for k in ['type', 'event_type', 'eventType', 'incident_type', 'incidentType']:
                    if k in obj:
                        event_type = obj[k]
                        break

                is_card = False
                card_type = None
                if event_type in YELLOW or str(event_type) in {str(x) for x in YELLOW}:
                    is_card = True
                    card_type = 'yellow'
                elif event_type in RED or str(event_type) in {str(x) for x in RED}:
                    is_card = True
                    card_type = 'red'
                elif isinstance(event_type, str) and ('yellow' in event_type.lower() or 'card' in event_type.lower()):
                    is_card = True
                    card_type = 'red' if 'red' in event_type.lower() or 'second' in event_type.lower() else 'yellow'

                if is_card and card_type:
                    # Extract player name
                    player = None
                    for k in ['player', 'name', 'player_name', 'playerName', 'fullName']:
                        if k in obj and isinstance(obj[k], str) and len(obj[k]) > 2:
                            player = obj[k]
                            break
                    if not player:
                        for k in obj:
                            if isinstance(obj[k], dict):
                                for nk in ['name', 'fullName', 'player_name']:
                                    if nk in obj[k] and isinstance(obj[k][nk], str):
                                        player = obj[k][nk]
                                        break
                            if player:
                                break

                    # Extract minute
                    minute = None
                    for k in ['minute', 'min', 'time', 'match_time', 'matchTime']:
                        if k in obj:
                            try:
                                minute = int(str(obj[k]).split('+')[0].split('.')[0])
                                break
                            except Exception:
                                pass

                    # Determine home/away
                    is_home = True
                    for k in ['team', 'team_id', 'teamId', 'side', 'isHome']:
                        if k in obj:
                            v = str(obj[k]).lower()
                            if v in ['away', 'false', '0', t2.lower()]:
                                is_home = False
                                break
                            elif v in ['home', 'true', '1', t1.lower()]:
                                is_home = True
                                break

                    if player and minute is not None and 0 < minute <= 125:
                        event = {'name': player, 'minute': minute, 'type': card_type}
                        if is_home:
                            home_cards.append(event)
                        else:
                            away_cards.append(event)

            for v in obj.values():
                walk(v, depth + 1)

        elif isinstance(obj, list):
            for item in obj:
                walk(item, depth + 1)

    walk(data)

    def dedup(cards):
        seen, out = set(), []
        for c in sorted(cards, key=lambda x: x['minute']):
            k = (c['name'][:6], c['minute'], c['type'])
            if k not in seen:
                seen.add(k)
                out.append(c)
        return out

    return {'home': dedup(home_cards), 'away': dedup(away_cards)}


def parse_cards_from_text(html, t1, t2):
    """
    Fallback: parse card events from visible text patterns in HTML.
    Looks for patterns near known card-related text.
    """
    # Strip to text
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)

    # Look for sequences like: "PlayerName 45'" or "45' PlayerName"
    # near card-related words
    home_cards, away_cards = [], []

    # Find "yellow card" or "red card" mentions and surrounding context
    for card_match in re.finditer(r'(yellow\s+card|red\s+card|second\s+yellow)', text, re.I):
        card_type = 'red' if 'red' in card_match.group(1).lower() or 'second' in card_match.group(1).lower() else 'yellow'
        ctx_start = max(0, card_match.start() - 100)
        ctx_end = min(len(text), card_match.end() + 100)
        ctx = text[ctx_start:ctx_end]

        min_m = re.search(r'(\d{1,3})(?:\+\d+)?\s*\'', ctx)
        name_m = re.search(r'([A-Z][a-záéíóúñüç]+ [A-Z][a-záéíóúñüç]+)', ctx)

        if min_m and name_m:
            minute = int(min_m.group(1))
            name = name_m.group(1)
            if 0 < minute <= 125:
                home_cards.append({'name': name, 'minute': minute, 'type': card_type})

    return {'home': home_cards, 'away': away_cards}


def debug_html(html, match_key):
    """Print diagnostic info about what's in the HTML."""
    print(f'  HTML length: {len(html)}')
    print(f'  Has __NUXT__: {"__NUXT__" in html}')
    print(f'  Has __NUXT_DATA__: {"__NUXT_DATA__" in html}')
    print(f'  Has icon-yellow-card: {"icon-yellow-card" in html}')
    print(f'  Has xlink: {"xlink" in html}')
    print(f'  Has Full Time: {"Full Time" in html}')
    has_ft = bool(re.search(r"\bFT\b", html))
    print(f'  Has FT: {has_ft}')
    # Show script tags
    scripts = re.findall(r'<script([^>]*)>', html)
    print(f'  Script tags: {len(scripts)}')
    for s in scripts[:5]:
        print(f'    <script{s}>')
    # Show a snippet of body
    body_m = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL)
    if body_m:
        body_text = re.sub(r'<[^>]+>', ' ', body_m.group(1))
        body_text = re.sub(r'\s+', ' ', body_text).strip()
        print(f'  Body text preview: {body_text[:300]}')


def build_slug(match_key):
    slug = match_key.lower().replace(' vs ', '-')
    for old, new in [
        ('ü','u'),('ç','c'),('é','e'),('è','e'),('ê','e'),
        ('à','a'),('á','a'),('ã','a'),('â','a'),
        ('ó','o'),('ô','o'),('ú','u'),('ñ','n'),
        ('&',' and '),("'",''),('ş','s'),('ğ','g'),
    ]:
        slug = slug.replace(old, new)
    slug = re.sub(r'[^a-z0-9-]', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug


def main():
    debug_first = os.environ.get('DEBUG_FIRST', '0') == '1'

    print(f'Loading {CONFIG_PATH}...')
    with open(CONFIG_PATH) as f:
        config = json.load(f)

    ai_ids = config.get('aiScoreIds', {})
    if not ai_ids:
        print('No aiScoreIds in config')
        sys.exit(0)

    print(f'Found {len(ai_ids)} match IDs')

    match_cards = config.get('matchCards', {})
    errors = 0
    fetched = 0
    skipped = 0

    for i, (match_key, aid) in enumerate(sorted(ai_ids.items()), 1):
        parts = match_key.split(' vs ')
        if len(parts) != 2:
            continue
        t1, t2 = parts

        slug = build_slug(match_key)
        url = f'https://m.aiscore.com/match-{slug}/{aid}'
        print(f'\n[{i}/{len(ai_ids)}] {match_key}')

        html = fetch_html(url)
        if not html or len(html) < 1000:
            errors += 1
            continue

        # Debug first match to understand structure
        if debug_first and i == 1:
            debug_html(html, match_key)

        is_finished = bool(re.search(r'Full\s*Time|"isFinished"\s*:\s*true|"status"\s*:\s*"finished"', html, re.I))
        if not is_finished:
            print(f'  Not finished — skipping')
            skipped += 1
            continue

        # Try NUXT data extraction first
        cards = {'home': [], 'away': []}
        nuxt_data = extract_nuxt_data(html)
        if nuxt_data:
            cards = find_cards_in_data(nuxt_data, t1, t2)
            print(f'  NUXT data found, {len(cards["home"])} home, {len(cards["away"])} away cards')
        else:
            # Fallback to text parsing
            cards = parse_cards_from_text(html, t1, t2)
            print(f'  No NUXT data, text fallback: {len(cards["home"])} home, {len(cards["away"])} away cards')

        if cards['home'] or cards['away']:
            print(f'    Home: {[(c["name"], c["minute"], c["type"]) for c in cards["home"]]}')
            print(f'    Away: {[(c["name"], c["minute"], c["type"]) for c in cards["away"]]}')

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
        for team_key, events_key in [('homeTeam', 'home'), ('awayTeam', 'away')]:
            team = mc[team_key]
            if team not in card_totals:
                card_totals[team] = {'yellow': 0, 'red': 0}
            for e in mc.get(events_key, []):
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
