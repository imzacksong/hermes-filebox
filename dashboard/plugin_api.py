"""Filebox backend — local filesystem reads AND writes for the Explorer-style pane.

Mounted at /api/plugins/hermes-filebox/. Localhost only, same trust as the terminal:
reads anything the user could `dir`, writes anything they could do in Explorer
(rename/copy/move/delete/mkdir/zip/extract). Delete goes to the recycle bin
(send2trash); the UI still confirms first.
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

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


THUMB_CACHE_DIR = Path(tempfile.gettempdir()) / "hermes-filebox-thumbs"
THUMB_CACHE_MAX_FILES = 2000
THUMB_CACHE_MAX_BYTES = 500 * 1024 * 1024


def _thumb_key(path: str, kind: str, size: int) -> Optional[str]:
    """Cache key binding path + content version (mtime, size)."""
    try:
        st = os.stat(path)
        sig = f"{path}|{st.st_mtime_ns}|{st.st_size}|{kind}|{size}"
        return hashlib.sha1(sig.encode("utf-8")).hexdigest() + ".jpg"
    except Exception:
        return None


def _thumb_get(key: Optional[str]) -> Optional[bytes]:
    if not key:
        return None
    try:
        p = THUMB_CACHE_DIR / key
        if p.is_file():
            return p.read_bytes()
    except Exception:
        pass
    return None


def _thumb_put(key: Optional[str], data: bytes) -> None:
    if not key or not data:
        return
    try:
        THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (THUMB_CACHE_DIR / key).write_bytes(data)
    except Exception:
        return
    # Opportunistic prune: oldest first, only when over a limit.
    try:
        files = [(f.stat().st_mtime, f.stat().st_size, f)
                 for f in THUMB_CACHE_DIR.iterdir() if f.is_file()]
        total = sum(s for _, s, _ in files)
        if len(files) > THUMB_CACHE_MAX_FILES or total > THUMB_CACHE_MAX_BYTES:
            files.sort()
            kept = len(files)
            for _, s, f in files:
                if kept <= THUMB_CACHE_MAX_FILES // 2 and total <= THUMB_CACHE_MAX_BYTES // 2:
                    break
                try:
                    f.unlink()
                    total -= s
                    kept -= 1
                except Exception:
                    pass
    except Exception:
        pass


@router.post("/videothumb")
def videothumb(body: MediaIn) -> JSONResponse:
    if Path(body.path).suffix.lower() not in VIDEO_EXTS:
        return JSONResponse({"error": "not a video"}, status_code=400)
    if (d := _deny_secret(Path(body.path))):
        return d
    ff = shutil.which("ffmpeg")
    if not ff:
        return JSONResponse({"error": "ffmpeg missing"}, status_code=501)
    size = max(32, min(body.size, 512))
    key = _thumb_key(body.path, "video", size)
    hit = _thumb_get(key)
    if hit is not None:
        return JSONResponse(
            {"data_url": f"data:image/jpeg;base64,{base64.b64encode(hit).decode('ascii')}",
             "cached": True})
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
        _thumb_put(key, bytes(out.stdout))
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
    if (d := _deny_secret(Path(body.path))):
        return d
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
    if (d := _deny_secret(Path(body.path))):
        return d
    try:
        key = _thumb_key(body.path, "model", size)
        hit = _thumb_get(key)
        if hit is not None:
            return JSONResponse(
                {"data_url": f"data:image/jpeg;base64,{base64.b64encode(hit).decode('ascii')}",
                 "cached": True})
        tris = _stl_facets(body.path) if ext == ".stl" else _obj_facets(body.path)
        if tris is None or not len(tris):
            return JSONResponse({"error": "no geometry"}, status_code=422)
        img = _render_facets(tris, size)
        _thumb_put(key, img)
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


# --- Secret-file deny (catalog requirement) ---
# Refuse reads/writes under ~/.ssh and under Hermes' own secret files, even
# though the backend runs as the user. Symlinks are resolved first so a
# link pointing at a secret can't sneak through. Everything else on disk
# stays browsable — same trust as the terminal, minus the keys.
_SECRET_NAMES = {
    "config.yaml", "config.yml", ".env",
    "secrets.json", "credentials.json", "token", ".token",
}
_SECRET_SUFFIXES = {".pem", ".key"}


def _hermes_home_dirs() -> List[Path]:
    cands = []
    env = os.environ.get("HERMES_HOME")
    if env:
        cands.append(Path(env))
    cands += [
        Path.home() / ".hermes",
        Path.home() / "AppData" / "Local" / "hermes",
        Path.home() / ".config" / "hermes",
    ]
    out = []
    for c in cands:
        try:
            if c.is_dir():
                out.append(c.resolve())
        except Exception:
            pass
    return out


_HERMES_DIRS = _hermes_home_dirs()


def _deny_secret(p: Path) -> Optional[JSONResponse]:
    """Return a 403 response if p resolves into ~/.ssh or a Hermes secret."""
    try:
        rp = Path(os.path.realpath(p))
    except Exception:
        return JSONResponse({"error": "bad path"}, status_code=400)
    try:
        ssh = Path.home().resolve() / ".ssh"
    except Exception:
        ssh = Path.home() / ".ssh"
    if rp == ssh or ssh in rp.parents:
        return JSONResponse({"error": "refusing ~/.ssh"}, status_code=403)
    for hd in _HERMES_DIRS:
        if rp == hd or hd in rp.parents:
            n = rp.name.lower()
            if n in _SECRET_NAMES or rp.suffix.lower() in _SECRET_SUFFIXES:
                return JSONResponse(
                    {"error": "refusing Hermes secret file"}, status_code=403)
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
        if (d := _deny_secret(src)):
            return d
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
        if (d := _deny_secret(dest)):
            return d
        done, failed = [], []
        for raw in body.paths:
            try:
                src = Path(raw)
                if not src.exists():
                    failed.append({"path": raw, "error": "not found"})
                    continue
                if (d := _deny_secret(src)):
                    failed.append({"path": raw, "error": "forbidden path"})
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
                        # symlinks=True: copy links as links — never follow
                        # a linked tree off into the source or a loop.
                        shutil.copytree(src, dst, symlinks=True)
                    else:
                        shutil.copy2(src, dst, follow_symlinks=False)
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
            if (d := _deny_secret(p)):
                failed.append({"path": raw, "error": "forbidden path"})
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
        for raw in body.paths:
            if (d := _deny_secret(Path(raw))):
                return d
        if not base.lower().endswith(".zip"):
            base += ".zip"
        zpath = _free_path(parent / base)
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for raw in body.paths:
                src = Path(raw)
                if not src.exists():
                    continue
                if src.is_dir() and not src.is_symlink():
                    for root, dirs, files in os.walk(src):
                        rp = Path(root)
                        if not dirs and not files:
                            # zip has no implicit dir entries — keep empty dirs
                            z.writestr(str(rp.relative_to(parent)) + "/", "")
                        for fn in files:
                            fp = rp / fn
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
        if (d := _deny_secret(src)):
            return d
        dest = Path(body.dest_dir) if body.dest_dir else src.parent / src.stem
        if dest.exists() and not dest.is_dir():
            return JSONResponse({"error": "destination blocked"}, status_code=409)
        dest = _free_path(dest) if dest.exists() else dest
        if (d := _deny_secret(dest)):
            return d
        dest.mkdir(parents=True, exist_ok=True)
        dest_resolved = dest.resolve()
        with zipfile.ZipFile(src, "r") as z:
            for m in z.infolist():
                # zip-slip guard: every member must land inside dest
                target = dest / m.filename
                try:
                    resolved = target.resolve()
                except Exception:
                    return JSONResponse({"error": "bad archive entry"}, status_code=400)
                if resolved != dest_resolved and dest_resolved not in resolved.parents:
                    return JSONResponse({"error": "archive has unsafe paths"}, status_code=400)
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
        import psutil
    except Exception:
        psutil = None
    if psutil is not None:
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
    if (d := _deny_secret(Path(target))):
        return d
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
    if (d := _deny_secret(Path(body.path))):
        return d
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
    if (d := _deny_secret(Path(body.path))):
        return d
    try:
        if Path(body.path).suffix.lower() not in IMAGE_EXTS:
            return JSONResponse({"error": "not an image"}, status_code=400)
        if os.path.getsize(body.path) > THUMB_SRC_CAP_MB * 1024 * 1024:
            return JSONResponse({"error": "too large"}, status_code=413)
        from PIL import Image
        size = max(32, min(body.size, 512))
        key = _thumb_key(body.path, "img", size)
        hit = _thumb_get(key)
        if hit is not None:
            b64 = base64.b64encode(hit).decode("ascii")
            return JSONResponse({"data_url": f"data:image/jpeg;base64,{b64}",
                                 "cached": True})
        with Image.open(body.path) as im:
            im.draft("RGB", (size, size))
            im = im.convert("RGB")
            im.thumbnail((size, size))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=70)
        _thumb_put(key, buf.getvalue())
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
        if (d := _deny_secret(target)):
            return d
        target.mkdir(parents=False, exist_ok=False)
        return JSONResponse({"ok": True, "path": str(target)})
    except FileExistsError:
        return JSONResponse({"error": "already exists"}, status_code=409)
    except PermissionError:
        return JSONResponse({"error": "access denied"}, status_code=403)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)
class WriteIn(BaseModel):
    path: str = ""
    text: str = ""
    max_kb: int = 1024


@router.post("/write")
def write_text(body: WriteIn) -> JSONResponse:
    """Overwrite a text file. Refuses dirs, symlinks, and files over the cap."""
    try:
        p = Path(body.path)
        if not p.is_file() or p.is_symlink():
            return JSONResponse({"error": "not a plain file"}, status_code=400)
        if (g := _guard_root(p)):
            return g
        if (d := _deny_secret(p)):
            return d
        cap = max(1, min(body.max_kb or 1024, 1024)) * 1024
        if p.stat().st_size > cap:
            return JSONResponse({"error": "file too large to edit here"}, status_code=413)
        data = (body.text or "").encode("utf-8")
        if len(data) > cap:
            return JSONResponse({"error": "new content too large"}, status_code=413)
        p.write_bytes(data)
        return JSONResponse({"ok": True, "path": str(p),
                             "size": len(data), "mtime": p.stat().st_mtime})
    except PermissionError:
        return JSONResponse({"error": "access denied"}, status_code=403)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


class MkfileIn(BaseModel):
    parent: str = ""
    name: str = ""


@router.post("/mkfile")
def mkfile(body: MkfileIn) -> JSONResponse:
    """Create an empty file. Auto-numbers when the name is taken."""
    name = _clean_name(body.name)
    if not name or any(c in name for c in BAD_NAME_CHARS):
        return JSONResponse({"error": "bad name"}, status_code=400)
    try:
        parent = Path(body.parent)
        if not parent.is_dir():
            return JSONResponse({"error": "bad parent"}, status_code=400)
        if (d := _deny_secret(parent)):
            return d
        target = _free_path(parent / name)
        target.touch(exist_ok=False)
        return JSONResponse({"ok": True, "path": str(target)})
    except FileExistsError:
        return JSONResponse({"error": "already exists"}, status_code=409)
    except PermissionError:
        return JSONResponse({"error": "access denied"}, status_code=403)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


class WatchIn(BaseModel):
    path: str = ""


@router.post("/watch")
def watch_dir(body: WatchIn) -> JSONResponse:
    """Cheap change fingerprint for auto-refresh: dir mtime + child count.

    No per-file stats, so polling every few seconds stays cheap even in
    huge folders. The frontend refetches /list only when this changes.
    """
    try:
        target = Path(body.path) if body.path else Path.home()
        if (d := _deny_secret(target)):
            return d
        if not target.is_dir():
            return JSONResponse({"error": "not a folder"}, status_code=400)
        try:
            with os.scandir(target) as it:
                count = sum(1 for _ in it)
        except (PermissionError, FileNotFoundError, OSError):
            return JSONResponse({"error": "access denied"}, status_code=403)
        return JSONResponse({"ok": True, "path": str(target),
                             "fingerprint": f"{target.stat().st_mtime_ns}:{count}"})
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


class SearchIn(BaseModel):
    root: str = ""
    query: str = ""
    show_hidden: bool = False
    max_results: int = 200
    max_depth: int = 8


@router.post("/search")
def search_files(body: SearchIn) -> JSONResponse:
    """Recursive filename search under root. Name matches only (no content).

    Bounded: max_results (cap 1000), max_depth (cap 12), and a dir-scan
    budget so a drive-root search can't hang the gateway. Symlinked dirs
    are matched by name but never descended into (loop-proof).
    """
    q = (body.query or "").strip().lower()
    if len(q) < 2:
        return JSONResponse({"error": "query too short"}, status_code=400)
    try:
        root = Path(body.root)
        if not root.is_dir():
            return JSONResponse({"error": "bad root"}, status_code=400)
    except Exception:
        return JSONResponse({"error": "bad root"}, status_code=400)
    if (d := _deny_secret(root)):
        return d
    max_results = max(1, min(body.max_results or 200, 1000))
    max_depth = max(0, min(body.max_depth or 8, 12))
    dir_budget = 20000
    out: List[Dict[str, Any]] = []
    truncated = False
    try:
        stack = [(str(root), 0)]
        while stack and len(out) < max_results:
            cur, depth = stack.pop()
            if dir_budget <= 0:
                truncated = True
                break
            dir_budget -= 1
            try:
                with os.scandir(cur) as it:
                    children = list(it)
            except (PermissionError, FileNotFoundError, OSError):
                continue
            for scan in children:
                try:
                    is_dir = scan.is_dir(follow_symlinks=False)
                except Exception:
                    continue
                e = _entry(scan, body.show_hidden)
                if e is None:
                    continue
                if q in scan.name.lower():
                    out.append(e)
                    if len(out) >= max_results:
                        truncated = True
                        break
                if is_dir and depth < max_depth:
                    try:
                        if not os.path.islink(scan.path):
                            stack.append((scan.path, depth + 1))
                    except Exception:
                        pass
        return JSONResponse({"ok": True, "root": str(root), "query": body.query,
                             "entries": out, "total": len(out),
                             "truncated": truncated})
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@router.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True}
def _trash_parse_i(data: bytes) -> Optional[Dict[str, Any]]:
    """Parse a $I recycle-bin metadata file: size + deleted time + original path."""
    import struct
    try:
        if len(data) < 28:
            return None
        ver = struct.unpack("<q", data[0:8])[0]
        size = struct.unpack("<q", data[8:16])[0]
        ft = struct.unpack("<q", data[16:24])[0]
        # v1: path at 24; v2 (Win8+): 4-byte path-length field, path at 28.
        # NOTE: never search the raw bytes for b"\x00\x00" — the low byte of
        # the last char plus the terminator aliases as a false end. Decode
        # first (NUL is illegal in Windows paths), then cut at the NUL char.
        off = 28 if ver == 2 else 24
        orig = data[off:].decode("utf-16-le", "replace").split("\x00", 1)[0]
        deleted = max(0, (ft - 116444736000000000) // 10000000)
        return {"size": max(0, size), "deleted": deleted, "orig": orig}
    except Exception:
        return None


def _trash_roots() -> List[Path]:
    roots = []
    for d in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        rb = Path(f"{d}:\\$Recycle.Bin")
        try:
            if rb.is_dir():
                roots.append(rb)
        except Exception:
            pass
    return roots


def _trash_scan() -> List[Dict[str, Any]]:
    items = []
    for rb in _trash_roots():
        try:
            sids = [x for x in rb.iterdir() if x.is_dir()]
        except Exception:
            continue
        for sid in sids:
            try:
                inames = [x for x in sid.iterdir()
                          if x.is_file() and x.name.startswith("$I")]
            except Exception:
                continue
            for ip in inames:
                try:
                    meta = _trash_parse_i(ip.read_bytes())
                    if not meta or not meta["orig"]:
                        continue
                    rfile = ip.parent / ("$R" + ip.name[2:])
                    size = meta["size"]
                    try:
                        if rfile.exists():
                            size = rfile.stat().st_size if rfile.is_file() else size
                    except Exception:
                        pass
                    is_dir = False
                    try:
                        is_dir = rfile.is_dir()
                    except Exception:
                        pass
                    name = Path(meta["orig"]).name or ip.name
                    ext = "" if is_dir else Path(name).suffix.lower()
                    items.append({
                        "id": f"{sid.name}/{ip.name}",
                        "name": name,
                        "path": f"trash://{sid.name}/{ip.name}",
                        "orig": meta["orig"],
                        "deleted": meta["deleted"],
                        "size": size,
                        "mtime": meta["deleted"],
                        "is_dir": is_dir,
                        "ext": ext,
                    })
                except Exception:
                    continue
    items.sort(key=lambda x: -x["deleted"])
    return items


def _trash_resolve(item_id: str) -> Optional[Dict[str, Any]]:
    for it in _trash_scan():
        if it["id"] == item_id or it["path"] == item_id:
            return it
    return None


@router.post("/trash")
def trash_list() -> Dict[str, Any]:
    try:
        return {"ok": True, "items": _trash_scan()}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "items": []}


@router.post("/trash-empty")
def trash_empty() -> Dict[str, Any]:
    removed = 0
    try:
        import ctypes
        SHERB_NOCONFIRMATION, SHERB_NOPROGRESSUI, SHERB_NOSOUND = 0x1, 0x2, 0x4
        rc = ctypes.windll.shell32.SHEmptyRecycleBinW(
            None, None, SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND)
        if rc == 0:
            return {"ok": True, "removed": -1}
    except Exception:
        pass
    for rb in _trash_roots():
        try:
            sids = [x for x in rb.iterdir() if x.is_dir()]
        except Exception:
            continue
        for sid in sids:
            try:
                files = [x for x in sid.iterdir() if x.is_file()]
            except Exception:
                continue
            for f in files:
                try:
                    f.unlink()
                    removed += 1
                except Exception:
                    pass
    return {"ok": True, "removed": removed}


class TrashRestoreIn(BaseModel):
    id: str = ""


@router.post("/trash-restore")
def trash_restore(body: TrashRestoreIn) -> Dict[str, Any]:
    it = _trash_resolve(body.id)
    if not it:
        return JSONResponse({"ok": False, "error": "item not found"}, status_code=404)
    try:
        rest = body.id.split("trash://", 1)[1] if "trash://" in body.id else body.id
        sid_name, iname = rest.split("/", 1)
        rfile = None
        iname_r = "$R" + iname[2:] if iname.startswith("$I") else iname
        for rb in _trash_roots():
            cand = rb / sid_name / iname_r
            try:
                if cand.exists() or os.path.isdir(str(cand)):
                    rfile = cand
                    break
            except Exception:
                continue
        if rfile is None:
            return JSONResponse({"ok": False, "error": "backing file gone"}, status_code=410)
        dest = Path(it["orig"])
        if (d := _deny_secret(dest)):
            return d
        try:
            if not dest.parent.is_dir():
                return JSONResponse(
                    {"ok": False, "error": "original folder no longer exists"},
                    status_code=409)
        except Exception:
            return JSONResponse({"ok": False, "error": "bad original path"},
                                status_code=400)
        if dest.exists() or os.path.lexists(str(dest)):
            dest = _free_path(dest)
        os.rename(str(rfile), str(dest))
        try:
            (rfile.parent / iname).unlink()
        except Exception:
            pass
        return {"ok": True, "path": str(dest)}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=500)


def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _os_clipboard_files() -> List[str]:
    """Read the Windows Explorer file clipboard (copy/paste outside Hermes)."""
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-Clipboard -Format FileDropList | ForEach-Object { $_.FullName }"],
            capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            return []
        return [ln.strip() for ln in (out.stdout or "").splitlines()
                if ln.strip() and os.path.exists(ln.strip())]
    except Exception:
        return []


@router.get("/dl")
def download_file(path: str = ""):
    """Direct file download for drag-out to Explorer (DownloadURL flavor).

    Files only, localhost callers. Folders can't ride DownloadURL —
    compress them first.
    """
    from fastapi.responses import FileResponse
    try:
        p = Path(path)
        if not path or not p.is_file():
            return JSONResponse({"ok": False, "error": "file only"}, status_code=400)
        if (d := _deny_secret(p)):
            return d
        return FileResponse(str(p), filename=p.name)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=500)


class CopyOutIn(BaseModel):
    paths: List[str] = []


@router.post("/copy-out")
def copy_out(body: CopyOutIn) -> Dict[str, Any]:
    """Put real files on the Windows clipboard so they paste into Explorer."""
    paths = [p for p in body.paths
             if p and not p.startswith("trash://") and os.path.exists(p)]
    if not paths:
        return JSONResponse({"ok": False, "error": "nothing to copy"}, status_code=400)
    for p in paths:
        if _deny_secret(Path(p)):
            return JSONResponse({"ok": False, "error": "forbidden path"}, status_code=403)
    try:
        arr = ",".join(_ps_quote(p) for p in paths)
        cmd = ("Add-Type -AssemblyName System.Windows.Forms; "
               f"$c = New-Object System.Collections.Specialized.StringCollection; "
               f"$c.AddRange(@({arr})); "
               "[System.Windows.Forms.Clipboard]::SetFileDropList($c)")
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", cmd],
            capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            return JSONResponse(
                {"ok": False, "error": (out.stderr or "clipboard failed")[:200]},
                status_code=500)
        return {"ok": True, "count": len(paths)}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=500)


class PasteOsIn(BaseModel):
    dest: str = ""


@router.post("/paste-os")
def paste_os(body: PasteOsIn) -> Dict[str, Any]:
    """Paste files copied in Explorer into a FileBox folder."""
    if not body.dest or body.dest.startswith("trash://"):
        return JSONResponse({"ok": False, "error": "bad destination"}, status_code=400)
    try:
        dest = Path(body.dest)
        if not dest.is_dir():
            return JSONResponse({"ok": False, "error": "bad destination"}, status_code=400)
        paths = _os_clipboard_files()
        if not paths:
            return JSONResponse({"ok": False, "error": "system clipboard has no files"},
                                status_code=404)
        return _paste("copy", OpIn(paths=paths, dest_dir=str(dest)))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=500)
