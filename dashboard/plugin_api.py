"""Filebox backend — local filesystem reads for the Explorer-style pane.

Mounted at /api/plugins/filebox/. Localhost only, same trust as the terminal:
reads anything the user could `dir`, plus mkdir. No rename/delete in v1.
"""
from __future__ import annotations

import base64
import io
import mimetypes
import os
import secrets
import shutil
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter()

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".tif", ".tiff"}
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


class MkdirIn(BaseModel):
    parent: str = ""
    name: str = ""


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


SHARE_PORT = 8077
_PEER_CFG = {"peer": "nina", "label": "Nina", "agent": "Milo", "thread": "milo-thread.md"}
try:
    _cfg_path = Path(__file__).resolve().parent / "peer.json"
    if _cfg_path.exists():
        import json as _json
        _PEER_CFG.update(_json.loads(_cfg_path.read_text(encoding="utf-8")))
except Exception:
    pass
NOTIFY_PEER = _PEER_CFG["peer"]
THREAD_LOG = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes" / "plugins" / "filebox" / _PEER_CFG["thread"]
_shares: Dict[str, Dict[str, Any]] = {}
_shares_lock = threading.Lock()
_share_server: Optional[object] = None
_lan_ip: Optional[str] = None


def _get_lan_ip() -> str:
    global _lan_ip
    if _lan_ip:
        return _lan_ip
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.168.1.1", 80))
        _lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        try:
            _lan_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            _lan_ip = "127.0.0.1"
    return _lan_ip


class _ShareHandler(BaseHTTPRequestHandler):
    server_version = "Filebox/1.0"

    def log_message(self, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        try:
            parts = self.path.split("?", 1)[0].strip("/").split("/")
            if len(parts) != 2 or parts[0] != "dl":
                self.send_error(404)
                return
            token = parts[1]
            with _shares_lock:
                share = _shares.get(token)
            if not share or not os.path.isfile(share["path"]):
                self.send_error(404)
                return
            ctype = mimetypes.guess_type(share["name"])[0] or "application/octet-stream"
            size = os.path.getsize(share["path"])
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", f'attachment; filename="{share["name"]}"')
            self.end_headers()
            with open(share["path"], "rb") as f:
                while True:
                    chunk = f.read(1024 * 256)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            try:
                self.send_error(500)
            except Exception:
                pass


def _ensure_share_server() -> None:
    global _share_server
    if _share_server is not None:
        return
    srv = ThreadingHTTPServer(("0.0.0.0", SHARE_PORT), _ShareHandler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    _share_server = srv


def _log_thread(who: str, text: str) -> None:
    try:
        from datetime import datetime
        THREAD_LOG.parent.mkdir(parents=True, exist_ok=True)
        if not THREAD_LOG.exists():
            THREAD_LOG.write_text(f"# File shares (via {_PEER_CFG['agent']})\n\nHumans read here. Approvals go through your own agent.\n\n", encoding="utf-8")
        with open(THREAD_LOG, "a", encoding="utf-8") as f:
            f.write(f"## {datetime.now():%Y-%m-%d %H:%M} — {who}\n\n{text}\n\n")
    except Exception:
        pass


class ShareIn(BaseModel):
    path: str = ""


class RevokeIn(BaseModel):
    token: str = ""


class NotifyIn(BaseModel):
    url: str = ""
    name: str = ""


@router.post("/config")
def peer_config() -> Dict[str, Any]:
    return {"peer": NOTIFY_PEER, "label": _PEER_CFG["label"], "agent": _PEER_CFG["agent"]}


@router.post("/notify")
def notify(body: NotifyIn) -> JSONResponse:
    hermes_bin = shutil.which("hermes")
    if not hermes_bin:
        return JSONResponse({"error": "hermes CLI not on PATH"}, status_code=500)
    msg = f"Zack shared a file with Nina: {body.name} — download here: {body.url}" if NOTIFY_PEER == "nina" else f"File shared ({body.name}) — download here: {body.url}"
    try:
        out = subprocess.run(
            [hermes_bin, "peer", "dm", NOTIFY_PEER, msg],
            capture_output=True, text=True, timeout=120,
        )
        reply = (out.stdout or "").strip()[:300]
        me, them = "Me", _PEER_CFG["agent"]
        if out.returncode != 0:
            _log_thread(f"{me} → {them} (FAILED)", msg + f"\n\nerror: {(out.stderr or reply)[:200]}")
            return JSONResponse({"error": (out.stderr or reply or "dm failed")[:300]}, status_code=502)
        _log_thread(f"{me} → {them}", msg)
        _log_thread(f"{them} → {me}", reply or "(empty reply)")
        return JSONResponse({"ok": True, "reply": reply})
    except subprocess.TimeoutExpired:
        return JSONResponse({"error": f"{_PEER_CFG['agent']} did not reply in time"}, status_code=504)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@router.post("/share")
def share(body: ShareIn) -> JSONResponse:
    if not body.path or not os.path.isfile(body.path):
        return JSONResponse({"error": "file only"}, status_code=400)
    try:
        _ensure_share_server()
    except OSError as e:
        return JSONResponse({"error": f"share server: {e}"[:200]}, status_code=500)
    token = secrets.token_urlsafe(24)
    with _shares_lock:
        _shares[token] = {"path": body.path, "name": os.path.basename(body.path),
                          "size": os.path.getsize(body.path)}
    url = f"http://{_get_lan_ip()}:{SHARE_PORT}/dl/{token}"
    return JSONResponse({"ok": True, "token": token, "url": url,
                         "name": os.path.basename(body.path)})


@router.post("/shares")
def shares() -> Dict[str, Any]:
    with _shares_lock:
        items = [{"token": k, "name": v["name"], "size": v["size"],
                  "url": f"http://{_get_lan_ip()}:{SHARE_PORT}/dl/{k}"}
                 for k, v in _shares.items()]
    return {"shares": items}


@router.post("/revoke")
def revoke(body: RevokeIn) -> Dict[str, Any]:
    with _shares_lock:
        _shares.pop(body.token, None)
    return {"ok": True}
