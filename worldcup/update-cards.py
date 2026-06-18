#!/usr/bin/env python3
"""
Fetches card data from AiScore for finished WC2026 matches.
Updates wc2026-config.json with per-match events + team totals.

AiScore uses SVG icon sprites for card types:
  <use xlink:href="#icon-yellow-card">  → yellow card
  <use xlink:href="#icon-red-card">     → red card
  <use xlink:href="#icon-second-yellow-card"> → second yellow (= red)

Each event row structure (from DOM inspection):
  <span class="text ml-xs">PLAYER NAME</span>
  <svg ...><use xlink:href="#icon-yellow-card"></svg>
  [minute in nearby text]
"""

import json, re, sys, os, time, socket
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

CONFIG_PATH = os.environ.get('CONFIG_PATH', 'worldcup/wc2026-config.json')
TIMEOUT = 10

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
    """
    Parse card events using AiScore's SVG icon structure.

    The timeline HTML looks like:
      <span class="text ml-xs" ...>César Montes</span>
      <svg ...><use xlink:href="#icon-red-card" ...></use></svg>
      ... 90+2' ...

    Or reversed for away events:
      <svg ...><use xlink:href="#icon-yellow-card"></use></svg>
      <span class="text ml-xs" ...>Brian Gutierrez</span>
      ... 17' ...

    We find each card icon, then look nearby for:
    1. The player name in a <span class="text ..."> element
    2. The minute from the surrounding text
    3. Home vs away from the position/class context
    """
    home_cards = []
    away_cards = []

    # Find all card icon occurrences
    # Pattern: xlink:href="#icon-yellow-card" or #icon-red-card or #icon-second-yellow-card
    card_re = re.compile(
        r'xlink:href=["\']#icon-(yellow-card|red-card|second-yellow-card)["\']',
        re.I
    )

    for m in card_re.finditer(html):
        icon_type = m.group(1)
        card_type = 'red' if 'red' in icon_type or 'second' in icon_type else 'yellow'

        # Search window: 800 chars before and 400 chars after the icon
        ctx_start = max(0, m.start() - 800)
        ctx_end = min(len(html), m.end() + 400)
        context = html[ctx_start:ctx_end]

        # ── Extract player name ──────────────────────────────────────
        # AiScore wraps player names in <span class="text ml-xs"> or similar
        name = None
        name_re = re.compile(
            r'<span[^>]+class=["\'][^"\']*\btext\b[^"\']*["\'][^>]*>([^<]{3,45})</span>',
            re.I
        )
        # Prefer the closest name match (last one before icon, or first after)
        name_matches = list(name_re.finditer(context))
        icon_pos = m.start() - ctx_start  # position of icon within context

        if name_matches:
            # Find closest match to icon position
            best = min(name_matches, key=lambda x: abs(x.start() - icon_pos))
            candidate = best.group(1).strip()
            # Validate: looks like a person name (Title Case, no HTML, reasonable length)
            if (3 <= len(candidate) <= 45 and
                not re.search(r'[<>&]', candidate) and
                re.search(r'[A-Za-záéíóúàèìòùüñčšžćđ]', candidate)):
                name = candidate

        if not name:
            # Fallback: look for capitalised words near the icon
            text = re.sub(r'<[^>]+>', ' ', context)
            text = re.sub(r'\s+', ' ', text)
            name_fallback = re.search(
                r'([A-ZÁÉÍÓÚÀÈÌÒÙÜÑČŠŽĆĐ][a-záéíóúàèìòùüñčšžćđ\-]+(?:\s+[A-ZÁÉÍÓÚÀÈÌÒÙÜÑČŠŽĆĐ][a-záéíóúàèìòùüñčšžćđ\-]+)+)',
                text
            )
            if name_fallback:
                name = name_fallback.group(1).strip()

        if not name:
            continue

        # ── Extract minute ───────────────────────────────────────────
        text = re.sub(r'<[^>]+>', ' ', context)
        min_match = re.search(r'(\d{1,3})(?:\+\d+)?\s*\'', text)
        if not min_match:
            continue
        minute = int(min_match.group(1))
        if minute > 125:
            continue

        # ── Determine home vs away ───────────────────────────────────
        # AiScore shows home team events on the left (icon after name)
        # and away team events on the right (icon before name)
        # The icon position relative to the name span tells us which side
        pre_icon = context[:icon_pos]

        # Check for 'right' class hint in containing divs
        is_away = bool(re.search(r'class=["\'][^"\']*\bright\b[^"\']*["\']', pre_icon[-300:], re.I))

        # Secondary check: if player name appears BEFORE the icon, it's home (name then card)
        # If player name appears AFTER the icon, it's away (card then name)
        if not is_away and name_matches:
            best = min(name_matches, key=lambda x: abs(x.start() - icon_pos))
            if best.start() > icon_pos:
                is_away = True  # name is after icon → away

        event = {'name': name, 'minute': minute, 'type': card_type}
        if is_away:
            away_cards.append(event)
        else:
            home_cards.append(event)

    # Deduplicate by (name prefix, minute, type)
    def dedup(cards):
        seen, out = set(), []
        for c in sorted(cards, key=lambda x: x['minute']):
            k = (c['name'][:6], c['minute'], c['type'])
            if k not in seen:
                seen.add(k)
                out.append(c)
        return out

    result = {'home': dedup(home_cards), 'away': dedup(away_cards)}

    # Sanity check: if we found many more than expected, something went wrong
    total = len(result['home']) + len(result['away'])
    if total > 20:
        print(f'  WARNING: {total} cards found — possible parsing error, capping at 20')
        result['home'] = result['home'][:10]
        result['away'] = result['away'][:10]

    return result


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
        print('No aiScoreIds in config — nothing to do')
        sys.exit(0)

    print(f'Found {len(ai_ids)} match IDs in config')

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
        if not html:
            errors += 1
            continue

        if len(html) < 1000:
            print(f'  Too short ({len(html)} chars) — skipping')
            skipped += 1
            continue

        # Check if finished
        is_finished = bool(re.search(r'Full\s*Time|>FT\s*\d|\bFT\b.*\d-\d', html))
        if not is_finished:
            print(f'  Not finished — skipping')
            skipped += 1
            continue

        cards = parse_cards(html, t1, t2)
        print(f'  ✓ {len(cards["home"])} home cards, {len(cards["away"])} away cards')
        if cards["home"]:
            print(f'    Home: {[(c["name"], c["minute"], c["type"]) for c in cards["home"]]}')
        if cards["away"]:
            print(f'    Away: {[(c["name"], c["minute"], c["type"]) for c in cards["away"]]}')

        match_cards[match_key] = {
            'homeTeam': t1, 'awayTeam': t2,
            'home': cards['home'], 'away': cards['away'],
            '_fetched': int(time.time() * 1000)
        }
        fetched += 1
        time.sleep(0.3)

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
