// Find & Replace logic for Miro
function escapeRegExp(string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function asRegex(find, { caseSensitive, wholeWord, regex }) {
  const flags = caseSensitive ? "g" : "gi";
  let pattern = regex ? find : escapeRegExp(find);
  if (wholeWord) pattern = `\\b${pattern}\\b`;
  return new RegExp(pattern, flags);
}

// Keep a small helper for card fields
function replaceInCard(card, re, replacement) {
  let total = 0;
  if (typeof card.title === "string") {
    const before = card.title;
    card.title = before.replace(re, () => { total++; return replacement; });
  }
  if (typeof card.description === "string") {
    const before = card.description;
    card.description = before.replace(re, () => { total++; return replacement; });
  }
  return total;
}

// Replace inside content-bearing items (text/sticky/shape).
// If preserveHtml is true we operate on the raw HTML string; otherwise strip tags.
function stripHtml(html) {
  const tmp = document.createElement("div");
  tmp.innerHTML = html;
  return tmp.textContent || tmp.innerText || "";
}

function insertAsHtml(originalHtml, re, replacement, preserveHtml) {
  if (preserveHtml) {
    // Operate on the raw HTML. This is simple and preserves tags,
    // but note it can affect attribute values if they match the regex.
    return originalHtml.replace(re, replacement);
  } else {
    // Replace in the plain text, then wrap back into <p> to be safe.
    const text = stripHtml(originalHtml);
    const replaced = text.replace(re, replacement);
    return `<p>${replaced.replace(/\n/g, "<br>")}</p>`;
  }
}

async function getTargetItems(selectionOnly) {
  if (selectionOnly) {
    const sel = await miro.board.getSelection();
    return sel;
  }
  // All items on the board
  const all = await miro.board.get(); // may be large; user can limit via selection
  return all;
}

function isSupported(item) {
  return ["text", "sticky_note", "shape", "card"].includes(item.type);
}

function getMatchesPreview(item, re, { preserveHtml }) {
  let sample = "";
  let count = 0;
  if (["text", "sticky_note", "shape"].includes(item.type)) {
    const hay = preserveHtml ? item.content : stripHtml(item.content || "");
    const matches = hay.match(re);
    count = matches ? matches.length : 0;
    sample = (hay || "").slice(0, 140);
  } else if (item.type === "card") {
    const hay = `${item.title || ""}\n${item.description || ""}`;
    const matches = hay.match(re);
    count = matches ? matches.length : 0;
    sample = hay.slice(0, 140);
  }
  return { count, sample };
}

async function doReplace(items, re, replacement, { preserveHtml }) {
  let totalReplacements = 0;
  let touched = 0;
  for (const item of items) {
    if (!isSupported(item)) continue;
    let changed = false;
    if (["text", "sticky_note", "shape"].includes(item.type)) {
      const before = item.content || "";
      const after = insertAsHtml(before, re, replacement, preserveHtml);
      if (after !== before) {
        item.content = after;
        changed = true;
        const matches = before.match(re);
        totalReplacements += matches ? matches.length : 0;
      }
    } else if (item.type === "card") {
      const added = replaceInCard(item, re, replacement);
      if (added > 0) {
        totalReplacements += added;
        changed = true;
      }
    }
    if (changed) {
      await item.sync();
      touched++;
    }
  }
  return { totalReplacements, touched };
}

function renderResults(list, totals) {
  const el = document.getElementById("results");
  el.innerHTML = "";
  if (list.length === 0) {
    el.innerHTML = `<div class="small">No matches.</div>`;
    return;
  }
  list.forEach((r) => {
    const div = document.createElement("div");
    div.className = "item";
    div.innerHTML = `<div><strong>${r.type}</strong> <span class="badge">matches: <span class="counter">${r.count}</span></span></div>
      <div class="small">${r.sample.replace(/[<>&]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c]))}...</div>`;
    el.appendChild(div);
  });
  const footer = document.createElement("div");
  footer.className = "small";
  footer.style.marginTop = "8px";
  footer.innerHTML = `<strong>Total matches:</strong> <span class="counter">${totals.matches}</span> across <span class="counter">${totals.items}</span> items.`;
  el.appendChild(footer);
}

async function preview() {
  const find = document.getElementById("find").value;
  const selectionOnly = document.getElementById("opt-selection").checked;
  const caseSensitive = document.getElementById("opt-case").checked;
  const wholeWord = document.getElementById("opt-whole").checked;
  const regex = document.getElementById("opt-regex").checked;
  const preserveHtml = document.getElementById("opt-html").checked;

  if (!find) {
    document.getElementById("results").innerHTML = '<div class="small">Enter something to find.</div>';
    return;
  }

  const re = asRegex(find, { caseSensitive, wholeWord, regex });
  const items = (await getTargetItems(selectionOnly)).filter(isSupported);

  const rows = [];
  let matches = 0;
  for (const it of items) {
    const { count, sample } = getMatchesPreview(it, re, { preserveHtml });
    if (count > 0) {
      rows.push({ id: it.id, type: it.type, count, sample });
      matches += count;
    }
  }
  renderResults(rows, { matches, items: rows.length });
}

async function replaceAll() {
  const find = document.getElementById("find").value;
  const replacement = document.getElementById("replace").value ?? "";
  const selectionOnly = document.getElementById("opt-selection").checked;
  const caseSensitive = document.getElementById("opt-case").checked;
  const wholeWord = document.getElementById("opt-whole").checked;
  const regex = document.getElementById("opt-regex").checked;
  const preserveHtml = document.getElementById("opt-html").checked;

  if (!find) {
    document.getElementById("results").innerHTML = '<div class="small">Enter something to find.</div>';
    return;
  }

  const re = asRegex(find, { caseSensitive, wholeWord, regex });
  const items = (await getTargetItems(selectionOnly)).filter(isSupported);

  const { totalReplacements, touched } = await doReplace(items, re, replacement, { preserveHtml });
  document.getElementById("results").innerHTML = `<div class="small">Replaced <span class="counter">${totalReplacements}</span> occurrence(s) across <span class="counter">${touched}</span> item(s).</div>`;
}

document.getElementById("preview").addEventListener("click", preview);
document.getElementById("replace-all").addEventListener("click", replaceAll);
