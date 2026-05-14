"""
worker.py — Búsqueda autónoma 24/7.
No importa buscador_app.py (tiene tkinter/GUI). Usa Ollama y MotorCascada directamente.
Los errores se registran en memoria_errores para que /evolve los detecte y corrija parsers.
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta

from ollama import AsyncClient
from db import PreciosDB
from motores.motor_cascada import MotorCascada

log = logging.getLogger("worker")

OLLAMA_HOST = "http://localhost:11434"
MODELO = "llama3"

PRODUCTOS_SEED = [
    ("iPhone 15 Pro", "electronica"),
    ("Samsung Galaxy S24", "electronica"),
    ("MacBook Air M2", "electronica"),
    ("AirPods Pro 2", "electronica"),
    ("Xiaomi 14", "electronica"),
    ("Vitamina C 1000mg", "suplementos"),
    ("Creatina monohidrato", "suplementos"),
]

_estado = {
    "activo": False,
    "ultimo_producto": None,
    "busquedas_hoy": 0,
    "inicio": None,
}


def _toca_buscar(p: dict) -> bool:
    if not p["ultima_busqueda"]:
        return True
    try:
        ultima = datetime.fromisoformat(p["ultima_busqueda"])
    except (ValueError, TypeError):
        return True
    return datetime.now() >= ultima + timedelta(minutes=p["intervalo_min"])


def _limpiar_json(texto: str) -> str:
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    return m.group(0) if m else texto


async def _planificar(producto: str) -> dict:
    prompt = f"""Eres experto en e-commerce España. Genera queries de búsqueda para encontrar el precio de "{producto}" nuevo.
Responde SOLO con este JSON:
{{"producto_objetivo": "{producto}", "queries_busqueda": ["comprar {producto}", "precio {producto} España", "{producto} oferta", "{producto} tienda online"]}}"""
    try:
        r = await asyncio.wait_for(
            AsyncClient(host=OLLAMA_HOST).chat(
                model=MODELO,
                messages=[{"role": "user", "content": prompt}],
                format="json"
            ),
            timeout=30.0
        )
        return json.loads(_limpiar_json(r["message"]["content"]))
    except Exception:
        return {
            "producto_objetivo": producto,
            "queries_busqueda": [f"comprar {producto}", f"precio {producto} España nuevo"]
        }


async def _extraer_precio_url(url: str, producto: str) -> dict | None:
    """Extrae precio de una URL usando Playwright + selectores estándar."""
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, timeout=15000, wait_until="domcontentloaded")

            # JSON-LD primero
            ld = await page.evaluate("""() => {
                const s = document.querySelector('script[type="application/ld+json"]');
                return s ? s.textContent : null;
            }""")
            precio = None
            nombre = None
            if ld:
                try:
                    data = json.loads(ld)
                    if isinstance(data, list):
                        data = data[0]
                    offers = data.get("offers", data)
                    if isinstance(offers, list):
                        offers = offers[0]
                    precio = float(str(offers.get("price", "0")).replace(",", "."))
                    nombre = data.get("name", producto)
                except Exception:
                    pass

            # Selectores CSS fallback
            if not precio:
                for sel in [".a-price .a-offscreen", ".price", "[itemprop='price']",
                             ".product-price", ".pvp", ".our-price", "#priceblock_ourprice"]:
                    try:
                        el = await page.query_selector(sel)
                        if el:
                            txt = await el.inner_text()
                            m = re.search(r"[\d]+[.,][\d]+", txt.replace(".", "").replace(",", "."))
                            if m:
                                precio = float(m.group(0))
                                break
                    except Exception:
                        continue

            await browser.close()

            if precio and precio > 0.5:
                return {
                    "url": url,
                    "nombre_detectado": nombre or producto,
                    "precio_eur": precio,
                    "envio_eur": 0.0,
                    "total_eur": precio,
                    "stock_label": "✅ En stock",
                }
    except Exception as e:
        log.debug(f"[WORKER] Error extrayendo {url}: {e}")
    return None


async def _buscar_producto(producto: str) -> list[dict]:
    plan = await _planificar(producto)
    motor = MotorCascada()
    urls = motor.buscar(plan.get("queries_busqueda", [producto]), producto=producto, buscar_nuevo=True)

    tasks = [_extraer_precio_url(url, producto) for url in urls[:5]]
    resultados = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in resultados if r and not isinstance(r, Exception)]


def _seed_watchlist(db: PreciosDB):
    existentes = {p["producto"] for p in db.watchlist_listar()}
    for producto, categoria in PRODUCTOS_SEED:
        if producto not in existentes:
            db.watchlist_añadir(producto, categoria)
            log.info(f"[WORKER] Seed: {producto}")


async def run_worker():
    db = PreciosDB()
    _seed_watchlist(db)
    _estado["activo"] = True
    _estado["inicio"] = datetime.now().isoformat()
    log.info("[WORKER] Arrancado — monitorizando watchlist 24/7")

    while True:
        for p in db.watchlist_listar():
            if not _toca_buscar(p):
                continue

            _estado["ultimo_producto"] = p["producto"]
            log.info(f"[WORKER] Buscando: {p['producto']}")

            try:
                resultados = await _buscar_producto(p["producto"])
                db.watchlist_marcar_busqueda(p["id"])
                _estado["busquedas_hoy"] += 1

                for r in resultados:
                    db.guardar_resultado({"nombre_detectado": r.get("nombre_detectado", p["producto"]), **r})

                log.info(f"[WORKER] {p['producto']}: {len(resultados)} resultados")

            except Exception as e:
                db.watchlist_marcar_error(p["id"])
                db.registrar_error_aprendizaje(
                    dominio=p["categoria"],
                    url=p["producto"],
                    tipo_error=type(e).__name__,
                    leccion=str(e)[:400],
                )
                log.warning(f"[WORKER] Error '{p['producto']}': {e}")

        await asyncio.sleep(60)


def get_estado() -> dict:
    return dict(_estado)
