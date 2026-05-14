"""
api.py — Backend FastAPI del comparador de precios.
Endpoints:
  GET /buscar?q=iphone15&nuevo=true   → lanza búsqueda y devuelve resultados
  GET /historial?producto=iphone15    → historial de precios de un producto
  GET /alertas                        → lista alertas activas
  POST /alerta                        → crear alerta de precio
  GET /health                         → estado del servidor
  GET /worker/status                  → estado del worker 24/7
  GET /watchlist                      → productos monitorizados
  POST /watchlist                     → añadir producto a watchlist
  DELETE /watchlist/{id}              → desactivar producto de watchlist
"""
import asyncio
import logging
from fastapi import FastAPI, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from playwright.async_api import async_playwright

from db import PreciosDB
from motores.motor_cascada import MotorCascada
from worker import run_worker, get_estado

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Comparador de Precios ES", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    asyncio.create_task(run_worker())

DB = PreciosDB()
_motor = MotorCascada()


@app.get("/buscar")
async def buscar(
    q: str = Query(..., description="Producto a buscar"),
    nuevo: bool = Query(True, description="Solo productos nuevos"),
):
    from worker import _planificar, _buscar_producto
    resultados = await _buscar_producto(q)

    for r in resultados:
        if r.get("precio_eur", 0) > 0:
            DB.guardar_resultado({"nombre_detectado": r.get("nombre_detectado", q), **r})

    return {
        "query": q,
        "total": len(resultados),
        "resultados": sorted(resultados, key=lambda x: x.get("total_eur", 9999))
    }


# ── Historial ────────────────────────────────────────────────────────────────

@app.get("/historial")
async def historial(producto: str = Query(...)):
    datos = DB.obtener_historial_precios(producto, limite=50)
    return {"producto": producto, "historial": datos}


# ── Alertas ──────────────────────────────────────────────────────────────────

class AlertaIn(BaseModel):
    producto: str
    precio_objetivo: float

@app.post("/alerta")
async def crear_alerta(alerta: AlertaIn):
    DB.crear_alerta(alerta.producto, alerta.precio_objetivo)
    return {"ok": True, "mensaje": f"Alerta creada: {alerta.producto} < {alerta.precio_objetivo}€"}

@app.get("/alertas")
async def listar_alertas():
    import sqlite3
    with sqlite3.connect(str(DB.db_path)) as conn:
        rows = conn.execute(
            "SELECT producto, precio_objetivo, activa, created_at FROM alertas ORDER BY created_at DESC"
        ).fetchall()
    return {"alertas": [{"producto": r[0], "precio_objetivo": r[1], "activa": r[2], "fecha": r[3]} for r in rows]}


# ── Worker 24/7 + Watchlist ─────────────────────────────────────────────────

@app.get("/worker/status")
async def worker_status():
    from replicator.core.scraper_fitness import ScraperFitness
    fitness = ScraperFitness().compute().get("total", 55.0)
    return {**get_estado(), "fitness": round(fitness, 1)}


class WatchlistIn(BaseModel):
    producto: str
    categoria: str = "electronica"
    intervalo_min: int = 360

@app.get("/watchlist")
async def watchlist_listar():
    return {"watchlist": DB.watchlist_listar()}

@app.post("/watchlist")
async def watchlist_añadir(item: WatchlistIn):
    id_ = DB.watchlist_añadir(item.producto, item.categoria, item.intervalo_min)
    return {"ok": True, "id": id_, "producto": item.producto}

@app.delete("/watchlist/{id}")
async def watchlist_desactivar(id: int):
    DB.watchlist_desactivar(id)
    return {"ok": True}


# ── /evolve manual ──────────────────────────────────────────────────────────

_evolve_corriendo = False

async def _lanzar_evolve():
    global _evolve_corriendo
    if _evolve_corriendo:
        return
    _evolve_corriendo = True
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", "replicator/run_evolution.py",
            cwd="/opt/scraper",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await proc.wait()
    finally:
        _evolve_corriendo = False

