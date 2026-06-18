#!/usr/bin/env python3
"""
Fetches card data from ESPN's public API for finished WC2026 matches.
ESPN returns clean JSON - no scraping needed.

Endpoints:
  Scoreboard: site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?limit=200&dates=20260611-20260719
  Summary:    site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={id}
"""

import json, re, sys, os, time
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

CONFIG_PATH = os.environ.get('CONFIG_PATH', 'worldcup/wc2026-config.json')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; curl/7.68)',
    'Accept': 'application/json',
}

SCOREBOARD_URL = 'https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?limit=200&dates=20260611-20260719'
SUMMARY_URL    = 'https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={}'

# ESPN team name → our sweep name
NAME_MAP = {
    'Mexico': 'Mexico', 'South Africa': 'South Africa',
    'South Korea': 'South Korea', 'Korea Republic': 'South Korea',
    'Czech Republic': 'Czechia', 'Czechia': 'Czechia',
    'Canada': 'Canada', 'Bosnia and Herzegovina': 'Bosnia & Herzegovina',
    'Bosnia & Herzegovina': 'Bosnia & Herzegovina',
    'USA': 'USA', 'United States': 'USA',
    'Paraguay': 'Paraguay', 'Qatar': 'Qatar', 'Switzerland': 'Switzerland',
    'Brazil': 'Brazil', 'Morocco': 'Morocco', 'Scotland': 'Scotland',
    'Haiti': 'Haiti', 'Australia': 'Australia', 'Turkiye': 'Türkiye',
    'Turkey': 'Türkiye', 'Türkiye': 'Türkiye', 'Germany': 'Germany',
    "Ivory Coast": 'Ivory Coast', "Cote d'Ivoire": 'Ivory Coast',
    "Côte d'Ivoire": 'Ivory Coast',
    'Netherlands': 'Netherlands', 'Japan': 'Japan',
    'Sweden': 'Sweden', 'Tunisia': 'Tunisia',
    'Spain': 'Spain', 'Cabo Verde': 'Cape Verde', 'Cape Verde': 'Cape Verde',
    'Belgium': 'Belgium', 'Egypt': 'Egypt',
    'Saudi Arabia': 'Saudi Arabia', 'Uruguay': 'Uruguay',
    'Iran': 'Iran', 'New Zealand': 'New Zealand',
    'France': 'France', 'Senegal': 'Senegal',
    'Norway': 'Norway', 'Iraq': 'Iraq',
    'Argentina': 'Argentina', 'Algeria': 'Algeria',
    'Austria': 'Austria', 'Jordan': 'Jordan',
    'Portugal': 'Portugal', 'DR Congo': 'DR Congo',
    'Congo, DR': 'DR Congo', 'Democratic Republic of Congo': 'DR Congo',
    'England': 'England', 'Croatia': 'Croatia',
    'Ghana': 'Ghana', 'Panama': 'Panama',
    'Colombia': 'Colombia', 'Uzbekistan': 'Uzbekistan',
    'Ecuador': 'Ecuador', 'Curacao': 'Curaçao', 'Curaçao': 'Curaçao',
}

def fetch_json(url):
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode('utf-8'))
    except HTTPError as e:
        print(f'  HTTP {e.code}: {url}')
    except URLError as e:
        print(f'  URLError: {e.reason}')
    except Exception as e:
        print(f'  Error: {type(e).__name__}: {e}')
    return None


def normalise(name):
    return NAME_MAP.get(name, name)


