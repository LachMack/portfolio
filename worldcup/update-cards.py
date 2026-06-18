#!/usr/bin/env python3
"""
Fetches card data from AiScore for all finished WC2026 matches
and updates wc2026-config.json with per-match events + team totals.
"""

import json, re, sys, os, time
from urllib.request import urlopen, Request
from urllib.error import URLError

CONFIG_PATH = os.environ.get('CONFIG_PATH', 'worldcup/wc2026-config.json')

# ── Name map: AiScore display name → our sweep name ──────────────────
NAME_MAP = {
    'Mexico': 'Mexico', 'South Africa': 'South Africa',
    'South Korea': 'South Korea', 'Korea Republic': 'South Korea',
    'Czechia': 'Czechia', 'Czech Republic': 'Czechia',
    'Canada': 'Canada', 'Bosnia & Herzegovina': 'Bosnia & Herzegovina',
    'Bosnia and Herzegovina': 'Bosnia & Herzegovina',
    'USA': 'USA', 'United States': 'USA',
    'Paraguay': 'Paraguay', 'Qatar': 'Qatar', 'Switzerland': 'Switzerland',
    'Brazil': 'Brazil', 'Morocco': 'Morocco', 'Scotland': 'Scotland',
    'Haiti': 'Haiti', 'Australia': 'Australia', 'Türkiye': 'Türkiye',
    'Turkey': 'Türkiye', 'Germany': 'Germany',
    "Côte d'Ivoire": 'Ivory Coast', "Cote d'Ivoire": 'Ivory Coast',
    'Ivory Coast': 'Ivory Coast',
    'Netherlands': 'Netherlands', 'Japan': 'Japan',
    'Sweden': 'Sweden', 'Tunisia': 'Tunisia',
    'Spain': 'Spain', 'Cabo Verde': 'Cape Verde', 'Cape Verde': 'Cape Verde',
    'Belgium': 'Belgium', 'Egypt': 'Egypt',
    'Saudi Arabia': 'Saudi Arabia', 'Uruguay': 'Uruguay',
    'Iran': 'Iran', 'IR Iran': 'Iran',
    'New Zealand': 'New Zealand', 'France': 'France',
    'Senegal': 'Senegal', 'Norway': 'Norway', 'Iraq': 'Iraq',
    'Argentina': 'Argentina', 'Algeria': 'Algeria',
    'Austria': 'Austria', 'Jordan': 'Jordan',
    'Portugal': 'Portugal',
    'DR Congo': 'DR Congo',
    'Democratic Republic of the Congo': 'DR Congo',
    'Congo DR': 'DR Congo',
    'England': 'England', 'Croatia': 'Croatia',
    'Ghana': 'Ghana', 'Panama': 'Panama',
    'Colombia': 'Colombia', 'Uzbekistan': 'Uzbekistan',
    'Ecuador': 'Ecuador', 'Curaçao': 'Curaçao', 'Curacao': 'Curaçao',
}

def fetch_html(url, retries=3):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=15) as r:
                return r.read().decode('utf-8', errors='replace')
        except Exception as e:
            print(f'  Attempt {attempt+1} failed: {e}')
            if attempt < retries - 1:
                time.sleep(2)
    return None

def parse_cards(html, t1, t2):
    """
    Parse yellow/red card events from AiScore match page HTML.
    Returns {home: [{name, minute, type}], away: [...]}
    
    AiScore timeline structure (from inspecting Mexico vs SA):
    Events appear as rows with:
    - img src containing 'yellow_card' or 'red_card' 
    - nearby text with player name and minute (e.g. "Brian Gutierrez\n17'")
    Home events are in left-side divs, away in right-side divs.
    """
    home_cards, away_cards = [], []
    
    # Strategy: find img tags with card indicators, then extract context
    # Pattern: img src with yellow/red, nearby minute pattern, nearby player name
    
    # Split into event blocks - AiScore wraps each timeline event
    # Look for the main event section between score display and HT/FT markers
    
    # Find card images and their surrounding context (±500 chars)
    img_pattern = re.compile(r'<img[^>]+src=["\']([^"\']*(?:yellow|red)[^"\']*)["\'][^>]*>', re.I)
    
    for m in img_pattern.finditer(html):
        src = m.group(1).lower()
        is_yellow = 'yellow' in src
        is_red = 'red' in src or 'second' in src
        if not is_yellow and not is_red:
            continue
        card_type = 'red' if is_red else 'yellow'
        
        # Get surrounding context (500 chars before the img tag)
        start = max(0, m.start() - 500)
        context = html[start:m.end() + 200]
        
        # Strip HTML tags for text parsing
        text = re.sub(r'<[^>]+>', ' ', context)
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Find minute pattern
        min_match = re.search(r'(\d{1,3})(?:\+\d+)?\s*\'', text)
        if not min_match:
            continue
        minute = int(min_match.group(1))
        
        # Extract player name: look for capitalized words near the minute
        # Remove the minute and common non-name words
        cleaned = re.sub(r'\d{1,3}(?:\+\d+)?\s*\'', '', text)
        cleaned = re.sub(r'\b(In|Out|Assist|Goal|Corner|HT|FT|Substitution|Foul)\b', '', cleaned, flags=re.I)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        # Find capitalized name (2+ words or single word with capital)
        name_match = re.search(r'([A-ZÁÉÍÓÚÀÈÌÒÙÜÑČŠŽ][a-záéíóúàèìòùüñčšž]+(?:\s+[A-ZÁÉÍÓÚÀÈÌÒÙÜÑČŠŽ][a-záéíóúàèìòùüñčšž]+)+)', cleaned)
        if not name_match:
            continue
        name = name_match.group(1).strip()
        if len(name) < 3 or len(name) > 50:
            continue
        
        # Determine home or away by checking which team name appears nearby
        # and by position (home events tend to appear before the score, away after)
        context_text = re.sub(r'<[^>]+>', ' ', context)
        
        # Check if t1 (home) team name appears closer than t2 (away)
        t1_pos = context_text.find(t1)
        t2_pos = context_text.find(t2)
        
        event = {'name': name, 'minute': minute, 'type': card_type}
        
        # Use div class hints if available
        pre_context = html[start:m.start()]
        if re.search(r'class=["\'][^"\']*right[^"\']*["\']', pre_context[-200:], re.I):
            away_cards.append(event)
        elif re.search(r'class=["\'][^"\']*left[^"\']*["\']', pre_context[-200:], re.I):
            home_cards.append(event)
        elif t1_pos >= 0 and (t2_pos < 0 or t1_pos < t2_pos):
            home_cards.append(event)
        elif t2_pos >= 0:
            away_cards.append(event)
        else:
            # Default: use position relative to score block
            home_cards.append(event)
    
    # Deduplicate by (name, minute, type)
    def dedup(cards):
        seen, result = set(), []
        for c in cards:
            key = (c['name'], c['minute'], c['type'])
            if key not in seen:
                seen.add(key)
                result.append(c)
        return sorted(result, key=lambda x: x['minute'])
    
    return {'home': dedup(home_cards), 'away': dedup(away_cards)}


