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
    """Extract card events from ESPN match summary JSON.

    ESPN uses boolean flags on detail objects:
      detail.redCard = True  → red card
      detail.yellowCard = True (implied by type.text) → yellow
    Each detail has: clock.displayValue, participants[0].athlete.displayName, team.id
    home team = competitors[0]
    """
    home_cards, away_cards = [], []

    try:
        comp = data['header']['competitions'][0]
        home_id = str(comp['competitors'][0]['team']['id'])
        details = comp.get('details', [])
    except (KeyError, IndexError):
        return {'home': [], 'away': []}

    # Also check keyEvents which has fuller card data
    key_events = data.get('keyEvents', [])
    card_events = []

    # Primary: header > competitions > details (has boolean redCard flag)
    for d in details:
        is_red = d.get('redCard', False)
        # Yellow card: not a scoring play, not red card, has participants
        # ESPN doesn't have a yellowCard boolean in details — use type.text from keyEvents
        if is_red:
            card_type = 'red'
        else:
            continue  # handle yellows via keyEvents below

        participants = d.get('participants', [])
        if not participants:
            continue
        name = participants[0].get('athlete', {}).get('displayName', '')
        if not name:
            continue

        clock = d.get('clock', {})
        minute_str = clock.get('displayValue', '0')
        try:
            minute = int(minute_str.replace("'", '').split('+')[0].strip())
        except (ValueError, AttributeError):
            continue

        team_id = str(d.get('team', {}).get('id', ''))
        event = {'name': name, 'minute': minute, 'type': card_type}
        if team_id == home_id:
            home_cards.append(event)
        else:
            away_cards.append(event)

    # keyEvents has both yellow and red cards with type.id 93=red, 94=yellow
    for ke in key_events:
        type_id = str(ke.get('type', {}).get('id', ''))
        type_text = ke.get('type', {}).get('text', '').lower()
        is_yellow = type_id == '94' or 'yellow card' in type_text
        is_red_ke = type_id == '93' or type_text == 'red card'
        if not is_yellow and not is_red_ke:
            continue

        card_type = 'red' if is_red_ke else 'yellow'
        participants = ke.get('participants', [])
        if not participants:
            continue
        name = participants[0].get('athlete', {}).get('displayName', '')
        if not name:
            continue

        clock = ke.get('clock', {})
        minute_str = clock.get('displayValue', '0')
        try:
            minute = int(minute_str.replace("'", '').split('+')[0].strip())
        except (ValueError, AttributeError):
            continue

        team_id = str(ke.get('team', {}).get('id', ''))
        event = {'name': name, 'minute': minute, 'type': card_type}
        if team_id == home_id:
            home_cards.append(event)
        else:
            away_cards.append(event)

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

        # Debug first match - print raw structure
        if processed == 1:
            import json as _json
            comp = data.get('header',{}).get('competitions',[{}])[0]
            details = comp.get('details',[])
            print(f'  DEBUG: details count={len(details)}')
            if details:
                print(f'  DEBUG: first detail={_json.dumps(details[0], ensure_ascii=False)[:300]}')
            # Also check gamepackageJSON key
            gp = data.get('gamepackageJSON',{})
            if gp:
                print(f'  DEBUG: gamepackageJSON keys={list(gp.keys())[:10]}')
            # Check all top-level keys
            print(f'  DEBUG: top-level keys={list(data.keys())}')
            # Look for plays
            plays = data.get('plays',[])
            print(f'  DEBUG: plays count={len(plays)}')
            if plays:
                print(f'  DEBUG: first play={_json.dumps(plays[0], ensure_ascii=False)[:300]}')

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
