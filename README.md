# Filebox — Explorer-style file browser for Hermes

Quick access, breadcrumbs, icon grid (S/M/L/XL), search, and a preview pane
with image / audio / video / PDF / text preview. Multiple folders stay open
in tabs (`+` to open, `×` to close). The quick-access sidebar resizes by
dragging its right edge and collapses with the `«` button (`»` rail to
bring it back). Sort order, tile size, sidebar width, hidden-file
toggle, pins, open tabs, and the active tab are all remembered between
launches. Select a file → **Send to…**
to share it over your home LAN, with an optional one-click heads-up to a
paired Hermes agent over the peer mesh.

## Install

1. Copy the `filebox` folder into your Hermes plugins directory
   (`%LOCALAPPDATA%\hermes\plugins\` on Windows, next to `sysmon`, `pals`, …).
2. Enable it: `hermes plugins enable filebox` (then restart the gateway).
3. In the Hermes desktop app: Settings → Plugins → turn on **Filebox**, then
   reload (⌘K → Reload). The Explorer pane starts collapsed — open it from
   the **Explorer** chip bottom-right. Drag it to the right side and close the
   built-in files pane if you want it as your sidebar.

## Sending files to someone on your LAN

Select a file → **Send to…** → share link like
`http://<your-lan-ip>:8077/dl/…`. They open it in any browser on the same
Wi-Fi and download. **Copy link** / **Stop sharing** manage it. First share
may trigger a Windows Firewall prompt for Python — allow it on private
networks or nobody can reach you. Files only, links live until revoked or
the gateway restarts.

## The "Tell <name>" button (paired agents only)

If you and one other person both run Hermes and have paired over the peer
mesh (`hermes peer ...`), the button DMs their agent with the file name and
link so it can pass it on / download it with approval.

To use it, edit `dashboard/peer.json`:

```json
{
  "peer": "zack",
  "label": "Zack",
  "agent": "Tala",
  "thread": "tala-thread.md"
}
```

- `peer` — the peer slug on YOUR machine (`hermes peer list`).
- `label` — the human's name (button reads "Tell Zack").
- `agent` — their agent's name (status reads "Tala will pass it to Zack").
- `thread` — transcript filename, written next to the plugin folder
  (`%LOCALAPPDATA%\hermes\plugins\filebox\`), readable any time.

No `peer.json` = defaults for the original machine (Zack → Nina via Milo).
If you don't have a paired agent, ignore the button — the copy-link flow
needs nothing.

## Editing files

Select anything and the preview panel grows an ops bar up top: **Copy path**,
**Rename** (inline, Enter to save), **Copy** / **Cut** / **Paste**,
**Delete** (second click confirms), **Compress**, and **Extract here** on
zips. Right-click any tile for the same ops in a context menu (paste targets
the folder you clicked, or the current folder). The preview panel resizes by
dragging its top edge and closes with the `×` in the ops bar (clicking the
file again still toggles it). The bottom row stays lean:
Open, Send, Show in Explorer.
auto-resolve (`file (2).txt`). Deletes are permanent (no recycle bin) and
drive roots are refused — you can't nuke `C:\` from here.

## Notes

- Media/PDF previews load straight from disk; if a preview ever shows
  "blocked", Open / reveal still work.
- Text preview shows the first 64KB with a **Read full file** option to 1MB.