def main():
    # Load current config
    print(f'Loading {CONFIG_PATH}...')
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    
    ai_ids = config.get('aiScoreIds', {})
    if not ai_ids:
        print('No aiScoreIds in config — nothing to do')
        sys.exit(0)
    
    # Determine which matches are finished (have scores in OFB data or manual)
    # For the GitHub Action we'll just try all matches and skip if page says "upcoming"
    
    match_cards = config.get('matchCards', {})
    card_totals = {}
    errors = 0
    fetched = 0
    skipped = 0
    
    for match_key, aid in ai_ids.items():
        parts = match_key.split(' vs ')
        if len(parts) != 2:
            continue
        t1, t2 = parts
        
        # Build URL slug
        slug = match_key.lower()
        slug = slug.replace(' vs ', '-')
        for old, new in [('ü','u'),('ç','c'),('é','e'),('è','e'),
                         ('ã','a'),('ó','o'),('&','and'),("'",'')]:
            slug = slug.replace(old, new)
        slug = re.sub(r'[^a-z0-9-]', '-', slug)
        slug = re.sub(r'-+', '-', slug).strip('-')
        
        url = f'https://m.aiscore.com/match-{slug}/{aid}'
        print(f'Fetching {match_key}...')
        
        html = fetch_html(url)
        if not html:
            print(f'  FAILED to fetch')
            errors += 1
            continue
        
        # Check if match is finished
        if 'Full Time' not in html and 'FT' not in html:
            print(f'  Skipping — not finished yet')
            skipped += 1
            continue
        
        cards = parse_cards(html, t1, t2)
        total_cards = len(cards['home']) + len(cards['away'])
        print(f'  Found {len(cards["home"])} home, {len(cards["away"])} away cards')
        
        match_cards[match_key] = {
            'homeTeam': t1,
            'awayTeam': t2,
            'home': cards['home'],
            'away': cards['away'],
            '_fetched': int(time.time() * 1000)
        }
        fetched += 1
        time.sleep(0.5)  # be polite
    
    # Tally card totals from match events
    for mc in match_cards.values():
        t1 = mc['homeTeam']
        t2 = mc['awayTeam']
        if t1 not in card_totals:
            card_totals[t1] = {'yellow': 0, 'red': 0}
        if t2 not in card_totals:
            card_totals[t2] = {'yellow': 0, 'red': 0}
        for e in mc.get('home', []):
            if e['type'] == 'red':
                card_totals[t1]['red'] += 1
            else:
                card_totals[t1]['yellow'] += 1
        for e in mc.get('away', []):
            if e['type'] == 'red':
                card_totals[t2]['red'] += 1
            else:
                card_totals[t2]['yellow'] += 1
    
    card_totals['_updated'] = int(time.time() * 1000)
    
    # Update config
    config['matchCards'] = match_cards
    config['cardTotals'] = card_totals
    
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    print(f'\nDone: {fetched} fetched, {skipped} skipped, {errors} errors')
    total_y = sum(v.get('yellow',0) for k,v in card_totals.items() if k != '_updated')
    total_r = sum(v.get('red',0) for k,v in card_totals.items() if k != '_updated')
    print(f'Card totals: {total_y} yellows, {total_r} reds across {len(match_cards)} matches')

if __name__ == '__main__':
    main()