def parse_summary(data, t1, t2):
    """Extract card events from ESPN match summary JSON."""
    home_cards, away_cards = [], []

    # ESPN incidents are in data['header']['competitions'][0]['details']
    # or data['plays'] for play-by-play
    # Card type IDs: 93=yellow card, 94=red card, 95=second yellow

    # Try header > competitions > details first
    try:
        details = data['header']['competitions'][0].get('details', [])
        for d in details:
            type_id = d.get('type', {}).get('id')
            type_text = d.get('type', {}).get('text', '').lower()
            is_yellow = type_id in ('93', 93) or 'yellow' in type_text
            is_red = type_id in ('94', 94, '95', 95) or 'red card' in type_text or 'second yellow' in type_text
            if not is_yellow and not is_red:
                continue

            athlete = d.get('athletesInvolved', [{}])
            name = athlete[0].get('displayName', '') if athlete else ''
            if not name:
                continue

            clock = d.get('clock', {})
            minute_str = clock.get('displayValue', '0')
            try:
                minute = int(minute_str.split(':')[0].split('+')[0])
            except Exception:
                continue

            card_type = 'red' if is_red else 'yellow'
            team_id = d.get('team', {}).get('id', '')
            home_id = str(data['header']['competitions'][0]['competitors'][0]['team']['id'])
            event = {'name': name, 'minute': minute, 'type': card_type}
            if team_id == home_id:
                home_cards.append(event)
            else:
                away_cards.append(event)

    except (KeyError, IndexError, TypeError):
        pass

    # Fallback: try plays array
    if not home_cards and not away_cards:
        try:
            plays = data.get('plays', [])
            home_id = str(data['header']['competitions'][0]['competitors'][0]['team']['id'])
            for play in plays:
                type_id = str(play.get('type', {}).get('id', ''))
                type_text = play.get('type', {}).get('text', '').lower()
                is_yellow = type_id == '93' or 'yellow' in type_text
                is_red = type_id in ('94','95') or 'red' in type_text
                if not is_yellow and not is_red:
                    continue
                participants = play.get('participants', [{}])
                name = participants[0].get('athlete', {}).get('displayName', '') if participants else ''
                if not name:
                    continue
                clock = play.get('clock', {})
                try:
                    minute = int(clock.get('displayValue','0').split(':')[0].split('+')[0])
                except Exception:
                    continue
                team_id = str(play.get('team', {}).get('id', ''))
                card_type = 'red' if is_red else 'yellow'
                event = {'name': name, 'minute': minute, 'type': card_type}
                if team_id == home_id:
                    home_cards.append(event)
                else:
                    away_cards.append(event)
        except (KeyError, IndexError, TypeError):
            pass

    def dedup(cards):
        seen, out = set(), []
        for c in sorted(cards, key=lambda x: x['minute']):
            k = (c['name'][:8], c['minute'], c['type'])
            if k not in seen:
                seen.add(k)
                out.append(c)
        return out

    return {'home': dedup(home_cards), 'away': dedup(away_cards)}


def main():
    print(f'Loading {CONFIG_PATH}...')
    with open(CONFIG_PATH) as f:
        config = json.load(f)

    # Step 1: fetch scoreboard to get all match event IDs
    print('Fetching ESPN scoreboard...')
    scoreboard = fetch_json(SCOREBOARD_URL)
    if not scoreboard:
        print('ERROR: Could not fetch scoreboard')
        sys.exit(1)

    events = scoreboard.get('events', [])
    print(f'Found {len(events)} events on ESPN scoreboard')

    # Build map of "T1 vs T2" → ESPN event ID for finished matches
    espn_matches = {}
    for event in events:
        try:
            comp = event['competitions'][0]
            status = comp['status']['type']['completed']
            if not status:
                continue
            competitors = comp['competitors']
            home = normalise(competitors[0]['team']['displayName'])
            away = normalise(competitors[1]['team']['displayName'])
            eid = event['id']
            espn_matches[f'{home} vs {away}'] = eid
            espn_matches[f'{away} vs {home}'] = eid  # also index reversed
        except (KeyError, IndexError):
            continue

    print(f'{len(espn_matches)//2} finished matches found on ESPN')

    # Step 2: fetch each finished match summary
    match_cards = config.get('matchCards', {})
    errors = 0
    fetched = 0
    skipped = 0

    # Get all match keys from config (our canonical names)
    ai_ids = config.get('aiScoreIds', {})
    match_keys = list(ai_ids.keys()) if ai_ids else list(espn_matches.keys())

    # Deduplicate to canonical "T1 vs T2" only
    canonical = set()
    for k in espn_matches:
        parts = k.split(' vs ')
        if len(parts) == 2:
            fwd = k
            rev = f'{parts[1]} vs {parts[0]}'
            if fwd not in canonical and rev not in canonical:
                canonical.add(fwd)

    processed = 0
    for match_key in sorted(canonical):
        eid = espn_matches.get(match_key)
        if not eid:
            continue

        parts = match_key.split(' vs ')
        t1, t2 = parts[0], parts[1]
        processed += 1

        print(f'\n[{processed}] {match_key} (ESPN id: {eid})')
        url = SUMMARY_URL.format(eid)
        data = fetch_json(url)

        if not data:
            errors += 1
            continue

        cards = parse_summary(data, t1, t2)
        print(f'  ✓ {len(cards["home"])} home, {len(cards["away"])} away cards')
        if cards['home']:
            print(f'    Home: {[(c["name"], c["minute"], c["type"]) for c in cards["home"]]}')
        if cards['away']:
            print(f'    Away: {[(c["name"], c["minute"], c["type"]) for c in cards["away"]]}')

        match_cards[match_key] = {
            'homeTeam': t1, 'awayTeam': t2,
            'home': cards['home'], 'away': cards['away'],
            '_fetched': int(time.time() * 1000)
        }
        fetched += 1
        time.sleep(0.2)

    if not fetched and not errors:
        print('\nNo finished matches found — nothing to update')

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
