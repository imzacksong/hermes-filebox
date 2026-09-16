# Filebox — Explorer-style file browser for Hermes

A full file manager that lives inside the Hermes desktop app: tabbed panes,
a resizable quick-access sidebar, icon grid, search, rich previews, full edit
operations, LAN sharing, and an interactive 3D model viewer. Zero API keys,
zero model tokens.

## Features

- **Tabbed browsing** — `+` opens a tab at your current folder, `×` closes.
  Each tab keeps its own folder, history, selection, and search. Open tabs
  restore across launches.
- **Quick-access sidebar** — pin folders, browse drives with usage bars,
  drag the edge to resize (80–320px), `«` collapses it to a `»` rail.
  Width and state persist.
- **Everything persists** — sort order, tile size (S/M/L/XL), hidden-file
  toggle, pins, tabs, sidebar and preview sizes.
- **Preview pane** — image, audio, and video playback, PDFs, text with
  Read-full-file, and an ops bar (Copy path, Rename, Copy/Cut/Paste,
  Delete, Compress, Extract). Resizes by dragging, `×` to close.
- **Right-click menu** — the same ops on any tile, using Hermes's native
  menu components.
- **Full edit ops** — rename (inline), copy/cut/paste across tabs, two-click
  delete, zip compress, extract-here. Collisions auto-resolve, drive roots
  are refused, deletes are permanent (no recycle bin).
- **Video thumbnails** — real frames via ffmpeg (falls back to icons
  without it).
- **3D models** — shaded thumbnails plus an interactive STL/OBJ viewer:
  drag to rotate, `+`/`−` zoom, reset. No three.js, no new dependencies.
- **LAN sharing** — Send to… serves any file over your Wi-Fi with a link;
  optional one-click Tell button DMs a paired Hermes agent over the peer
  mesh (see below).

## Install

Tell your Hermes Agent to install it honestly. It's the easiest way.


```sh
git clone https://github.com/imzacksong/hermes-filebox.git
cp -r hermes-filebox ~/.hermes/plugins/filebox   # Windows: %LOCALAPPDATA%\hermes\plugins\filebox
```

1. Copy this folder into your Hermes plugins directory
   (`%LOCALAPPDATA%\hermes\plugins\` on Windows) and name it `filebox`.
2. (Optional, paired agents only) Copy `dashboard/peer.example.json` to
   `dashboard/peer.json` and fill in your peer slug, label, and agent name.
3. Enable it: `hermes plugins enable filebox`, then restart the gateway.
4. In the Hermes desktop app: Settings → Plugins → turn on **Filebox**, then
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

## Rich tiles & 3D

Video files get real frame thumbnails (ffmpeg grabs a frame ~10% in — needs
`ffmpeg`/`ffprobe` on PATH or video tiles fall back to icons). `.stl` and
`.obj` files get rendered 3D thumbnails, and opening one drops an interactive
viewer into the preview: drag to rotate, `+`/`−` to zoom, Reset view. Models
over ~96MB skip preview (Open them instead).

## Notes

- Media/PDF previews load straight from disk; if a preview ever shows
  "blocked", Open / reveal still work.
- Text preview shows the first 64KB with a **Read full file** option to 1MB.
