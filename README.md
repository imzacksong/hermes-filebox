# Filebox — Explorer-style file browser for Hermes

Quick access, breadcrumbs, icon grid (S/M/L/XL), search, and a preview pane
with image / audio / video / PDF / text preview. Multiple folders stay open
in tabs (`+` to open, `×` to close). The quick-access sidebar resizes by
dragging its right edge and collapses with the `«` button (`»` rail to
bring it back). Sort order, tile size, sidebar width, hidden-file
toggle, pins, open tabs, and the active tab are all remembered between
launches. The sidebar (pins, Recycle Bin, drives) reorders by dragging
rows up and down, and remembers the order.

The `☰` button by the tile-size picker switches between the icon grid
(S/M/L/XL) and a Windows-style details list (Name · Size · Modified ·
Type, click a header to sort). The choice sticks between launches.

## Selecting files

Type in the search box to filter the current folder instantly. With 2 or
more characters FileBox also searches filenames in all subfolders (up to
8 levels deep, 200 results) — deep hits replace the list with a `🔍`
status line. Double-click a folder result to go there; files open,
preview, and take every context-menu op in place.

Click selects one. `Ctrl`/`Cmd`-click toggles, `Shift`-click selects a
range, `Ctrl+A` grabs the whole folder, `Esc` clears. With several
selected, a batch panel offers **Copy / Cut / Delete** (second click
confirms) and **Compress** into one zip. Right-click copy/cut/compress
act on the whole selection when the clicked file is in it. Dragging a
selection into a folder moves all of it.

Keyboard: arrows move the cursor, `Shift`+arrows extends the range,
`F2` renames, `Del` deletes (with confirm), `Enter` opens, `Esc`
clears. The folder view refreshes itself every few seconds when files
change elsewhere. The status bar has **+ New folder** and **+ New
file** (a new file opens straight into rename), and right-click →
**Duplicate** copies in place with an auto-numbered name.

## Recycle Bin

The sidebar has a **Recycle Bin** entry: deleted files and folders with
their original location and deletion date. Select one (or several) →
**Restore**, or right-click → Restore. The toolbar offers **Empty
Recycle Bin** (click twice to confirm — permanent). Deletes from FileBox
go to the bin, never vanish.

## Moving files in and out

- Drag a file out of FileBox into Explorer or onto the desktop — it
  copies over (single files; zip folders first).
- Right-click → **Copy outside Hermes**, then paste in Explorer.
- Copy files in Explorer, then Paste inside a FileBox folder — they copy
  in (works even when FileBox's own clipboard is empty).

## Install

1. Copy the `filebox` folder into your Hermes plugins directory
   (`%LOCALAPPDATA%\hermes\plugins\` on Windows, next to `sysmon`, `pals`, …).
2. Enable it: `hermes plugins enable filebox` (then restart the gateway).
3. In the Hermes desktop app: Settings → Plugins → turn on **Filebox**, then
   reload (⌘K → Reload). The FileBox pane starts collapsed — open it from
   the **FileBox** chip bottom-right. Drag it to the right side and close the
   built-in files pane if you want it as your sidebar.

.

.

## Editing files

Select anything and the preview panel grows an ops bar up top: **Copy path**,
**Rename** (inline, Enter to save), **Copy** / **Cut** / **Paste**,
**Delete** (second click confirms), **Compress**, and **Extract here** on
zips. Right-click any tile for the same ops in a context menu (paste targets
the folder you clicked, or the current folder). Text files under 256 KB
show an **Edit** button — change the text, **Save**, done. The preview panel resizes by
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
