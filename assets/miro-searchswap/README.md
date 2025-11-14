
# Miro Find & Replace (Selection-aware)

A tiny Miro Web SDK v2 app that adds **Find & Replace** to boards, with an option to search **only within the current selection**.

## Features
- Find & Replace across **Text**, **Sticky notes**, **Shapes** (`content`), and **Cards** (`title` + `description`).
- **Selection only** toggle — operate just on the user's current selection.
- Options: **case-sensitive**, **whole word**, **regex**, and **preserve HTML** (operate on the raw HTML of `content` fields).
- Preview matches before replacing. Counts and per-item snippets included.
- Uses `item.sync()` to persist updates (per Miro SDK).

## Quick start
1. Create a **Developer team** in Miro and **Create new app** (Settings → Your apps).
2. Set the **App URL** to your hosted `index.html` (or run locally with a tunnel like `ngrok`).
3. Grant scopes: `boards:read` and `boards:write`.
4. Upload your app icons (optional), then **Install** the app to a board.
5. Click the app icon → panel opens → run Find/Replace.

> Script tag (SDK v2): `https://miro.com/app/static/sdk/v2/miro.js`.

## Local dev
Any static server works:
```bash
# from this folder
python3 -m http.server 5173
# or: npx http-server -p 5173
```
Then set the **App URL** to your tunnel (e.g. `https://xyz.ngrok.app/index.html`).

## Code map
- **index.html / index.js** — wires the toolbar icon (`icon:click`) to open `panel.html`.
- **panel.html / panel.js** — the UI and logic.
  - `miro.board.getSelection()` when "Selection only" is ticked, else `miro.board.get()`.
  - Updates require `await item.sync()`.

## Notes
- For content-bearing items (Text/Sticky/Shape), we can either:
  - Replace in the raw **HTML** string (`preserve HTML` – default), or
  - Strip tags → replace in **plain text** → rewrap (safer if you worry about hitting attributes).
- For **Cards**, we replace in both `title` and `description`.
- Large boards: prefer **Selection only** for speed.

## References
- Web SDK script tag & quickstart: developers.miro.com (see **Build a Web SDK app** and **Add drag & drop** code snippets).
- **Interact with boards and items** / `board.get()`.
- **Update and sync item properties** — use `item.sync()` to persist changes.
- **Board UI** — `icon:click` and opening panels.

