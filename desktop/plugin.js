/**
 * Filebox — desktop half of the unified filebox package.
 * Windows-Explorer-style pane: quick access, breadcrumbs, icon grid,
 * search, preview, mkdir. Enable in Settings → Plugins.
 *
 * Plain ESM, loaded uncompiled — jsx() calls, not JSX syntax.
 * Only these imports resolve: @hermes/plugin-sdk, react, react/jsx-runtime.
 */
import {
  atom, Button, Codicon, ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger, GlyphSpinner, host, SearchField, STATUSBAR_AREAS, Tip, usePluginI18n, useQuery, useValue
} from '@hermes/plugin-sdk'
import { useEffect, useMemo, useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'filebox'
const RENDER_CAP = 400
const collapsed = atom(true)
const clipboard = atom(null)
const pendingRename = atom(null)
const pendingDelete = atom(null)
const dirBump = atom(0)

function hasFbPaths(ev) {
  try { return Array.from(ev.dataTransfer?.types || []).includes('application/x-filebox-paths') } catch { return false }
}

function parentDir(p) {
  const d = String(p || '').replace(/[/\\][^/\\]+$/, '')
  return d || p
}
let paneCtx = null
let paneRegister = null
let paneDispose = null

function syncPane() {
  if (!paneCtx || !paneRegister) return
  const open = !collapsed.get()
  if (open && !paneDispose) {
    try { paneDispose = paneRegister() } catch { /* noop */ }
    try { if (host && typeof host.revealPane === 'function') host.revealPane('filebox:filebox-pane') } catch { /* noop */ }
  } else if (!open && paneDispose) {
    try { paneDispose() } catch { /* noop */ }
    paneDispose = null
  }
}

const EN = {
  explorer: 'Explorer',
  quickAccess: 'Quick access',
  thisPC: 'This PC',
  searchFiles: 'Search this folder…',
  back: 'Back', fwd: 'Forward', up: 'Up', refresh: 'Refresh', home: 'Home',
  newFolder: 'New folder', create: 'Create', cancel: 'Cancel',
  showHidden: 'Show hidden files',
  pinFolder: 'Pin this folder', unpinFolder: 'Unpin this folder',
  reveal: 'Show in Explorer', copyPath: 'Copy path', openFile: 'Open',
  rename: 'Rename', save: 'Save',
  copy: 'Copy', cut: 'Cut', paste: 'Paste',
  delete: 'Delete', confirmDelete: 'Confirm delete?',
  compress: 'Compress', extract: 'Extract here',
  openFailed: 'Could not open — revealed the folder instead.',
  items: n => `${n} item${n === 1 ? '' : 's'}`,
  showingFirst: (a, b) => `Showing ${a} of ${b} — refine search`,
  emptyFolder: 'Empty folder.',
  backendDown: 'Backend unreachable — enable filebox and restart the gateway.',
  sortBy: 'Sort',
  sortName: 'Name', sortSize: 'Size', sortDate: 'Modified', sortType: 'Type',
  preview: 'Preview', details: 'Details',
  closePreview: 'Close preview',
  collapse: 'Collapse panel', expand: 'Expand panel',
  binaryFile: 'Binary file — no text preview.',
  mediaBlocked: 'Preview blocked here — use Open instead.',
  bigModel: 'Model too large to preview — use Open instead.',
  resetView: 'Reset view',
  readFull: 'Read full file',
  showLess: 'Show less',
}
const LOCALES = { en: EN }

const CSS = `
.hermes-fb{display:flex;height:100%;min-height:0;color:var(--ui-text-primary)}
.hermes-fb-nav{width:148px;flex-shrink:0;overflow-y:auto;padding:6px 4px;border-right:1px solid var(--ui-stroke-secondary)}
.hermes-fb-group{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--ui-text-quaternary);padding:6px 6px 2px}
.hermes-fb-navbtn{display:flex;align-items:center;gap:6px;width:100%;text-align:left;font-size:12px;color:var(--ui-text-secondary);background:none;border:0;border-radius:4px;padding:4px 6px;cursor:pointer;min-width:0}
.hermes-fb-navbtn:hover{background:var(--chrome-action-hover);color:var(--ui-text-primary)}
.hermes-fb-navbtn[data-on=true]{background:var(--chrome-action-hover);color:var(--ui-accent)}
.hermes-fb-navbtn span:last-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hermes-fb-drivebar{height:3px;border-radius:2px;background:var(--chrome-action-hover);margin:2px 6px 4px;overflow:hidden}
.hermes-fb-drivebar>div{height:100%;background:var(--ui-accent)}
.hermes-fb-main{flex:1;min-width:0;display:flex;flex-direction:column}
.hermes-fb-toolbar{display:flex;align-items:center;gap:2px;padding:4px 6px;flex-shrink:0}
.hermes-fb-tbtn{width:24px;height:24px;display:inline-flex;align-items:center;justify-content:center;font-size:13px;color:var(--ui-text-secondary);background:none;border:0;border-radius:4px;cursor:pointer;flex-shrink:0}
.hermes-fb-tbtn:hover:not(:disabled){background:var(--chrome-action-hover);color:var(--ui-text-primary)}
.hermes-fb-tbtn:disabled{opacity:.3;cursor:default}
.hermes-fb-crumbs{display:flex;align-items:center;gap:0;flex:1;min-width:0;overflow-x:auto;font-size:12px;scrollbar-width:none}
.hermes-fb-crumbs::-webkit-scrollbar{display:none}
.hermes-fb-crumb{background:none;border:0;color:var(--ui-text-secondary);cursor:pointer;padding:3px 5px;border-radius:4px;white-space:nowrap;font-size:12px}
.hermes-fb-crumb:hover{background:var(--chrome-action-hover);color:var(--ui-text-primary)}
.hermes-fb-crumb[data-on=true]{color:var(--ui-accent)}
.hermes-fb-searchrow{display:flex;gap:4px;padding:0 6px 4px;flex-shrink:0;align-items:center}
.hermes-fb-search{flex:1;min-width:0}
.hermes-fb-search input{width:100%}
.hermes-fb-sort{background:transparent;border:1px solid var(--ui-stroke-secondary);border-radius:4px;color:var(--ui-text-secondary);font-size:11px;height:24px;flex-shrink:0}
.hermes-fb-grid{flex:1;min-height:0;overflow-y:auto;padding:2px 6px;display:grid;gap:2px;align-content:start}
.hermes-fb-tile{display:flex;flex-direction:column;align-items:center;gap:2px;background:none;border:1px solid transparent;border-radius:6px;padding:8px 4px 6px;cursor:pointer;min-width:0;color:var(--ui-text-primary)}
.hermes-fb-tile:hover{background:var(--chrome-action-hover)}
.hermes-fb-tile[data-on=true]{border-color:var(--ui-accent);background:var(--chrome-action-hover)}
.hermes-fb-tileicon{color:var(--ui-text-tertiary);display:flex;align-items:center;justify-content:center;flex-shrink:0}
.hermes-fb-tile[data-dir=true] .hermes-fb-tileicon{color:#dcb959}
.hermes-fb-tileimg{border-radius:4px;object-fit:cover;background:var(--chrome-action-hover)}
.hermes-fb-tilename{font-size:11px;line-height:14px;text-align:center;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;word-break:break-word}
.hermes-fb-tilesub{font-size:10px;color:var(--ui-text-quaternary);white-space:nowrap}
.hermes-fb-status{display:flex;gap:8px;font-size:11px;color:var(--ui-text-tertiary);padding:4px 8px;border-top:1px solid var(--ui-stroke-secondary);flex-shrink:0;overflow:hidden;white-space:nowrap}
.hermes-fb-preview{border-top:1px solid var(--ui-stroke-secondary);max-height:44%;overflow-y:auto;padding:6px 8px;flex-shrink:0}
.hermes-fb-preview img{max-width:100%;border-radius:6px}
.hermes-fb-preview pre{font-size:11px;line-height:15px;white-space:pre-wrap;word-break:break-word;color:var(--ui-text-secondary);margin:4px 0 0;font-family:inherit}
.hermes-fb-kv{display:flex;justify-content:space-between;font-size:11px;color:var(--ui-text-secondary);padding:1px 0}
.hermes-fb-kv b{color:var(--ui-text-primary);font-weight:600}
.hermes-fb-actions{display:flex;gap:4px;margin-top:6px;flex-wrap:wrap}
.hermes-fb-mkdir{display:flex;gap:4px;padding:4px 6px;flex-shrink:0}
.hermes-fb-mkdir input{flex:1;min-width:0;height:24px;font-size:12px;padding:0 6px;border-radius:4px;border:1px solid var(--ui-stroke-secondary);background:transparent;color:var(--ui-text-primary)}
.hermes-fb-error{font-size:11px;color:var(--ui-text-secondary);padding:8px}
.hermes-fb-tabs{display:flex;align-items:center;gap:2px;padding:4px 6px 0;flex-shrink:0;overflow-x:auto;scrollbar-width:none;border-bottom:1px solid var(--ui-stroke-secondary)}
.hermes-fb-tab{display:inline-flex;align-items:center;gap:5px;max-width:150px;font-size:11px;color:var(--ui-text-secondary);background:none;border:1px solid transparent;border-bottom:0;border-radius:6px 6px 0 0;padding:4px 6px;cursor:pointer;white-space:nowrap;flex-shrink:0}
.hermes-fb-tab:hover{color:var(--ui-text-primary)}
.hermes-fb-tab[data-on=true]{background:var(--chrome-action-hover);color:var(--ui-text-primary);border-color:var(--ui-stroke-secondary)}
.hermes-fb-tab span:first-child{overflow:hidden;text-overflow:ellipsis}
.hermes-fb-tabx{background:none;border:0;color:var(--ui-text-quaternary);cursor:pointer;font-size:13px;line-height:1;padding:0 2px;border-radius:3px}
.hermes-fb-tabx:hover{color:var(--ui-text-primary)}
.hermes-fb-grip{width:6px;cursor:col-resize;flex-shrink:0;border-right:1px solid var(--ui-stroke-secondary)}
.hermes-fb-grip:hover{background:var(--ui-accent)}
.hermes-fb-rail{width:26px;flex-shrink:0;display:flex;flex-direction:column;align-items:center;padding-top:6px;border-right:1px solid var(--ui-stroke-secondary)}
.hermes-fb-opsbar{display:flex;gap:4px;flex-wrap:wrap;align-items:center;padding:6px 8px;border-bottom:1px solid var(--ui-stroke-secondary)}
.hermes-fb-pvwrap{display:flex;flex-direction:column;flex-shrink:0;min-height:0;border-top:1px solid var(--ui-stroke-secondary)}
.hermes-fb-pvwrap .hermes-fb-preview{border-top:0;flex:1;min-height:0;max-height:none}
.hermes-fb-griph{height:6px;cursor:row-resize;flex-shrink:0}
.hermes-fb-griph:hover{background:var(--ui-accent)}
.hermes-fb-tile[data-drop=true]{border-color:var(--ui-accent);background:var(--chrome-action-hover)}
`

const CODE_EXTS = new Set(['.py', '.js', '.ts', '.tsx', '.jsx', '.mjs', '.cjs', '.json', '.yaml', '.yml', '.toml', '.md', '.txt', '.log', '.ini', '.cfg', '.css', '.html', '.xml', '.csv', '.ps1', '.bat', '.sh', '.java', '.c', '.cpp', '.h', '.rs', '.go', '.kt', '.sql', '.vue'])
const IMG_EXTS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico', '.tif', '.tiff'])
const VID_EXTS = new Set(['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.webm', '.m4v', '.ts'])
const AUD_EXTS = new Set(['.mp3', '.wav', '.flac', '.ogg', '.m4a', '.opus', '.wma'])
const MODEL_EXTS = new Set(['.stl', '.obj'])
const ZIP_EXTS = new Set(['.zip', '.7z', '.rar', '.tar', '.gz'])

function category(e) {
  if (e.is_dir) return 'dir'
  if (IMG_EXTS.has(e.ext)) return 'img'
  if (AUD_EXTS.has(e.ext)) return 'audio'
  if (VID_EXTS.has(e.ext)) return 'video'
  if (MODEL_EXTS.has(e.ext)) return 'model'
  if (ZIP_EXTS.has(e.ext)) return 'zip'
  if (CODE_EXTS.has(e.ext)) return 'code'
  if (e.ext === '.pdf') return 'pdf'
  return 'file'
}

function iconFor(cat) {
  switch (cat) {
    case 'dir': return 'folder'
    case 'img': case 'audio': case 'video': return 'file-media'
    case 'zip': return 'file-zip'
    case 'code': return 'file-code'
    case 'pdf': return 'file-pdf'
    default: return 'file'
  }
}

function fmtSize(b) {
  b = Number(b) || 0
  if (b >= 1073741824) return `${(b / 1073741824).toFixed(1)} GB`
  if (b >= 1048576) return `${(b / 1048576).toFixed(1)} MB`
  if (b >= 1024) return `${(b / 1024).toFixed(0)} KB`
  return `${b} B`
}

function fmtDate(epoch) {
  if (!epoch) return '—'
  const d = new Date(epoch * 1000)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  if (sameDay) return time
  return `${d.toLocaleDateString([], { month: 'numeric', day: 'numeric', year: d.getFullYear() === now.getFullYear() ? undefined : 'numeric' })} ${time}`
}

function splitPath(path) {
  const parts = path.split(/[/\\]+/).filter(Boolean)
  if (/^[A-Za-z]:$/.test(parts[0])) parts[0] = `${parts[0]}\\`
  return parts
}

function thumbKind(ext) {
  if (IMG_EXTS.has(ext)) return 'img'
  if (VID_EXTS.has(ext)) return 'video'
  if (MODEL_EXTS.has(ext)) return 'model'
  return null
}

function Thumb({ ctx, entry, px, fallback }) {
  const kind = thumbKind(entry.ext)
  const ep = kind === 'video' ? '/videothumb' : kind === 'model' ? '/modelthumb' : '/thumb'
  const q = useQuery({
    queryKey: [ID, ep, entry.path, entry.mtime],
    queryFn: ({ signal }) => ctx.rest(ep, { method: 'POST', timeoutMs: 30000, signal, body: { path: entry.path, size: 256 } }),
    enabled: !!kind,
    staleTime: 300000,
    retry: false,
  })
  if (!kind || q.isError) return fallback || null
  if (!q.data?.data_url) return null
  return jsx('img', { className: 'hermes-fb-tileimg', src: q.data.data_url, alt: '', loading: 'lazy', style: { width: px, height: px } })
}

function fileUrl(path) {
  return 'file:///' + String(path || '').replace(/\\/g, '/').split('/').map(encodeURIComponent).join('/')
}

function parseModel(ext, bytes) {
  const capTris = 12000
  if (ext === '.obj') {
    const text = new TextDecoder().decode(bytes.slice(0, 32 * 1024 * 1024))
    const verts = []
    const out = []
    for (const line of text.split('\n')) {
      if (line[0] === 'v' && line[1] === ' ') {
        const p = line.split(/\s+/)
        verts.push([+p[1], +p[2], +p[3]])
      } else if (line[0] === 'f' && line[1] === ' ') {
        const idx = line.slice(1).trim().split(/\s+/).map(s => parseInt(s.split('/')[0], 10) - 1)
        for (let k = 1; k < idx.length - 1 && out.length < capTris * 9; k++) {
          for (const j of [idx[0], idx[k], idx[k + 1]]) {
            const v = verts[j]
            if (v && v.every(Number.isFinite)) out.push(v[0], v[1], v[2])
          }
        }
      }
      if (out.length >= capTris * 9) break
    }
    const n = Math.floor(out.length / 9)
    return n ? { tris: new Float32Array(out.slice(0, n * 9)), n } : null
  }
  if (bytes.length > 84) {
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    const count = dv.getUint32(80, true)
    if (count > 0 && count < 3000000 && 84 + count * 50 === bytes.length) {
      const stride = Math.max(1, Math.ceil(count / capTris))
      const out = []
      for (let i = 0; i < count; i += stride) {
        const o = 84 + i * 50 + 12
        for (let k = 0; k < 9; k++) out.push(dv.getFloat32(o + k * 4, true))
      }
      return { tris: new Float32Array(out), n: Math.floor(out.length / 9) }
    }
  }
  const text = new TextDecoder().decode(bytes.slice(0, 64 * 1024 * 1024))
  const re = /vertex\s+(\S+)\s+(\S+)\s+(\S+)/g
  const out = []
  let m
  while ((m = re.exec(text)) && out.length < capTris * 9) out.push(+m[1], +m[2], +m[3])
  const n = Math.floor(out.length / 9)
  return n ? { tris: new Float32Array(out.slice(0, n * 9)), n } : null
}

function drawModel(canvas, geo, rx, ry, zoom) {
  const W = canvas.width, H = canvas.height
  const g = canvas.getContext('2d')
  g.fillStyle = '#141419'
  g.fillRect(0, 0, W, H)
  const { tris, n } = geo
  const b = geo.bounds
  const span = Math.max(b.x1 - b.x0, b.y1 - b.y0, b.z1 - b.z0, 1e-9)
  const s = Math.min(W, H) * 0.42 * zoom / span
  const ox = W / 2, oy = H / 2
  const cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2, cz = (b.z0 + b.z1) / 2
  const c1 = Math.cos(ry), s1 = Math.sin(ry), c2 = Math.cos(rx), s2 = Math.sin(rx)
  const items = []
  for (let i = 0; i < n; i++) {
    const p = []
    for (let k = 0; k < 3; k++) {
      const X = tris[i * 9 + k * 3] - cx, Y = tris[i * 9 + k * 3 + 1] - cy, Z = tris[i * 9 + k * 3 + 2] - cz
      const x1 = X * c1 + Z * s1, z1 = -X * s1 + Z * c1
      const y1 = Y * c2 - z1 * s2, z2 = Y * s2 + z1 * c2
      p.push(ox + x1 * s, oy - y1 * s, z2)
    }
    const ex = p[3] - p[0], ey = p[4] - p[1], ez = p[5] - p[2]
    const fx = p[6] - p[0], fy = p[7] - p[1], fz = p[8] - p[2]
    const nx = ey * fz - ez * fy, ny = ez * fx - ex * fz, nz = ex * fy - ey * fx
    const ln = Math.sqrt(nx * nx + ny * ny + nz * nz) + 1e-9
    const shade = Math.abs((nx * 0.4 + ny * 0.5 + nz * 0.75) / ln / 1.05)
    items.push({ p, d: (p[2] + p[5] + p[8]) / 3, v: Math.round(45 + 175 * Math.min(1, 0.15 + 0.85 * shade)) })
  }
  items.sort((a, b) => a.d - b.d)
  for (const it of items) {
    const v = it.v
    g.fillStyle = `rgb(${v},${v},${Math.min(255, v + 12)})`
    g.beginPath()
    g.moveTo(it.p[0], it.p[1])
    g.lineTo(it.p[3], it.p[4])
    g.lineTo(it.p[6], it.p[7])
    g.closePath()
    g.fill()
  }
}

function ModelView({ ctx, t, entry }) {
  const ref = useRef(null)
  const [rot, setRot] = useState({ x: 0.5, y: 0.6, z: 1 })
  const q = useQuery({
    queryKey: [ID, 'raw', entry.path, entry.mtime],
    queryFn: ({ signal }) => ctx.rest('/raw', { method: 'POST', timeoutMs: 30000, signal, body: { path: entry.path, max_mb: 48 } }),
    enabled: entry.size < 96 * 1024 * 1024,
    staleTime: 300000,
    retry: false,
  })
  const geo = useMemo(() => {
    if (!q.data?.b64) return null
    try {
      const bin = Uint8Array.from(atob(q.data.b64), c => c.charCodeAt(0))
      const parsed = parseModel(entry.ext, bin)
      if (!parsed || !parsed.tris.every(Number.isFinite)) return { error: true }
      let x0 = 1 / 0, y0 = 1 / 0, z0 = 1 / 0, x1 = -1 / 0, y1 = -1 / 0, z1 = -1 / 0
      const tr = parsed.tris
      for (let i = 0; i < tr.length; i += 3) {
        const X = tr[i], Y = tr[i + 1], Z = tr[i + 2]
        if (X < x0) x0 = X; if (X > x1) x1 = X
        if (Y < y0) y0 = Y; if (Y > y1) y1 = Y
        if (Z < z0) z0 = Z; if (Z > z1) z1 = Z
      }
      return { ...parsed, bounds: { x0, y0, z0, x1, y1, z1 } }
    } catch { return { error: true } }
  }, [q.data])
  useEffect(() => {
    if (ref.current && geo && !geo.error) {
      try { drawModel(ref.current, geo, rot.x, rot.y, rot.z) } catch { /* noop */ }
    }
  }, [geo, rot])
  const startSpin = e => {
    e.preventDefault()
    const sx = e.clientX, sy = e.clientY
    const r0 = { ...rot }
    const move = ev => setRot(r => ({ ...r, x: r0.x + (ev.clientY - sy) * 0.01, y: r0.y + (ev.clientX - sx) * 0.01 }))
    const up = () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up) }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }
  if (entry.size >= 96 * 1024 * 1024) return jsx('div', { className: 'hermes-fb-error', children: t('bigModel') })
  if (q.isError) return jsx('div', { className: 'hermes-fb-error', children: t('mediaBlocked') })
  if (!geo) return jsx(GlyphSpinner, { ariaLabel: entry.name })
  if (geo.error) return jsx('div', { className: 'hermes-fb-error', children: t('mediaBlocked') })
  return jsxs('div', { children: [
    jsx('canvas', { ref, width: 560, height: 340, onMouseDown: startSpin, style: { width: '100%', borderRadius: 6, marginTop: 4, cursor: 'grab', background: '#141419', touchAction: 'none' } }),
    jsxs('div', { className: 'hermes-fb-actions', children: [
      jsx('span', { className: 'hermes-fb-tilesub', children: `${geo.n} tris · drag to rotate` }),
      jsx('span', { style: { flex: 1 } }),
      jsx(Button, { size: 'micro', variant: 'ghost', onClick: () => setRot(r => ({ ...r, z: Math.max(0.3, +(r.z / 1.25).toFixed(2)) })), children: '−' }),
      jsx(Button, { size: 'micro', variant: 'ghost', onClick: () => setRot(r => ({ ...r, z: Math.min(5, +(r.z * 1.25).toFixed(2)) })), children: '+' }),
      jsx(Button, { size: 'micro', variant: 'ghost', onClick: () => setRot({ x: 0.5, y: 0.6, z: 1 }), children: t('resetView') }),
    ] }),
  ] })
}

