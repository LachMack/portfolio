#!/usr/bin/env python3
"""
Fetches card data from AiScore using Node.js to evaluate __NUXT__ data.
"""

import json, re, sys, os, time, subprocess
from pathlib import Path

CONFIG_PATH = os.environ.get('CONFIG_PATH', 'worldcup/wc2026-config.json')
SCRIPT_DIR = Path(__file__).parent
NODE_SCRIPT = SCRIPT_DIR / 'extract_cards.js'


def get_cards_via_node(url, t1, t2, debug=False):
    """Call Node.js script to fetch and parse NUXT data from AiScore."""
    args = ['node', str(NODE_SCRIPT), url, t1, t2]
    if debug:
        args.append('debug')
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=20)
        if debug and result.stderr:
            print(f'  DEBUG stderr:')
            for line in result.stderr.strip().split('\n'):
                print(f'    {line}')
        if result.stdout:
            data = json.loads(result.stdout)
            if 'error' in data:
                print(f'  Node error: {data["error"]}')
                return None
            return data
        return None
    except subprocess.TimeoutExpired:
        print(f'  Node timeout after 20s')
        return None
    except Exception as e:
        print(f'  Node call failed: {e}')
        return None


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
    print(f'Loading {CONFIG_PATH}...')
    with open(CONFIG_PATH) as f:
        config = json.load(f)

    ai_ids = config.get('aiScoreIds', {})
    if not ai_ids:
        print('No aiScoreIds in config')
        sys.exit(0)

    # Check Node.js is available
    try:
        node_ver = subprocess.run(['node', '--version'], capture_output=True, text=True, timeout=5)
        print(f'Node.js: {node_ver.stdout.strip()}')
    except Exception:
        print('ERROR: Node.js not available')
        sys.exit(1)

    if not NODE_SCRIPT.exists():
        print(f'ERROR: {NODE_SCRIPT} not found')
        sys.exit(1)

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

        is_debug = (i == 1 and os.environ.get("DEBUG_FIRST","0") == "1")
        data = get_cards_via_node(url, t1, t2, debug=is_debug)
        if data is None:
            errors += 1
            continue

        debug = data.get('debug', {})
        home_cards = data.get('home', [])
        away_cards = data.get('away', [])

        if not debug.get('hasNuxt'):
            print(f'  No NUXT data — skipping')
            skipped += 1
            continue

        print(f'  ✓ {len(home_cards)} home, {len(away_cards)} away cards (html: {debug.get("htmlLength",0):,})')
        if home_cards:
            print(f'    Home: {[(c["name"], c["minute"], c["type"]) for c in home_cards]}')
        if away_cards:
            print(f'    Away: {[(c["name"], c["minute"], c["type"]) for c in away_cards]}')

        match_cards[match_key] = {
            'homeTeam': t1, 'awayTeam': t2,
            'home': home_cards, 'away': away_cards,
            '_fetched': int(time.time() * 1000)
        }
        fetched += 1
        time.sleep(0.2)

    # Tally totals from per-match events
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
