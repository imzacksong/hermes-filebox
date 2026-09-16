"""Filebox backend — local filesystem reads AND writes for the Explorer-style pane.

Mounted at /api/plugins/filebox/. Localhost only, same trust as the terminal:
reads anything the user could `dir`, writes anything they could do in Explorer
(rename/copy/move/delete/mkdir/zip/extract). Delete goes to the recycle bin
(send2trash); the UI still confirms first.
"""
from __future__ import annotations

import base64
import io
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter()

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".ts"}
MODEL_EXTS = {".stl", ".obj"}
MAX_LIST = 8000
READ_CAP_KB = 256
THUMB_SRC_CAP_MB = 25


class PathIn(BaseModel):
    path: str = ""
    show_hidden: bool = False


class ReadIn(BaseModel):
    path: str = ""
    max_kb: int = READ_CAP_KB


class ThumbIn(BaseModel):
    path: str = ""
    size: int = 256


class MediaIn(BaseModel):
    path: str = ""
    size: int = 256


@router.post("/videothumb")
def videothumb(body: MediaIn) -> JSONResponse:
    if Path(body.path).suffix.lower() not in VIDEO_EXTS:
        return JSONResponse({"error": "not a video"}, status_code=400)
    ff = shutil.which("ffmpeg")
    if not ff:
        return JSONResponse({"error": "ffmpeg missing"}, status_code=501)
    size = max(32, min(body.size, 512))
    t = 1.0
    fp = shutil.which("ffprobe")
    if fp:
        try:
            out = subprocess.run(
                [fp, "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", body.path],
                capture_output=True, text=True, timeout=15)
            dur = float((out.stdout or "").strip())
            t = min(5.0, max(0.5, dur * 0.1))
        except Exception:
            pass
    try:
        out = subprocess.run(
            [ff, "-hide_banner", "-loglevel", "error", "-ss", str(t),
             "-i", body.path, "-frames:v", "1", "-vf", f"scale={size}:-1",
             "-q:v", "5", "-f", "mjpeg", "-"],
            capture_output=True, timeout=30)
        if out.returncode != 0 or not out.stdout:
            return JSONResponse({"error": "no frame"}, status_code=422)
        b64 = base64.b64encode(out.stdout).decode("ascii")
        return JSONResponse({"data_url": f"data:image/jpeg;base64,{b64}"})
    except subprocess.TimeoutExpired:
        return JSONResponse({"error": "timed out"}, status_code=504)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


class RawIn(BaseModel):
    path: str = ""
    max_mb: int = 48


@router.post("/raw")
def raw_bytes(body: RawIn) -> JSONResponse:
    try:
        cap = max(1, min(body.max_mb, 96)) * 1024 * 1024
        with open(body.path, "rb") as f:
            raw = f.read(cap + 1)
        truncated = len(raw) > cap
        raw = raw[:cap]
        return JSONResponse({
            "b64": base64.b64encode(raw).decode("ascii"),
            "size": len(raw), "truncated": truncated})
    except FileNotFoundError:
        return JSONResponse({"error": "not found"}, status_code=404)
    except PermissionError:
        return JSONResponse({"error": "access denied"}, status_code=403)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