function Preview({ ctx, t, entry, refetch, select }) {
  const isImg = IMG_EXTS.has(entry.ext)
  const isAudio = AUD_EXTS.has(entry.ext)
  const isVideo = VID_EXTS.has(entry.ext)
  const isModel = MODEL_EXTS.has(entry.ext)
  const isTextish = !entry.is_dir && !isImg && !isAudio && !isVideo && !isModel && entry.ext !== '.pdf'
  const isPdf = !entry.is_dir && entry.ext === '.pdf'
  const [mediaErr, setMediaErr] = useState(false)
  const [fullRead, setFullRead] = useState(false)
  const [renameMode, setRenameMode] = useState(false)
  const [renameName, setRenameName] = useState(entry.name)
  const [confirmDel, setConfirmDel] = useState(false)
  const [opBusy, setOpBusy] = useState(false)
  const clip = useValue(clipboard)
  const opErr = e => hostNotify(ctx, String((e && e.data && e.data.error) || (e && e.message) || e))
  if (pendingRename.get() === entry.path) { pendingRename.set(null); if (!renameMode) { setRenameName(entry.name); setConfirmDel(false); setRenameMode(true) } }
  if (pendingDelete.get() === entry.path) { pendingDelete.set(null); if (!confirmDel) setConfirmDel(true) }
  const doPasteHere = async () => {
    const c = clipboard.get()
    if (!c) return
    const dest = entry.path.replace(/[/\\][^/\\]+$/, '') || entry.path
    setOpBusy(true)
    try {
      const r = await ctx.rest(c.mode === 'cut' ? '/move' : '/copy', { method: 'POST', timeoutMs: 60000, body: { paths: c.paths, dest_dir: dest } })
      if (!r?.ok) opErr((r?.failed?.[0]?.error) || 'paste failed')
      else if (c.mode === 'cut') clipboard.set(null)
      refetch()
    } catch (e) { opErr(e) }
    setOpBusy(false)
  }
  const doRename = async () => {
    const name = (renameName || '').trim()
    if (!name || name === entry.name) { setRenameMode(false); return }
    setOpBusy(true)
    try {
      const r = await ctx.rest('/rename', { method: 'POST', timeoutMs: 15000, body: { path: entry.path, new_name: name } })
      setRenameMode(false)
      refetch()
      if (r?.path) select(r.path)
    } catch (e) { opErr(e) }
    setOpBusy(false)
  }
  const doDelete = async () => {
    if (!confirmDel) { setConfirmDel(true); return }
    setOpBusy(true)
    try {
      const r = await ctx.rest('/delete', { method: 'POST', timeoutMs: 30000, body: { paths: [entry.path] } })
      if (!r?.ok) opErr((r?.failed?.[0]?.error) || 'delete failed')
      select(null)
      refetch()
    } catch (e) { opErr(e) }
    setConfirmDel(false)
    setOpBusy(false)
  }
  const doZip = async () => {
    setOpBusy(true)
    try {
      await ctx.rest('/zip', { method: 'POST', timeoutMs: 60000, body: { paths: [entry.path] } })
      refetch()
    } catch (e) { opErr(e) }
    setOpBusy(false)
  }
  const doExtract = async () => {
    setOpBusy(true)
    try {
      const r = await ctx.rest('/extract', { method: 'POST', timeoutMs: 60000, body: { path: entry.path } })
      if (r?.path) hostNotify(ctx, 'Extracted to ' + r.path)
      refetch()
    } catch (e) { opErr(e) }
    setOpBusy(false)
  }
  const thumb = useQuery({
    queryKey: [ID, 'thumb', entry.path, entry.mtime, 'pv'],
    queryFn: ({ signal }) => ctx.rest('/thumb', { method: 'POST', timeoutMs: 15000, signal, body: { path: entry.path, size: 512 } }),
    enabled: isImg,
    staleTime: 300000,
    retry: false,
  })
  const text = useQuery({
    queryKey: [ID, 'read', entry.path, entry.mtime],
    queryFn: ({ signal }) => ctx.rest('/read', { method: 'POST', timeoutMs: 15000, signal, body: { path: entry.path, max_kb: 64 } }),
    enabled: isTextish && entry.size < 2 * 1024 * 1024,
    staleTime: 60000,
    retry: false,
  })
  const full = useQuery({
    queryKey: [ID, 'readfull', entry.path, entry.mtime],
    queryFn: ({ signal }) => ctx.rest('/read', { method: 'POST', timeoutMs: 20000, signal, body: { path: entry.path, max_kb: 1024 } }),
    enabled: fullRead && isTextish,
    staleTime: 60000,
    retry: false,
  })
  const openFile = async () => {
    const url = `file:///${entry.path.replace(/\\/g, '/')}`
    try {
      const ok = await ctx.os.openExternal(url)
      if (!ok) throw new Error('no handler')
    } catch {
      try { await ctx.os.revealPath(entry.path.replace(/[/\\][^/\\]+$/, '') || entry.path) } catch { /* noop */ }
      hostNotify(ctx, t('openFailed'))
    }
  }
  return jsxs('div', { className: 'hermes-fb-preview', children: [
    jsxs('div', { className: 'hermes-fb-opsbar', children: [
      jsx(Button, { size: 'micro', variant: 'ghost', onClick: () => ctx.os.writeClipboard(entry.path), children: t('copyPath') }),
      renameMode && jsx('input', { value: renameName, onChange: e => setRenameName(e.target.value), onKeyDown: e => { if (e.key === 'Enter') doRename() }, autoFocus: true, 'aria-label': t('rename'), style: { flex: 1, minWidth: 60, height: 24, fontSize: 12, padding: '0 6px', borderRadius: 4, border: '1px solid var(--ui-stroke-secondary)', background: 'transparent', color: 'var(--ui-text-primary)' } }),
      renameMode && jsx(Button, { size: 'micro', onClick: doRename, disabled: opBusy, children: t('save') }),
      renameMode && jsx(Button, { size: 'micro', variant: 'ghost', onClick: () => setRenameMode(false), children: t('cancel') }),
      !renameMode && jsx(Button, { size: 'micro', variant: 'ghost', onClick: () => { setRenameName(entry.name); setConfirmDel(false); setRenameMode(true) }, children: t('rename') }),
      jsx(Button, { size: 'micro', variant: 'ghost', onClick: () => clipboard.set({ mode: 'copy', paths: [entry.path], label: entry.name }), children: t('copy') }),
      jsx(Button, { size: 'micro', variant: 'ghost', onClick: () => clipboard.set({ mode: 'cut', paths: [entry.path], label: entry.name }), children: t('cut') }),
      jsx(Button, { size: 'micro', variant: 'ghost', onClick: doPasteHere, disabled: !clip || opBusy, children: t('paste') }),
      jsx(Button, { size: 'micro', variant: 'ghost', onClick: doDelete, disabled: opBusy, children: confirmDel ? t('confirmDelete') : t('delete') }),
      jsx(Button, { size: 'micro', variant: 'ghost', onClick: doZip, disabled: opBusy, children: t('compress') }),
      entry.ext === '.zip' && jsx(Button, { size: 'micro', variant: 'ghost', onClick: doExtract, disabled: opBusy, children: t('extract') }),
      jsx('span', { style: { flex: 1 } }),
      jsx('button', { className: 'hermes-fb-tbtn', style: { width: 20, height: 20, fontSize: 12 }, title: t('closePreview'), onClick: () => select(null), children: '×' }),
    ] }),
    jsxs('div', { className: 'hermes-fb-kv', children: [jsx('span', { children: t('details') }), jsx('b', { children: entry.name })] }),
    jsxs('div', { className: 'hermes-fb-kv', children: [jsx('span', { children: 'Size' }), jsx('b', { children: entry.is_dir ? '—' : fmtSize(entry.size) })] }),
    jsxs('div', { className: 'hermes-fb-kv', children: [jsx('span', { children: 'Modified' }), jsx('b', { children: fmtDate(entry.mtime) })] }),
    isImg && thumb.data?.data_url && jsx('img', { src: thumb.data.data_url, alt: entry.name, loading: 'lazy' }),
    isAudio && !mediaErr && jsx('audio', { controls: true, preload: 'metadata', src: fileUrl(entry.path), style: { width: '100%', marginTop: 4 }, onError: () => setMediaErr(true) }),
    isVideo && !mediaErr && jsx('video', { controls: true, preload: 'metadata', src: fileUrl(entry.path), style: { width: '100%', maxHeight: 240, background: '#000', borderRadius: 6, marginTop: 4 }, onError: () => setMediaErr(true) }),
    (isAudio || isVideo) && mediaErr && jsx('div', { className: 'hermes-fb-error', children: t('mediaBlocked') }),
    isPdf && !mediaErr && jsx('iframe', { src: fileUrl(entry.path), title: entry.name, style: { width: '100%', height: 480, border: 0, borderRadius: 6, marginTop: 4, background: '#fff' }, onError: () => setMediaErr(true) }),
    isPdf && mediaErr && jsx('div', { className: 'hermes-fb-error', children: t('mediaBlocked') }),
    isModel && jsx(ModelView, { ctx, t, entry }),
    isTextish && text.data && !fullRead && (text.data.is_binary
      ? jsx('div', { className: 'hermes-fb-error', children: t('binaryFile') })
      : jsxs('div', { children: [
        jsx('pre', { children: (text.data.text || '') + (text.data.truncated ? '…' : '') }),
        text.data.truncated && jsx(Button, { size: 'micro', variant: 'ghost', onClick: () => setFullRead(true), children: t('readFull') }),
      ] })),
    isTextish && fullRead && jsxs('div', { children: [
      full.isFetching && jsx(GlyphSpinner, { ariaLabel: t('readFull') }),
      full.data && !full.data.is_binary && jsx('pre', { children: (full.data.text || '') + (full.data.truncated ? '…' : '') }),
      full.data && full.data.is_binary && jsx('div', { className: 'hermes-fb-error', children: t('binaryFile') }),
      jsx(Button, { size: 'micro', variant: 'ghost', onClick: () => setFullRead(false), children: t('showLess') }),
    ] }),
    jsxs('div', { className: 'hermes-fb-actions', children: [
      !entry.is_dir && jsx(Button, { size: 'micro', onClick: openFile, children: t('openFile') }),
      jsx(Button, { size: 'micro', variant: 'ghost', onClick: () => ctx.os.revealPath(entry.is_dir ? entry.path : entry.path.replace(/[/\\][^/\\]+$/, '')), children: t('reveal') }),
    ] }),
  ] })
}

