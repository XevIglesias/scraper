"""
api.py — Backend FastAPI del comparador de precios.
Endpoints:
  GET /buscar?q=iphone15&nuevo=true   → lanza búsqueda y devuelve resultados
  GET /historial?producto=iphone15    → historial de precios de un producto
  GET /alertas                        → lista alertas activas
  POST /alerta                        → crear alerta de precio
  GET /health                         → estado del servidor
"""
import asyncio
from fastapi import FastAPI, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from playwright.async_api import async_playwright

from db import PreciosDB
from motores.motor_cascada import MotorCascada

app = FastAPI(title="Comparador de Precios ES", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DB = PreciosDB()
_motor = MotorCascada()

# ── Búsqueda activa ──────────────────────────────────────────────────────────

async def _analizar_urls(urls: list[str], plan: dict) -> list[dict]:
    """Lanza Playwright headless y analiza cada URL."""
    from buscador_app import analizar_url
    resultados = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        tasks = [
            analizar_url(url, browser, plan, modo_barato=False, query_original=plan["producto_objetivo"],
                         callback=lambda r: resultados.append(r), auto_aprendizaje=False)
            for url in urls[:6]
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
        await browser.close()
    return resultados


@app.get("/buscar")
async def buscar(
    q: str = Query(..., description="Producto a buscar"),
    nuevo: bool = Query(True, description="Solo productos nuevos"),
):
    from buscador_app import planificar
    plan = await planificar(q, modo_barato=False)
    if not plan:
        return {"error": "No se pudo planificar la búsqueda", "resultados": []}

    urls = _motor.buscar(plan.get("queries_busqueda", [q]), producto=q, buscar_nuevo=nuevo)
    resultados = await _analizar_urls(urls, plan)

    # Guardar en historial
    for r in resultados:
        if r and r.get("precio_eur", 0) > 0:
            DB.guardar_precio(
                producto=r.get("nombre_detectado", q),
                tienda=r.get("url", "").split("/")[2].replace("www.", ""),
                precio=r.get("precio_eur", 0),
                envio=r.get("envio_eur", 0),
                url=r.get("url", ""),
            )

    return {
        "query": q,
        "total": len(resultados),
        "resultados": sorted(
            [r for r in resultados if r],
            key=lambda x: x.get("total_eur", 9999)
        )
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
<title>Comparador de Precios ES</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d0d0d; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; padding: 20px; }
  h1 { color: #4CAF50; margin-bottom: 20px; font-size: 1.5rem; }
  .search-box { display: flex; gap: 10px; margin-bottom: 30px; }
  input { flex: 1; padding: 12px; background: #1a1a1a; border: 1px solid #333; border-radius: 8px; color: #fff; font-size: 1rem; }
  button { padding: 12px 24px; background: #4CAF50; border: none; border-radius: 8px; color: #000; font-weight: bold; cursor: pointer; font-size: 1rem; }
  button:hover { background: #66BB6A; }
  .card { background: #161616; border: 1px solid #2a2a2a; border-radius: 10px; padding: 16px; margin-bottom: 12px; }
  .precio { font-size: 1.8rem; font-weight: bold; color: #4CAF50; }
  .tienda { color: #888; font-size: 0.9rem; margin-top: 4px; }
  .nombre { font-size: 1rem; margin-bottom: 8px; }
  .stock { font-size: 0.85rem; }
  a { color: #4CAF50; text-decoration: none; }
  #status { color: #888; margin-bottom: 16px; font-size: 0.9rem; }
  .spinner { display: none; color: #4CAF50; }
</style>
</head>
<body>
<h1>🔍 Comparador de Precios España</h1>
<div class="search-box">
  <input id="q" type="text" placeholder="Busca cualquier producto... (ej: iPhone 15 Pro Max 256GB nuevo)" />
  <button onclick="buscar()">Buscar</button>
</div>
<div id="status"></div>
<div id="resultados"></div>
<script>
async function buscar() {
  const q = document.getElementById('q').value.trim();
  if (!q) return;
  document.getElementById('status').textContent = 'Buscando... (puede tardar 30-60 segundos)';
  document.getElementById('resultados').innerHTML = '';
  try {
    const r = await fetch('/buscar?q=' + encodeURIComponent(q) + '&nuevo=true');
    const data = await r.json();
    document.getElementById('status').textContent = data.total + ' resultados para "' + q + '"';
    document.getElementById('resultados').innerHTML = data.resultados.map(res => `
      <div class="card">
        <div class="nombre">${res.nombre_detectado || q}</div>
        <div class="precio">${res.total_eur?.toFixed(2)}€</div>
        <div class="tienda">${res.url?.split('/')[2] || ''} · ${res.stock_label || ''}</div>
        <div style="margin-top:8px"><a href="${res.url}" target="_blank">Ver oferta →</a></div>
      </div>
    `).join('') || '<p style="color:#888">Sin resultados. Intenta con otro producto.</p>';
  } catch(e) {
    document.getElementById('status').textContent = 'Error: ' + e.message;
  }
}
document.getElementById('q').addEventListener('keydown', e => { if (e.key === 'Enter') buscar(); });
</script>
</body>
</html>
"""
