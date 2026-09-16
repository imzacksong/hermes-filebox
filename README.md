# Filebox — Explorer-style file browser for Hermes

Quick access, breadcrumbs, icon grid (S/M/L/XL), search, and a preview pane
with image / audio / video / PDF / text preview. Multiple folders stay open
in tabs (`+` to open, `×` to close). The quick-access sidebar resizes by
dragging its right edge and collapses with the `«` button (`»` rail to
bring it back). Sort order, tile size, sidebar width, hidden-file
toggle, pins, open tabs, and the active tab are all remembered between
launches.

## Features

- **Tabbed browsing** — `+` opens a tab at your current folder, `×` closes.
  Each tab keeps its own folder, history, selection, and search. Open tabs
  restore across launches.
- **Drag and drop** — drag any tile into a folder (or another tab's folder)
  to move it. Same-folder drops are ignored, collisions auto-resolve.
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
  delete to the recycle bin, zip compress, extract-here. Drive roots are
  refused.
- **Video thumbnails** — real frames via ffmpeg (falls back to icons
  without it).
- **3D models** — shaded thumbnails plus an interactive STL/OBJ viewer:
  drag to rotate, `+`/`−` zoom, reset. No three.js, no new dependencies.

## Install

1. Copy the `filebox` folder into your Hermes plugins directory
   (`%LOCALAPPDATA%\hermes\plugins\` on Windows).
2. Enable it: `hermes plugins enable filebox` (then restart the gateway).
3. In the Hermes desktop app: Settings → Plugins → turn on **Filebox**, then
   reload (⌘K → Reload). The Explorer pane starts collapsed — open it from
   the **Explorer** chip bottom-right. Drag it to the right side and close the
   built-in files pane if you want it as your sidebar.

## Editing files

Select anything and the preview panel grows an ops bar up top: **Copy path**,
**Rename** (inline, Enter to save), **Copy** / **Cut** / **Paste**,
**Delete** (second click confirms), **Compress**, and **Extract here** on
zips. Right-click any tile for the same ops in a context menu (paste targets
the folder you clicked, or the current folder). The preview panel resizes by
dragging its top edge and closes with the `×` in the ops bar (clicking the
file again still toggles it). The bottom row stays lean:
Open, Show in Explorer.
auto-resolve (`file (2).txt`). Deletes go to the recycle bin (needs
`send2trash` in the Hermes venv — `pip install send2trash`) and drive roots
are refused — you can't nuke `C:\` from here.

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