function hostNotify(ctx, message) {
  try {
    if (ctx.host && typeof ctx.host.notify === 'function') ctx.host.notify({ kind: 'info', message })
  } catch { /* noop */ }
}

function TabPane({ ctx, tabId, initialCwd, sort, setSort, tilePx, setTilePx, showHidden, setShowHidden, sideWidth, setSideWidth, sideCollapsed, setSideCollapsed, previewH, setPreviewH, hidden }) {
  const t = usePluginI18n(ID)
  const [cwd, setCwd] = useState(initialCwd || null)
  const [back, setBack] = useState([])
  const [fwd, setFwd] = useState([])
  const [selected, setSelected] = useState(null)
  const [search, setSearch] = useState('')
  const [pins, setPins] = useState(() => ctx.storage.get('pins', null))
  const [mkdirMode, setMkdirMode] = useState(false)
  const [mkdirName, setMkdirName] = useState('')
  const [dropPath, setDropPath] = useState(null)
  const bump = useValue(dirBump)

  const roots = useQuery({
    queryKey: [ID, 'roots'],
    queryFn: ({ signal }) => ctx.rest('/roots', { method: 'POST', timeoutMs: 15000, signal, body: {} }),
    staleTime: 600000,
    retry: false,
  })

  const home = roots.data?.home || null
  const pinsEffective = pins || (home ? [home] : [])

  const list = useQuery({
    queryKey: [ID, 'list', cwd, showHidden, bump],
    queryFn: ({ signal }) => ctx.rest('/list', { method: 'POST', timeoutMs: 20000, signal, body: { path: cwd, show_hidden: showHidden } }),
    enabled: !!cwd,
    staleTime: 10000,
    retry: false,
  })

  const nav = (path, push = true) => {
    if (!path || path === cwd) return
    if (push && cwd) {
      setBack(b => [...b.slice(-49), cwd])
      setFwd([])
    }
    setCwd(path)
    setSelected(null)
    setSearch('')
  }

  const goBack = () => {
    if (!back.length) return
    const prev = back[back.length - 1]
    setBack(b => b.slice(0, -1))
    if (cwd) setFwd(f => [cwd, ...f].slice(0, 50))
    setCwd(prev)
    setSelected(null)
    setSearch('')
  }

  const goFwd = () => {
    if (!fwd.length) return
    const [next, ...rest] = fwd
    setFwd(rest)
    if (cwd) setBack(b => [...b.slice(-49), cwd])
    setCwd(next)
    setSelected(null)
    setSearch('')
  }

  const entries = useMemo(() => {
    const all = list.data?.entries ?? []
    const q = search.trim().toLowerCase()
    const filtered = q ? all.filter(e => e.name.toLowerCase().includes(q)) : all
    const cmp = {
      name: (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }),
      size: (a, b) => (b.size - a.size) || a.name.localeCompare(b.name),
      mtime: (a, b) => (b.mtime - a.mtime) || a.name.localeCompare(b.name),
      type: (a, b) => (a.ext.localeCompare(b.ext)) || a.name.localeCompare(b.name),
    }[sort] || ((a, b) => 0)
    return [...filtered].sort((a, b) => ((b.is_dir ? 1 : 0) - (a.is_dir ? 1 : 0)) || cmp(a, b))
  }, [list.data, search, sort])

  const total = list.data?.total ?? entries.length
  const shown = entries.slice(0, RENDER_CAP)
  const crumbs = cwd ? splitPath(cwd) : []
  const selEntry = selected ? entries.find(e => e.path === selected) : null
  const pinned = cwd && pinsEffective.includes(cwd)

  const togglePin = () => {
    if (!cwd) return
    const next = pinned ? pinsEffective.filter(p => p !== cwd) : [...pinsEffective, cwd]
    setPins(next)
    ctx.storage.set('pins', next)
  }

  const doMkdir = async () => {
    const name = mkdirName.trim()
    if (!name || !cwd) return
    try {
      await ctx.rest('/mkdir', { method: 'POST', timeoutMs: 15000, body: { parent: cwd, name } })
      setMkdirName('')
      setMkdirMode(false)
      list.refetch()
    } catch { /* error surfaces on next list load */ }
  }

  const startDrag = e => {
    e.preventDefault()
    const x0 = e.clientX
    const w0 = sideWidth
    const move = ev => setSideWidth(Math.min(320, Math.max(80, Math.round(w0 + ev.clientX - x0))))
    const up = () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up) }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }

  const pasteTo = async dest => {
    const c = clipboard.get()
    if (!c || !dest) return
    try {
      const r = await ctx.rest(c.mode === 'cut' ? '/move' : '/copy', { method: 'POST', timeoutMs: 60000, body: { paths: c.paths, dest_dir: dest } })
      if (!r?.ok) hostNotify(ctx, ((r?.failed?.[0]?.error) || 'paste failed'))
      else if (c.mode === 'cut') clipboard.set(null)
      list.refetch()
    } catch (e) { hostNotify(ctx, String((e && e.message) || e)) }
  }

  const dropMove = async (paths, dest) => {
    const final = (paths || []).filter(p => typeof p === 'string' && p && p !== dest && parentDir(p) !== dest)
    if (!final.length || !dest) return
    try {
      const r = await ctx.rest('/move', { method: 'POST', timeoutMs: 60000, body: { paths: final, dest_dir: dest } })
      if (!r?.ok) hostNotify(ctx, (r?.failed?.[0]?.error) || 'move failed')
      dirBump.set(dirBump.get() + 1)
    } catch (e) { hostNotify(ctx, String((e && e.message) || e)) }
  }

  const quickOp = async (kind, target) => {
    try {
      if (kind === 'open') { openEntry(target); return }
      if (kind === 'rename') { pendingRename.set(target.path); setSelected(target.path); return }
      if (kind === 'delete') { pendingDelete.set(target.path); setSelected(target.path); return }
      if (kind === 'copy') { clipboard.set({ mode: 'copy', paths: [target.path], label: target.name }); return }
      if (kind === 'cut') { clipboard.set({ mode: 'cut', paths: [target.path], label: target.name }); return }
      if (kind === 'paste') { await pasteTo(target.is_dir ? target.path : cwd); return }
      if (kind === 'copypath') { await ctx.os.writeClipboard(target.path); return }
      if (kind === 'reveal') { await ctx.os.revealPath(target.is_dir ? target.path : target.path.replace(/[/\\][^/\\]+$/, '')); return }
      if (kind === 'compress') await ctx.rest('/zip', { method: 'POST', timeoutMs: 60000, body: { paths: [target.path] } })
      else if (kind === 'extract') await ctx.rest('/extract', { method: 'POST', timeoutMs: 60000, body: { path: target.path } })
      list.refetch()
    } catch (e) { hostNotify(ctx, String((e && e.message) || e)) }
  }

  const startPreviewDrag = e => {
    e.preventDefault()
    const y0 = e.clientY
    const h0 = previewH
    const move = ev => setPreviewH(Math.min(640, Math.max(140, Math.round(h0 + (y0 - ev.clientY)))))
    const up = () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up) }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }

  const openEntry = async e => {
    if (e.is_dir) { nav(e.path); return }
    const url = `file:///${e.path.replace(/\\/g, '/')}`
    try {
      const ok = await ctx.os.openExternal(url)
      if (!ok) throw new Error('no handler')
    } catch {
      try { await ctx.os.revealPath(e.path.replace(/[/\\][^/\\]+$/, '')) } catch { /* noop */ }
    }
  }

  if (!cwd && home) setCwd(home)

  return jsxs('div', { className: 'hermes-fb', style: hidden ? { display: 'none' } : { flex: 1, minHeight: 0, height: 'auto' }, children: [
    sideCollapsed && jsx('div', { className: 'hermes-fb-rail', children:
      jsx('button', { className: 'hermes-fb-tbtn', title: 'Show sidebar', onClick: () => setSideCollapsed(false), children: '»' }),
    }),
    !sideCollapsed && jsxs('div', { className: 'hermes-fb-nav', style: { width: sideWidth }, children: [
      jsxs('div', { style: { display: 'flex', alignItems: 'center' }, children: [
        jsx('div', { className: 'hermes-fb-group', style: { flex: 1 }, children: t('quickAccess') }),
        jsx('button', { className: 'hermes-fb-tbtn', style: { width: 20, height: 20, fontSize: 11 }, title: 'Hide sidebar', onClick: () => setSideCollapsed(true), children: '«' }),
      ] }),
      ...pinsEffective.map(p => jsx('button', {
        className: 'hermes-fb-navbtn', 'data-on': p === cwd,
        onClick: () => nav(p),
        children: [jsx(Codicon, { name: 'folder' }), jsx('span', { children: p.split(/[/\\]+/).filter(Boolean).pop() || p })],
      }, `pin:${p}`)),
      jsx('div', { className: 'hermes-fb-group', children: t('thisPC') }),
      ...(roots.data?.drives ?? []).map(d => jsxs('div', { children: [
        jsx('button', {
          className: 'hermes-fb-navbtn', 'data-on': d.mount === cwd,
          onClick: () => nav(d.mount),
          children: [jsx(Codicon, { name: 'device-hard-drive' }), jsx('span', { children: `${d.device} · ${d.total_gb} GB` })],
        }),
        jsx('div', { className: 'hermes-fb-drivebar', children: jsx('div', { style: { width: `${d.percent}%` } }) }),
      ] }, `drive:${d.mount}`)),
    ] }),
    !sideCollapsed && jsx('div', { className: 'hermes-fb-grip', onMouseDown: startDrag }),
    jsxs('div', { className: 'hermes-fb-main', children: [
      jsxs('div', { className: 'hermes-fb-toolbar', children: [
        jsx('button', { className: 'hermes-fb-tbtn', disabled: !back.length, 'aria-label': t('back'), title: t('back'), onClick: goBack, children: '←' }),
        jsx('button', { className: 'hermes-fb-tbtn', disabled: !fwd.length, 'aria-label': t('fwd'), title: t('fwd'), onClick: goFwd, children: '→' }),
        jsx('button', { className: 'hermes-fb-tbtn', disabled: !list.data?.parent, 'aria-label': t('up'), title: t('up'), onClick: () => list.data?.parent && nav(list.data.parent), children: '↑' }),
        jsx('button', { className: 'hermes-fb-tbtn', 'aria-label': t('refresh'), title: t('refresh'), onClick: () => list.refetch(), children: '↻' }),
        jsx('div', { className: 'hermes-fb-crumbs', children:
          crumbs.map((c, i) => {
            const upto = crumbs.slice(0, i + 1).join('\\') + (i === 0 && /^[A-Za-z]:\\$/.test(c) ? '' : '')
            const full = i === 0 ? c : `${crumbs[0]}${crumbs.slice(1, i + 1).join('\\')}`
            return jsxs('span', { style: { display: 'inline-flex', alignItems: 'center', flexShrink: 0 }, children: [
              i > 0 && jsx('span', { style: { color: 'var(--ui-text-quaternary)' }, children: '›' }),
              jsx('button', { className: 'hermes-fb-crumb', 'data-on': i === crumbs.length - 1, onClick: () => nav(full), children: c.replace(/\\$/, '') }),
            ] }, i)
          }),
        }),
        jsx('button', { className: 'hermes-fb-tbtn', title: pinned ? t('unpinFolder') : t('pinFolder'), onClick: () => togglePin(cwd), children: pinned ? '★' : '☆' }),
      ] }),
      jsxs('div', { className: 'hermes-fb-searchrow', children: [
        jsx('div', { className: 'hermes-fb-search', children: jsx(SearchField, {
          value: search, onChange: setSearch, placeholder: t('searchFiles'),
          containerClassName: '',
        }) }),
        jsx('select', { className: 'hermes-fb-sort', value: sort, 'aria-label': t('sortBy'), onChange: e => setSort(e.target.value), children: [
          jsx('option', { value: 'name', children: t('sortName') }),
          jsx('option', { value: 'size', children: t('sortSize') }),
          jsx('option', { value: 'mtime', children: t('sortDate') }),
          jsx('option', { value: 'type', children: t('sortType') }),
        ] }),
        jsx('select', { className: 'hermes-fb-sort', value: tilePx, 'aria-label': 'tile size', onChange: e => setTilePx(Number(e.target.value)), children: [
          jsx('option', { value: 64, children: 'S' }),
          jsx('option', { value: 88, children: 'M' }),
          jsx('option', { value: 112, children: 'L' }),
          jsx('option', { value: 144, children: 'XL' }),
        ] }),
      ] }),
      mkdirMode && jsxs('div', { className: 'hermes-fb-mkdir', children: [
        jsx('input', { value: mkdirName, placeholder: t('newFolder'), onChange: e => setMkdirName(e.target.value), onKeyDown: e => { if (e.key === 'Enter') doMkdir() } }),
        jsx(Button, { size: 'micro', onClick: doMkdir, children: t('create') }),
        jsx(Button, { size: 'micro', variant: 'ghost', onClick: () => { setMkdirMode(false); setMkdirName('') }, children: t('cancel') }),
      ] }),
      jsxs('div', { className: 'hermes-fb-grid', style: { gridTemplateColumns: `repeat(auto-fill,minmax(${tilePx + 16}px,1fr))` }, onDragOver: ev => { if (hasFbPaths(ev)) ev.preventDefault() }, onDrop: ev => {
        if (ev.target?.closest && ev.target.closest('[data-dir="true"]')) return
        ev.preventDefault()
        try { dropMove(JSON.parse(ev.dataTransfer.getData('application/x-filebox-paths') || '[]'), cwd) } catch {}
      }, children: [
        list.isFetching && !list.data && jsx(GlyphSpinner, { ariaLabel: t('explorer') }),
        list.isError && jsx('div', { className: 'hermes-fb-error', role: 'status', children: t('backendDown') }),
        ...shown.map(e => {
          const cat = category(e)
          const iconPx = Math.max(24, Math.round(tilePx * 0.42))
          return jsx(ContextMenu, { children: [
          jsx(ContextMenuTrigger, { asChild: true, children: jsx('button', {
            className: 'hermes-fb-tile', 'data-on': selected === e.path, 'data-dir': e.is_dir,
            'data-drop': dropPath === e.path,
            draggable: true,
            onDragStart: ev => { try { ev.dataTransfer.setData('application/x-filebox-paths', JSON.stringify([e.path])) } catch {} ev.dataTransfer.effectAllowed = 'move'; setSelected(e.path) },
            onDragOver: e.is_dir ? (ev => { if (hasFbPaths(ev)) { ev.preventDefault(); ev.dataTransfer.dropEffect = 'move'; setDropPath(e.path) } }) : undefined,
            onDragLeave: e.is_dir ? (ev => { if (!ev.currentTarget.contains(ev.relatedTarget)) setDropPath(cur => cur === e.path ? null : cur) }) : undefined,
            onDrop: e.is_dir ? (ev => { ev.preventDefault(); setDropPath(null); try { dropMove(JSON.parse(ev.dataTransfer.getData('application/x-filebox-paths') || '[]'), e.path) } catch {} }) : undefined,
            onClick: () => setSelected(selected === e.path ? null : e.path),
            onContextMenu: () => setSelected(e.path),
            onDoubleClick: () => openEntry(e),
            onKeyDown: ev => { if (ev.key === 'Enter') openEntry(e) },
            'aria-label': e.name,
            children: [
              jsx(Thumb, { ctx, entry: e, px: iconPx, fallback: jsx('span', { className: 'hermes-fb-tileicon', children: jsx(Codicon, { name: iconFor(cat), size: iconPx }) }) }),
              jsx('span', { className: 'hermes-fb-tilename', children: e.name }),
              jsx('span', { className: 'hermes-fb-tilesub', children: e.is_dir ? '—' : fmtSize(e.size) }),
            ],
          }) }),
          jsx(ContextMenuContent, { children: [
            jsx(ContextMenuItem, { onSelect: () => quickOp('open', e), children: t('openFile') }),
            jsx(ContextMenuItem, { onSelect: () => quickOp('rename', e), children: t('rename') }),
            jsx(ContextMenuSeparator, {}),
            jsx(ContextMenuItem, { onSelect: () => quickOp('copy', e), children: t('copy') }),
            jsx(ContextMenuItem, { onSelect: () => quickOp('cut', e), children: t('cut') }),
            jsx(ContextMenuItem, { onSelect: () => quickOp('paste', e), children: t('paste') }),
            jsx(ContextMenuSeparator, {}),
            jsx(ContextMenuItem, { onSelect: () => quickOp('compress', e), children: t('compress') }),
            e.ext === '.zip' && jsx(ContextMenuItem, { onSelect: () => quickOp('extract', e), children: t('extract') }),
            jsx(ContextMenuItem, { onSelect: () => quickOp('delete', e), variant: 'destructive', children: t('delete') }),
            jsx(ContextMenuSeparator, {}),
            jsx(ContextMenuItem, { onSelect: () => quickOp('copypath', e), children: t('copyPath') }),
            jsx(ContextMenuItem, { onSelect: () => quickOp('reveal', e), children: t('reveal') }),
          ] }),
        ] }, e.path)
        }),
      ] }),
      total > shown.length && jsx('div', { className: 'hermes-fb-status', children: t('showingFirst', shown.length, total) }),
      jsxs('div', { className: 'hermes-fb-status', children: [
        jsx('span', { children: t('items', total) }),
        selEntry && jsx('span', { children: `${selEntry.name} · ${selEntry.is_dir ? '' : `${fmtSize(selEntry.size)} · `}${fmtDate(selEntry.mtime)}` }),
        jsx('span', { style: { flex: 1 } }),
        jsx('button', { className: 'hermes-fb-tbtn', style: { width: 'auto', fontSize: 11 }, onClick: () => setMkdirMode(!mkdirMode), children: `+ ${t('newFolder')}` }),
        jsx('button', { className: 'hermes-fb-tbtn', style: { width: 'auto', fontSize: 11 }, onClick: () => setShowHidden(!showHidden), children: showHidden ? '✓ hidden' : 'hidden' }),
      ] }),
      selEntry && jsxs('div', { className: 'hermes-fb-pvwrap', style: { height: previewH }, children: [
        jsx('div', { className: 'hermes-fb-griph', onMouseDown: startPreviewDrag }),
        jsx(Preview, { ctx, t, entry: selEntry, refetch: () => list.refetch(), select: setSelected }, selEntry.path),
      ] }),
    ] }),
  ] })
}