def _stl_facets(path: str, cap: int = 4000):
    """Return (m,3,3) float array of triangles, sampled down to cap. Needs numpy."""
    import numpy as np
    with open(path, "rb") as f:
        buf = f.read()
    tris = None
    if len(buf) > 84:
        import struct
        (count,) = struct.unpack("<I", buf[80:84])
        if 0 < count < 5000000 and 84 + count * 50 == len(buf):
            dt = np.dtype([("n", "<f4", 3), ("v", "<f4", 9), ("a", "<u2")])
            arr = np.frombuffer(buf[84:84 + count * 50], dtype=dt)
            tris = arr["v"].reshape(-1, 3, 3).astype(np.float64)
    if tris is None:
        text = buf[:32 * 1024 * 1024].decode("utf-8", errors="ignore")
        verts = []
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("vertex"):
                try:
                    verts.append([float(x) for x in s.split()[1:4]])
                except ValueError:
                    pass
                if len(verts) >= cap * 3:
                    break
        if len(verts) < 3:
            return None
        tris = np.array(verts[:len(verts) // 3 * 3], dtype=np.float64).reshape(-1, 3, 3)
    if len(tris) > cap:
        tris = tris[:: (len(tris) + cap - 1) // cap]
    return tris


def _obj_facets(path: str, cap: int = 4000):
    import numpy as np
    verts: List[List[float]] = []
    faces: List[List[int]] = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for i, line in enumerate(f):
            if i > 2000000:
                break
            if line.startswith("v "):
                try:
                    verts.append([float(x) for x in line.split()[1:4]])
                except ValueError:
                    pass
            elif line.startswith("f "):
                try:
                    idx = [int(p.split("/")[0]) - 1 for p in line.split()[1:]]
                    if len(idx) >= 3:
                        for k in range(1, len(idx) - 1):
                            faces.append([idx[0], idx[k], idx[k + 1]])
                except ValueError:
                    pass
                if len(faces) >= cap:
                    break
    if not faces or not verts:
        return None
    v = np.array(verts, dtype=np.float64)
    tris = []
    for a, b, c in faces:
        if 0 <= a < len(v) and 0 <= b < len(v) and 0 <= c < len(v):
            tris.append([v[a], v[b], v[c]])
    return np.array(tris) if tris else None


def _render_facets(tris, size: int) -> bytes:
    from PIL import Image, ImageDraw
    import numpy as np
    c = tris.reshape(-1, 3)
    span = (c.max(0) - c.min(0)).max() or 1e-9
    t = (tris - c.min(0)) / span - 0.5
    az, el = 0.6, 0.45
    ca, sa, ce, se = np.cos(az), np.sin(az), np.cos(el), np.sin(el)
    x = t[..., 0] * ca + t[..., 2] * sa
    z = -t[..., 0] * sa + t[..., 2] * ca
    y = t[..., 1] * ce - z * se
    z2 = t[..., 1] * se + z * ce
    e1, e2 = x[:, 1] - x[:, 0], y[:, 1] - y[:, 0]
    f1, f2 = x[:, 2] - x[:, 0], y[:, 2] - y[:, 0]
    nz = e1 * f2 - e2 * f1
    nx = (y[:, 1] - y[:, 0]) * (z2[:, 2] - z2[:, 0]) - (z2[:, 1] - z2[:, 0]) * (y[:, 2] - y[:, 0])
    ny = (z2[:, 1] - z2[:, 0]) * (x[:, 2] - x[:, 0]) - (x[:, 1] - x[:, 0]) * (z2[:, 2] - z2[:, 0])
    ln = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-9
    light = np.array([0.4, 0.5, 0.75])
    light /= np.linalg.norm(light)
    s = np.clip((nx * light[0] + ny * light[1] + nz * light[2]) / ln, 0, 1)
    order = np.argsort(z2.mean(1))
    im = Image.new("RGB", (size, size), (18, 18, 24))
    d = ImageDraw.Draw(im)
    px = (x * 0.85 + 0.5) * size
    py = (0.5 - y * 0.85) * size
    for i in order:
        g = int(45 + 175 * s[i])
        d.polygon([float(px[i, 0]), float(py[i, 0]), float(px[i, 1]),
                   float(py[i, 1]), float(px[i, 2]), float(py[i, 2])],
                  fill=(g, g, min(255, g + 12)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=72)
    return buf.getvalue()


@router.post("/modelthumb")
def modelthumb(body: MediaIn) -> JSONResponse:
    ext = Path(body.path).suffix.lower()
    if ext not in MODEL_EXTS:
        return JSONResponse({"error": "not a model"}, status_code=400)
    size = max(32, min(body.size, 512))
    try:
        tris = _stl_facets(body.path) if ext == ".stl" else _obj_facets(body.path)
        if tris is None or not len(tris):
            return JSONResponse({"error": "no geometry"}, status_code=422)
        img = _render_facets(tris, size)
        return JSONResponse(
            {"data_url": f"data:image/jpeg;base64,{base64.b64encode(img).decode('ascii')}",
             "tris": int(len(tris))})
    except FileNotFoundError:
        return JSONResponse({"error": "not found"}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


class MkdirIn(BaseModel):
    parent: str = ""
    name: str = ""


BAD_NAME_CHARS = '/\\:*?"<>|'


def _clean_name(name: str) -> str:
    return (name or "").strip().rstrip(". ")


def _free_path(p: Path) -> Path:
    if not p.exists():
        return p
    stem, suffix = (p.stem, p.suffix) if p.suffix else (p.name, "")
    # for dirs p.suffix may be a fake extension (e.g. "data.old") — treat
    # dotted dir names carefully: only split when it's actually a file
    if p.is_dir():
        stem, suffix = p.name, ""
    i = 2
    while True:
        cand = p.parent / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
        i += 1


def _guard_root(p: Path) -> Optional[JSONResponse]:
    try:
        if p.parent == p:
            return JSONResponse({"error": "refusing drive root"}, status_code=400)
    except Exception:
        return JSONResponse({"error": "bad path"}, status_code=400)
    return None


class RenameIn(BaseModel):
    path: str = ""
    new_name: str = ""


@router.post("/rename")
def rename(body: RenameIn) -> JSONResponse:
    name = _clean_name(body.new_name)
    if not name or any(c in name for c in BAD_NAME_CHARS):
        return JSONResponse({"error": "bad name"}, status_code=400)
    try:
        src = Path(body.path)
        if not src.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        if (g := _guard_root(src)):
            return g
        dst = src.parent / name
        if dst.exists():
            return JSONResponse({"error": "already exists"}, status_code=409)
        src.rename(dst)
        return JSONResponse({"ok": True, "path": str(dst)})
    except PermissionError:
        return JSONResponse({"error": "access denied"}, status_code=403)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


class OpIn(BaseModel):
    paths: List[str] = []
    dest_dir: str = ""


def _paste(op: str, body: OpIn) -> JSONResponse:
    if not body.paths:
        return JSONResponse({"error": "nothing selected"}, status_code=400)
    try:
        dest = Path(body.dest_dir)
        if not dest.is_dir():
            return JSONResponse({"error": "bad destination"}, status_code=400)
        done, failed = [], []
        for raw in body.paths:
            try:
                src = Path(raw)
                if not src.exists():
                    failed.append({"path": raw, "error": "not found"})
                    continue
                if op == "move" and (g := _guard_root(src)):
                    failed.append({"path": raw, "error": "drive root"})
                    continue
                if src.is_dir() and (dest.resolve() == src.resolve() or src.resolve() in dest.resolve().parents):
                    failed.append({"path": raw, "error": "can't paste into itself"})
                    continue
                dst = _free_path(dest / src.name)
                if op == "copy":
                    if src.is_dir():
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
                else:
                    shutil.move(str(src), str(dst))
                done.append(str(dst))
            except PermissionError:
                failed.append({"path": raw, "error": "access denied"})
            except Exception as e:
                failed.append({"path": raw, "error": str(e)[:120]})
        return JSONResponse({"ok": not failed, "done": done, "failed": failed})
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@router.post("/copy")
def copy(body: OpIn) -> JSONResponse:
    return _paste("copy", body)


@router.post("/move")
def move(body: OpIn) -> JSONResponse:
    return _paste("move", body)


class DeleteIn(BaseModel):
    paths: List[str] = []


@router.post("/delete")
def delete(body: DeleteIn) -> JSONResponse:
    if not body.paths:
        return JSONResponse({"error": "nothing selected"}, status_code=400)
    try:
        from send2trash import send2trash
    except ImportError:
        return JSONResponse(
            {"error": "send2trash missing — pip install send2trash (refusing permanent delete)"},
            status_code=501)
    done, failed = [], []
    for raw in body.paths:
        try:
            p = Path(raw)
            if not p.exists():
                failed.append({"path": raw, "error": "not found"})
                continue
            if (g := _guard_root(p)):
                failed.append({"path": raw, "error": "drive root"})
                continue
            send2trash(str(p))
            done.append(raw)
        except PermissionError:
            failed.append({"path": raw, "error": "access denied"})
        except Exception as e:
            failed.append({"path": raw, "error": str(e)[:120]})
    return JSONResponse({"ok": not failed, "done": done, "failed": failed})


class ZipIn(BaseModel):
    paths: List[str] = []
    name: str = ""


@router.post("/zip")
def make_zip(body: ZipIn) -> JSONResponse:
    if not body.paths:
        return JSONResponse({"error": "nothing selected"}, status_code=400)
    try:
        first = Path(body.paths[0])
        parent = first.parent
        base = _clean_name(body.name) or (first.stem if len(body.paths) == 1 else "archive")
        if any(c in base for c in BAD_NAME_CHARS):
            return JSONResponse({"error": "bad name"}, status_code=400)
        if not base.lower().endswith(".zip"):
            base += ".zip"
        zpath = _free_path(parent / base)
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for raw in body.paths:
                src = Path(raw)
                if not src.exists():
                    continue
                if src.is_dir() and not src.is_symlink():
                    for root, _, files in os.walk(src):
                        for fn in files:
                            fp = Path(root) / fn
                            z.write(fp, fp.relative_to(parent))
                else:
                    z.write(src, src.name)
        return JSONResponse({"ok": True, "path": str(zpath)})
    except PermissionError:
        return JSONResponse({"error": "access denied"}, status_code=403)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


class ExtractIn(BaseModel):
    path: str = ""
    dest_dir: str = ""


@router.post("/extract")
def extract_zip(body: ExtractIn) -> JSONResponse:
    try:
        src = Path(body.path)
        if not src.is_file() or src.suffix.lower() != ".zip":
            return JSONResponse({"error": "not a zip"}, status_code=400)
        dest = Path(body.dest_dir) if body.dest_dir else src.parent / src.stem
        if dest.exists() and not dest.is_dir():
            return JSONResponse({"error": "destination blocked"}, status_code=409)
        dest = _free_path(dest) if dest.exists() else dest
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(src, "r") as z:
            z.extractall(dest)
        return JSONResponse({"ok": True, "path": str(dest)})
    except PermissionError:
        return JSONResponse({"error": "access denied"}, status_code=403)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


def _is_hidden(p: Path, entry_hidden: bool = False) -> bool:
    if p.name.startswith("."):
        return True
    if entry_hidden:
        return True
    try:
        attrs = p.stat().st_file_attributes  # Windows-only attr
        return bool(attrs & 0x2)
    except Exception:
        return False


def _entry(scan: os.DirEntry, show_hidden: bool) -> Optional[Dict[str, Any]]:
    try:
        is_dir = scan.is_dir(follow_symlinks=False)
    except Exception:
        return None
    try:
        st = scan.stat(follow_symlinks=False)
    except Exception:
        return None
    path = str(Path(scan.path))
    hidden = scan.name.startswith(".")
    if not hidden:
        try:
            hidden = bool(st.st_file_attributes & 0x2)
        except Exception:
            pass
    if hidden and not show_hidden:
        return None
    ext = "" if is_dir else Path(scan.name).suffix.lower()
    return {
        "name": scan.name,
        "path": path,
        "is_dir": is_dir,
        "size": 0 if is_dir else st.st_size,
        "mtime": st.st_mtime,
        "ext": ext,
        "hidden": hidden,
    }


@router.post("/roots")
def roots() -> Dict[str, Any]:
    drives = []
    try:
        for part in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(part.mountpoint)
                drives.append({
                    "device": part.device,
                    "mount": part.mountpoint,
                    "fstype": part.fstype,
                    "percent": u.percent,
                    "total_gb": round(u.total / (1024 ** 3), 1),
                })
            except Exception:
                pass
    except Exception:
        pass
    return {"home": str(Path.home()), "drives": drives}


@router.post("/list")
def list_dir(body: PathIn) -> JSONResponse:
    target = body.path or str(Path.home())
    try:
        entries: List[Dict[str, Any]] = []
        total = 0
        with os.scandir(target) as it:
            for scan in it:
                total += 1
                if len(entries) >= MAX_LIST:
                    continue
                e = _entry(scan, body.show_hidden)
                if e:
                    entries.append(e)
        parent = str(Path(target).parent) if Path(target).parent != Path(target) else None
        return JSONResponse({"path": target, "parent": parent, "entries": entries,
                             "total": total, "truncated": total > len(entries)})
    except FileNotFoundError:
        return JSONResponse({"error": "not found"}, status_code=404)
    except PermissionError:
        return JSONResponse({"error": "access denied"}, status_code=403)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@router.post("/read")
def read_text(body: ReadIn) -> JSONResponse:
    try:
        cap = max(1, min(body.max_kb, 1024)) * 1024
        with open(body.path, "rb") as f:
            raw = f.read(cap + 1)
        truncated = len(raw) > cap
        raw = raw[:cap]
        if b"\x00" in raw[:8192]:
            return JSONResponse({"is_binary": True, "truncated": truncated})
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("latin-1")
            except Exception:
                return JSONResponse({"is_binary": True, "truncated": truncated})
        return JSONResponse({"is_binary": False, "text": text, "truncated": truncated})
    except FileNotFoundError:
        return JSONResponse({"error": "not found"}, status_code=404)
    except PermissionError:
        return JSONResponse({"error": "access denied"}, status_code=403)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@router.post("/thumb")
def thumb(body: ThumbIn) -> JSONResponse:
    try:
        if Path(body.path).suffix.lower() not in IMAGE_EXTS:
            return JSONResponse({"error": "not an image"}, status_code=400)
        if os.path.getsize(body.path) > THUMB_SRC_CAP_MB * 1024 * 1024:
            return JSONResponse({"error": "too large"}, status_code=413)
        from PIL import Image
        size = max(32, min(body.size, 512))
        with Image.open(body.path) as im:
            im.draft("RGB", (size, size))
            im = im.convert("RGB")
            im.thumbnail((size, size))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=70)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return JSONResponse({"data_url": f"data:image/jpeg;base64,{b64}"})
    except FileNotFoundError:
        return JSONResponse({"error": "not found"}, status_code=404)
    except PermissionError:
        return JSONResponse({"error": "access denied"}, status_code=403)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@router.post("/mkdir")
def mkdir(body: MkdirIn) -> JSONResponse:
    name = (body.name or "").strip().rstrip(". ")
    if not name or any(c in name for c in '/\\:*?"<>|'):
        return JSONResponse({"error": "bad name"}, status_code=400)
    try:
        target = Path(body.parent) / name
        target.mkdir(parents=False, exist_ok=False)
        return JSONResponse({"ok": True, "path": str(target)})
    except FileExistsError:
        return JSONResponse({"error": "already exists"}, status_code=409)
    except PermissionError:
        return JSONResponse({"error": "access denied"}, status_code=403)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@router.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True}


@router.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True}