@app.post("/evolve")
async def evolve(background_tasks: BackgroundTasks):
    if _evolve_corriendo:
        return {"ok": False, "mensaje": "Ya hay un ciclo /evolve en curso"}
    background_tasks.add_task(_lanzar_evolve)
    return {"ok": True, "mensaje": "Ciclo /evolve iniciado — tarda ~5 minutos"}


# ── Health + UI mínima ───────────────────────────────────────────────────────

@app.get("/health")
async def health():
    import subprocess
    ollama_ok = subprocess.run(["ollama", "list"], capture_output=True).returncode == 0
    return {"status": "ok", "ollama": ollama_ok}


@app.get("/", response_class=HTMLResponse)
async def ui():
    return """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PrecioES — Comparador de Precios España</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0a0a0a; color: #e0e0e0; font-family: 'Segoe UI', system-ui, sans-serif; }
  header { background: #111; border-bottom: 1px solid #222; padding: 14px 24px; display: flex; align-items: center; gap: 16px; }
  .logo { color: #4CAF50; font-size: 1.3rem; font-weight: 700; letter-spacing: -0.5px; }
  .search-wrap { flex: 1; display: flex; gap: 8px; max-width: 700px; }
  input { flex: 1; padding: 10px 14px; background: #1a1a1a; border: 1px solid #333; border-radius: 8px; color: #fff; font-size: 0.95rem; outline: none; }
  input:focus { border-color: #4CAF50; }
  .btn-buscar { padding: 10px 22px; background: #4CAF50; border: none; border-radius: 8px; color: #000; font-weight: 700; cursor: pointer; white-space: nowrap; }
  .btn-buscar:hover { background: #66BB6A; }
  .btn-evolve { background: #1a237e; color: #7986CB; padding: 8px 14px; font-size: 0.8rem; border-radius: 6px; border: 1px solid #283593; cursor: pointer; white-space: nowrap; }
  .btn-evolve:hover { background: #283593; color: #fff; }
  .btn-evolve:disabled { opacity: 0.4; cursor: default; }
  main { max-width: 900px; margin: 0 auto; padding: 20px 16px; }
  #worker-bar { background: #111; border: 1px solid #1e1e1e; border-radius: 8px; padding: 8px 14px; font-size: 0.8rem; color: #555; margin-bottom: 20px; }
  #status { color: #666; font-size: 0.9rem; margin-bottom: 16px; min-height: 20px; }
  .resultados-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
  .resultados-count { font-size: 0.85rem; color: #666; }
  .card { background: #131313; border: 1px solid #1f1f1f; border-radius: 12px; padding: 18px 20px; margin-bottom: 10px; display: flex; align-items: center; gap: 20px; transition: border-color 0.15s; }
  .card:hover { border-color: #333; }
  .card:first-child { border-color: #2e7d32; background: #0d1f0e; }
  .card-badge { font-size: 0.7rem; font-weight: 700; color: #4CAF50; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
  .card-nombre { font-size: 0.95rem; color: #ccc; margin-bottom: 6px; line-height: 1.3; }
  .card-tienda { font-size: 0.8rem; color: #555; }
  .card-stock { font-size: 0.78rem; color: #4CAF50; margin-top: 2px; }
  .card-precio-wrap { margin-left: auto; text-align: right; flex-shrink: 0; }
  .card-precio { font-size: 2rem; font-weight: 700; color: #fff; }
  .card-envio { font-size: 0.75rem; color: #555; margin-top: 2px; }
  .card-link { display: inline-block; margin-top: 8px; padding: 6px 14px; background: #1a2a1a; border: 1px solid #2e7d32; border-radius: 6px; color: #4CAF50; font-size: 0.8rem; text-decoration: none; }
  .card-link:hover { background: #2e7d32; color: #fff; }
  .spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid #333; border-top-color: #4CAF50; border-radius: 50%; animation: spin 0.7s linear infinite; vertical-align: middle; margin-right: 8px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .empty { text-align: center; padding: 60px 20px; color: #444; }
</style>
</head>
<body>
<header>
  <div class="logo">💹 PrecioES</div>
  <div class="search-wrap">
    <input id="q" type="text" placeholder="iPhone 15 Pro, MacBook Air M2, creatina..." />
    <button class="btn-buscar" onclick="buscar()">Buscar</button>
  </div>
  <button class="btn-evolve" id="btn-evolve" onclick="lanzarEvolve()">⚡ /evolve</button>
</header>
<main>
  <div id="worker-bar">Cargando estado del sistema...</div>
  <div id="status"></div>
  <div id="resultados"></div>
</main>
<script>
async function buscar() {
  const q = document.getElementById('q').value.trim();
  if (!q) return;
  document.getElementById('status').innerHTML = '<span class="spinner"></span>Buscando en tiendas españolas... (30-60s)';
  document.getElementById('resultados').innerHTML = '';
  try {
    const r = await fetch('/buscar?q=' + encodeURIComponent(q) + '&nuevo=true');
    const data = await r.json();
    const res = data.resultados || [];
    document.getElementById('status').textContent = res.length ? '' : 'Sin resultados para "' + q + '"';
    if (!res.length) { document.getElementById('resultados').innerHTML = '<div class="empty">No se encontraron precios.<br>Intenta con otro término.</div>'; return; }
    document.getElementById('status').textContent = res.length + ' tiendas encontradas para "' + q + '"';
    document.getElementById('resultados').innerHTML = res.map((r, i) => `
      <div class="card">
        <div style="flex:1">
          ${i===0 ? '<div class="card-badge">🏆 Mejor precio</div>' : ''}
          <div class="card-nombre">${r.nombre_detectado || q}</div>
          <div class="card-tienda">${r.url?.split('/')[2]?.replace('www.','') || ''}</div>
          <div class="card-stock">${r.stock_label || '✅ En stock'}</div>
          <a class="card-link" href="${r.url}" target="_blank">Ver oferta →</a>
        </div>
        <div class="card-precio-wrap">
          <div class="card-precio">${r.total_eur?.toFixed(2)}€</div>
          <div class="card-envio">${r.envio_eur > 0 ? 'Envío: ' + r.envio_eur.toFixed(2) + '€' : 'Envío incluido'}</div>
        </div>
      </div>
    `).join('');
  } catch(e) {
    document.getElementById('status').textContent = 'Error al buscar: ' + e.message;
  }
}
document.getElementById('q').addEventListener('keydown', e => { if (e.key === 'Enter') buscar(); });
async function cargarWorker() {
  try {
    const r = await fetch('/worker/status');
    const d = await r.json();
    document.getElementById('worker-bar').innerHTML =
      `⚙️ Worker 24/7: <span style="color:#4CAF50">${d.activo ? 'ACTIVO' : 'inactivo'}</span> &nbsp;|&nbsp; Fitness: <b style="color:#4CAF50">${d.fitness}/100</b> &nbsp;|&nbsp; Búsquedas hoy: ${d.busquedas_hoy} &nbsp;|&nbsp; Último: ${d.ultimo_producto || '—'}`;
  } catch(e) {}
}
cargarWorker();
setInterval(cargarWorker, 30000);
async function lanzarEvolve() {
  const btn = document.getElementById('btn-evolve');
  btn.disabled = true; btn.textContent = '⏳ Evolucionando...';
  try {
    const r = await fetch('/evolve', {method:'POST'});
    const d = await r.json();
    btn.textContent = d.ok ? '✅ Corriendo (~5min)' : '⚠️ Ya en curso';
    setTimeout(() => { btn.disabled=false; btn.textContent='⚡ /evolve'; }, 300000);
  } catch(e) { btn.disabled=false; btn.textContent='⚡ /evolve'; }
}
</script>
</body>
</html>
"""