function tabName(cwd) {
  if (!cwd) return 'Home'
  const parts = String(cwd).split(/[/\\]+/).filter(Boolean)
  return parts.pop() || cwd
}

function Explorer({ ctx }) {
  const t = usePluginI18n(ID)
  const roots = useQuery({
    queryKey: [ID, 'roots'],
    queryFn: ({ signal }) => ctx.rest('/roots', { method: 'POST', timeoutMs: 15000, signal, body: {} }),
    staleTime: 600000,
    retry: false,
  })
  const home = roots.data?.home || null
  const [sort, setSortState] = useState(() => ctx.storage.get('sort', 'name'))
  const setSort = v => { setSortState(v); try { ctx.storage.set('sort', v) } catch {} }
  const [tilePx, setTilePxState] = useState(() => Number(ctx.storage.get('tilePx', 88)) || 88)
  const setTilePx = v => { const n = Number(v) || 88; setTilePxState(n); try { ctx.storage.set('tilePx', n) } catch {} }
  const [showHidden, setShowHiddenState] = useState(() => ctx.storage.get('showHidden', false) === true)
  const setShowHidden = v => { setShowHiddenState(v); try { ctx.storage.set('showHidden', v) } catch {} }
  const [sideWidth, setSideWidthState] = useState(() => Number(ctx.storage.get('sideWidth', 148)) || 148)
  const setSideWidth = v => { const n = Number(v) || 148; setSideWidthState(n); try { ctx.storage.set('sideWidth', n) } catch {} }
  const [sideCollapsed, setSideCollapsedState] = useState(() => ctx.storage.get('sideCollapsed', false) === true)
  const setSideCollapsed = v => { setSideCollapsedState(v); try { ctx.storage.set('sideCollapsed', v) } catch {} }
  const [previewH, setPreviewHState] = useState(() => Number(ctx.storage.get('previewH', 280)) || 280)
  const setPreviewH = v => { const n = Number(v) || 280; setPreviewHState(n); try { ctx.storage.set('previewH', n) } catch {} }
  const [tabs, setTabsState] = useState(() => {
    try {
      const saved = ctx.storage.get('tabs', null)
      if (Array.isArray(saved) && saved.length) {
        const clean = saved
          .filter(x => x && typeof x === 'object')
          .map((x, i) => ({ id: Number(x.id) || (Date.now() + i), cwd: typeof x.cwd === 'string' ? x.cwd : null }))
        if (clean.length) return clean.slice(0, 12)
      }
    } catch {}
    return [{ id: 1, cwd: null }]
  })
  const [activeId, setActiveIdState] = useState(() => ctx.storage.get('activeTab', null))
  const saveTabs = next => { setTabsState(next); try { ctx.storage.set('tabs', next) } catch {} }
  const setActive = id => { setActiveIdState(id); try { ctx.storage.set('activeTab', id) } catch {} }
  const active = tabs.find(x => x.id === activeId) || tabs[0]
  const addTab = () => {
    const id = Date.now()
    saveTabs([...tabs, { id, cwd: active?.cwd || home }].slice(-12))
    setActive(id)
  }
  const closeTab = id => {
    const i = tabs.findIndex(x => x.id === id)
    if (i < 0) return
    if (tabs.length <= 1) {
      const nid = Date.now()
      saveTabs([{ id: nid, cwd: home }])
      setActive(nid)
      return
    }
    const next = tabs.filter(x => x.id !== id)
    saveTabs(next)
    if (id === active.id) setActive(next[Math.min(i, next.length - 1)].id)
  }
  return jsxs('div', { className: 'hermes-fb', style: { flexDirection: 'column' }, children: [
    jsxs('div', { className: 'hermes-fb-tabs', children: [
      ...tabs.map(x => jsxs('button', {
        className: 'hermes-fb-tab', 'data-on': x.id === active.id, title: x.cwd || 'Home',
        onClick: () => setActive(x.id),
        children: [
          jsx('span', { children: tabName(x.cwd) }),
          tabs.length > 1 && jsx('span', { className: 'hermes-fb-tabx', title: 'Close tab', onClick: e => { e.stopPropagation(); closeTab(x.id) }, children: '×' }),
        ],
      }, x.id)),
      jsx('button', { className: 'hermes-fb-tbtn', title: 'New tab', onClick: addTab, children: '+' }),
      jsx('span', { style: { flex: 1 } }),
      jsx('button', { className: 'hermes-fb-tbtn', title: t('collapse'), onClick: () => { collapsed.set(true); syncPane() }, children: '−' }),
    ] }),
    ...tabs.map(x => jsx(TabPane, {
      ctx, tabId: x.id, initialCwd: x.cwd, sort, setSort, tilePx, setTilePx, showHidden, setShowHidden,
      sideWidth, setSideWidth, sideCollapsed, setSideCollapsed, previewH, setPreviewH,
      hidden: x.id !== active.id,
    }, x.id)),
  ] })
}

