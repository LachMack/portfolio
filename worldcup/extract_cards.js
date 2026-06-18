#!/usr/bin/env node
const https = require('https');
const url = process.argv[2];
const t1 = process.argv[3];
const t2 = process.argv[4];
const debug = process.argv[5] === 'debug';

if (!url) { process.stdout.write(JSON.stringify({error:'No URL'})); process.exit(1); }

function fetch(url) {
  return new Promise((resolve, reject) => {
    https.get(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html',
        'Connection': 'close',
      },
      timeout: 12000,
    }, (res) => {
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    }).on('error', reject).on('timeout', () => reject(new Error('timeout')));
  });
}

async function main() {
  let html;
  try { html = await fetch(url); }
  catch(e) { process.stdout.write(JSON.stringify({error: e.message})); return; }

  const nuxtMatch = html.match(/window\.__NUXT__=([\s\S]*?)\s*<\/script>/);
  if (!nuxtMatch) { process.stdout.write(JSON.stringify({error:'No __NUXT__'})); return; }

  let nuxtData;
  try {
    nuxtData = (new Function(`return ${nuxtMatch[1]}`))();
  } catch(e) {
    process.stdout.write(JSON.stringify({error:'eval: '+e.message})); return;
  }

  if (debug) {
    // Print top-level keys and structure to stderr for diagnosis
    function summarise(obj, depth, maxDepth) {
      if (depth > maxDepth || obj === null || obj === undefined) return String(obj);
      if (typeof obj !== 'object') return typeof obj + ':' + String(obj).slice(0,40);
      if (Array.isArray(obj)) return `Array[${obj.length}]` + (obj.length > 0 ? ' ' + summarise(obj[0], depth+1, maxDepth) : '');
      const keys = Object.keys(obj);
      return `{${keys.slice(0,8).map(k => k+':'+summarise(obj[k], depth+1, maxDepth)).join(', ')}${keys.length > 8 ? '...' : ''}}`;
    }
    process.stderr.write('NUXT top level: ' + summarise(nuxtData, 0, 1) + '\n');
    
    // Find all objects that might be events by searching for numeric keys that look like minutes
    // Also search for strings like 'yellow', 'red', 'card'
    function findCardRelated(obj, path, results) {
      if (!obj || typeof obj !== 'object' || results.length > 20) return;
      const str = JSON.stringify(obj).toLowerCase();
      if (str.includes('yellow') || str.includes('red card') || str.includes('incident')) {
        if (Object.keys(obj).length < 20) {
          results.push({path, obj: JSON.stringify(obj).slice(0,200)});
        }
      }
      if (Array.isArray(obj)) {
        obj.forEach((v,i) => findCardRelated(v, path+`[${i}]`, results));
      } else {
        Object.keys(obj).forEach(k => findCardRelated(obj[k], path+'.'+k, results));
      }
    }
    const cardRelated = [];
    findCardRelated(nuxtData, 'root', cardRelated);
    process.stderr.write('Card-related objects found: ' + cardRelated.length + '\n');
    cardRelated.slice(0,5).forEach(r => process.stderr.write('  '+r.path+': '+r.obj+'\n'));
  }

  // Search for incidents/events with card type indicators
  const homeCards = [], awayCards = [];
  const seen = new Set();

  // AiScore uses incident type IDs - common values:
  // 41=yellow, 42=red, 44=second yellow, 45=penalty, etc.
  // Also check string values
  const YELLOW = new Set([41, '41', 'yellow_card', 'Yellow Card', 'yellow', 'YC', 6]);
  const RED = new Set([42, '42', 'red_card', 'Red Card', 'red', 'RC', 44, '44', 7, 'second_yellow']);

  function walkForCards(obj, depth) {
    if (depth > 25 || !obj || typeof obj !== 'object') return;
    if (Array.isArray(obj)) { obj.forEach(v => walkForCards(v, depth+1)); return; }

    const keys = Object.keys(obj);
    // Check if this looks like an event/incident object
    const typeVal = obj.type ?? obj.incidentType ?? obj.incident_type ?? obj.eventType ?? obj.event_type ?? obj.typeId ?? obj.type_id;
    const isYellow = YELLOW.has(typeVal) || (typeof typeVal === 'string' && typeVal.toLowerCase().includes('yellow'));
    const isRed = RED.has(typeVal) || (typeof typeVal === 'string' && (typeVal.toLowerCase().includes('red') || typeVal.toLowerCase().includes('second')));

    if (isYellow || isRed) {
      // Try to get player name
      let name = null;
      const playerObj = obj.player ?? obj.Player ?? obj.playerInfo;
      if (playerObj) {
        name = playerObj.name ?? playerObj.fullName ?? playerObj.shortName ?? playerObj.player_name;
      }
      if (!name) {
        name = obj.playerName ?? obj.player_name ?? obj.name ?? obj.fullName;
      }
      if (!name || typeof name !== 'string' || name.length < 2) {
        keys.forEach(k => walkForCards(obj[k], depth+1));
        return;
      }

      // Get minute
      let minute = null;
      const timeVal = obj.minute ?? obj.min ?? obj.time ?? obj.elapsed ?? obj.matchTime ?? obj.match_time ?? obj.incidentTime;
      if (timeVal !== undefined && timeVal !== null) {
        minute = parseInt(String(timeVal).split('+')[0].split('.')[0]);
      }
      if (!minute || minute <= 0 || minute > 125) {
        keys.forEach(k => walkForCards(obj[k], depth+1));
        return;
      }

      const cardType = isRed ? 'red' : 'yellow';
      const key = name.slice(0,8)+'_'+minute+'_'+cardType;
      if (!seen.has(key)) {
        seen.add(key);
        // Determine home/away
        const isHome = obj.isHome ?? obj.is_home;
        const side = String(obj.team ?? obj.side ?? obj.teamId ?? '').toLowerCase();
        let away = false;
        if (isHome === false || isHome === 0) away = true;
        else if (side === 'away' || side === '0' || (t2 && side.includes(t2.toLowerCase().slice(0,4)))) away = true;
        
        const event = {name, minute, type: cardType};
        if (away) awayCards.push(event); else homeCards.push(event);
      }
    }

    keys.forEach(k => walkForCards(obj[k], depth+1));
  }

  walkForCards(nuxtData, 0);
  homeCards.sort((a,b) => a.minute-b.minute);
  awayCards.sort((a,b) => a.minute-b.minute);

  process.stdout.write(JSON.stringify({
    home: homeCards, away: awayCards,
    debug: {htmlLength: html.length, hasNuxt: true, totalEvents: homeCards.length+awayCards.length}
  }));
}

main().catch(e => process.stdout.write(JSON.stringify({error: e.message})));
