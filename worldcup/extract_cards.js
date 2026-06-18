#!/usr/bin/env node
/**
 * Fetches AiScore match pages and extracts card events from __NUXT__ data.
 * Called by update-cards.py via subprocess.
 * Usage: node extract_cards.js <url> <t1> <t2>
 * Outputs JSON to stdout.
 */

const https = require('https');
const url = process.argv[2];
const t1 = process.argv[3];
const t2 = process.argv[4];

if (!url) {
  process.stdout.write(JSON.stringify({error: 'No URL provided'}));
  process.exit(1);
}

function fetch(url) {
  return new Promise((resolve, reject) => {
    const options = {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html',
        'Connection': 'close',
      },
      timeout: 12000,
    };
    https.get(url, options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => resolve(data));
    }).on('error', reject).on('timeout', () => reject(new Error('timeout')));
  });
}

async function main() {
  let html;
  try {
    html = await fetch(url);
  } catch(e) {
    process.stdout.write(JSON.stringify({error: e.message}));
    process.exit(0);
  }

  if (!html || html.length < 1000) {
    process.stdout.write(JSON.stringify({error: 'Too short: ' + html.length}));
    process.exit(0);
  }

  // Find and execute the __NUXT__ function
  const nuxtMatch = html.match(/window\.__NUXT__=([\s\S]*?)(?=\n?<\/script>)/);
  if (!nuxtMatch) {
    process.stdout.write(JSON.stringify({error: 'No __NUXT__ found'}));
    process.exit(0);
  }

  let nuxtData;
  try {
    // Execute the NUXT function in a sandboxed context
    const fn = new Function(`return ${nuxtMatch[1]}`);
    nuxtData = fn();
  } catch(e) {
    process.stdout.write(JSON.stringify({error: 'NUXT eval failed: ' + e.message}));
    process.exit(0);
  }

  // Walk the data looking for card events
  // Card type IDs used by sports data: 41=yellow, 42=red, 44=second yellow
  const YELLOW_TYPES = new Set([41, '41', 'yellow', 'Yellow Card', 'YC']);
  const RED_TYPES = new Set([42, '42', 44, '44', 'red', 'Red Card', 'RC', 'Second Yellow']);

  const homeCards = [];
  const awayCards = [];
  const seen = new Set();

  function walk(obj, depth) {
    if (depth > 20 || !obj || typeof obj !== 'object') return;
    if (Array.isArray(obj)) {
      obj.forEach(item => walk(item, depth + 1));
      return;
    }

    const keys = Object.keys(obj);
    // Look for event-like objects with type + player + minute
    const hasType = keys.some(k => ['type', 'event_type', 'eventType', 'incidentType', 'incident_type'].includes(k));
    const hasTime = keys.some(k => ['minute', 'min', 'time', 'matchTime', 'match_time', 'elapsed'].includes(k));
    const hasPlayer = keys.some(k => ['player', 'name', 'playerName', 'player_name', 'fullName'].includes(k));

    if (hasType && (hasTime || hasPlayer)) {
      // Get type value
      const typeVal = obj.type ?? obj.event_type ?? obj.eventType ?? obj.incidentType ?? obj.incident_type;
      const isYellow = YELLOW_TYPES.has(typeVal) || (typeof typeVal === 'string' && typeVal.toLowerCase().includes('yellow'));
      const isRed = RED_TYPES.has(typeVal) || (typeof typeVal === 'string' && (typeVal.toLowerCase().includes('red') || typeVal.toLowerCase().includes('second')));

      if (isYellow || isRed) {
        // Get player name
        let name = null;
        const nameKeys = ['player', 'name', 'playerName', 'player_name', 'fullName'];
        for (const k of nameKeys) {
          if (obj[k] && typeof obj[k] === 'string' && obj[k].length > 2) {
            name = obj[k];
            break;
          }
          // Sometimes player is a nested object
          if (obj[k] && typeof obj[k] === 'object') {
            const nested = obj[k];
            const nestedName = nested.name ?? nested.fullName ?? nested.player_name ?? nested.shortName;
            if (nestedName && typeof nestedName === 'string' && nestedName.length > 2) {
              name = nestedName;
              break;
            }
          }
        }

        // Get minute
        let minute = null;
        const timeKeys = ['minute', 'min', 'time', 'matchTime', 'match_time', 'elapsed'];
        for (const k of timeKeys) {
          if (obj[k] !== undefined) {
            const parsed = parseInt(String(obj[k]).split('+')[0].split('.')[0]);
            if (!isNaN(parsed) && parsed > 0 && parsed <= 125) {
              minute = parsed;
              break;
            }
          }
        }

        if (name && minute) {
          const cardType = isRed ? 'red' : 'yellow';
          const key = `${name.slice(0,6)}_${minute}_${cardType}`;
          if (!seen.has(key)) {
            seen.add(key);
            // Determine home/away
            const teamVal = String(obj.team ?? obj.teamId ?? obj.team_id ?? obj.side ?? obj.isHome ?? '').toLowerCase();
            const isAway = teamVal === 'away' || teamVal === 'false' || teamVal === '0' ||
                           (t2 && teamVal.includes(t2.toLowerCase().slice(0,4)));
            const event = {name, minute, type: cardType};
            if (isAway) awayCards.push(event);
            else homeCards.push(event);
          }
        }
      }
    }

    keys.forEach(k => walk(obj[k], depth + 1));
  }

  walk(nuxtData, 0);

  // Sort by minute
  homeCards.sort((a,b) => a.minute - b.minute);
  awayCards.sort((a,b) => a.minute - b.minute);

  process.stdout.write(JSON.stringify({
    home: homeCards,
    away: awayCards,
    debug: {
      htmlLength: html.length,
      hasNuxt: true,
      totalEvents: homeCards.length + awayCards.length,
    }
  }));
}

main().catch(e => {
  process.stdout.write(JSON.stringify({error: e.message}));
  process.exit(0);
});