function FileChip({ ctx }) {
  const t = usePluginI18n(ID)
  const isCollapsed = useValue(collapsed)
  return jsx(Tip, { label: t(isCollapsed ? 'expand' : 'collapse'), children: jsx(Button, {
    variant: 'ghost', size: 'micro',
    'aria-label': t(isCollapsed ? 'expand' : 'collapse'),
    onClick: () => { collapsed.set(!collapsed.get()); syncPane() },
    children: jsx('span', { style: { fontSize: 11 }, children: 'FileBox' }),
  }) })
}

export default {
  id: ID,
  name: 'Filebox',
  description: 'Explorer-style file browser: quick access, breadcrumbs, grid, search, preview.',
  dispose() {
    try { if (paneDispose) paneDispose() } catch { /* noop */ }
    paneDispose = null
    paneCtx = null
    paneRegister = null
  },
  register(ctx) {
    ctx.i18n.register(LOCALES)
    const style = document.createElement('style')
    style.textContent = CSS
    document.head.append(style)
    paneCtx = ctx
    ctx.onDispose(() => {
      try { if (paneDispose) paneDispose() } catch { /* noop */ }
      paneDispose = null
      style.remove()
    })
    paneRegister = () => ctx.register({ id: 'filebox-pane', area: 'panes', title: 'FileBox', data: { placement: 'right', width: '440px' }, render: () => jsx(Explorer, { ctx }) })
    if (!collapsed.get()) paneDispose = paneRegister()
    ctx.register({ id: 'filebox-chip', area: STATUSBAR_AREAS.right, order: 14, render: () => jsx(FileChip, { ctx }) })
  },
}
