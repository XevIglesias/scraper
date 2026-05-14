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

from urllib.parse import urlparse
from ollama import AsyncClient
from db import PreciosDB
from motores.motor_cascada import MotorCascada
from parsers.electronica import AmazonParser, PcComponentesParser, MediaMarktParser, FnacParser
from parsers.generalista import CarrefourParser, ElCorteInglesParser

_PARSERS = {
    "amazon.es": AmazonParser(),
    "pccomponentes.com": PcComponentesParser(),
    "mediamarkt.es": MediaMarktParser(),
    "fnac.es": FnacParser(),
    "carrefour.es": CarrefourParser(),
    "elcorteingles.es": ElCorteInglesParser(),
}

def _dominio(url: str) -> str:
    h = urlparse(url).hostname or ""
    return h[4:] if h.startswith("www.") else h

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


_SELECTORES_PRECIO = [
    # Amazon
    ".a-price.priceToPay .a-offscreen", ".a-price .a-offscreen", "#priceblock_ourprice",
    # Genéricos schema
    "[itemprop='price']", "[data-price]", "[data-product-price]",
    # WooCommerce / PrestaShop / Shopify
    ".price ins .amount", ".price .amount", ".woocommerce-Price-amount",
    ".product-price", ".current-price", ".price-current", ".js-price",
    ".product__price", ".ProductMeta__Price", ".price__current",
    # Tiendas españolas
    ".pvp", ".precio", ".importe", ".precio-actual", ".price-box .price",
    ".pdp-price", ".buybox-price", ".js-product-price",
    # Fallback genérico
    ".price", ".our-price", "span.price", "#price",
]


def _parsear_precio(texto: str) -> float | None:
    txt = texto.strip().replace("\xa0", "").replace(" ", "")
    # Formato europeo: 1.299,99 → 1299.99
    m = re.search(r"(\d{1,3}(?:\.\d{3})*),(\d{2})", txt)
    if m:
        return float(m.group(0).replace(".", "").replace(",", "."))
    # Formato con punto decimal: 1299.99
    m = re.search(r"\d+\.\d{2}", txt)
    if m:
        return float(m.group(0))
    # Solo dígitos con coma
    m = re.search(r"\d+,\d+", txt)
    if m:
        return float(m.group(0).replace(",", "."))
    return None


async def _extraer_precio_url(url: str, producto: str) -> dict | None:
    """Extrae precio usando parser especializado si existe, o genérico como fallback."""
    try:
        from playwright.async_api import async_playwright
        dom = _dominio(url)
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = await browser.new_page()
            await page.set_extra_http_headers({"Accept-Language": "es-ES,es;q=0.9"})
            await page.goto(url, timeout=20000, wait_until="domcontentloaded")

            # Parser especializado si existe para este dominio
            if dom in _PARSERS:
                try:
                    r = await _PARSERS[dom].parse(page)
                    await browser.close()
                    if r.precio > 0:
                        return {
                            "url": url,
                            "nombre_detectado": r.nombre or producto,
                            "precio_eur": r.precio,
                            "envio_eur": r.envio if r.envio >= 0 else 0.0,
                            "total_eur": r.precio + (r.envio if r.envio > 0 else 0.0),
                            "stock_label": "✅ " + r.stock_label,
                        }
                    await browser.close()
                    return None
                except Exception as e:
                    log.debug(f"[WORKER] Parser {dom} falló: {e}")

            precio = None
            nombre = None

            # 1. JSON-LD (más fiable, resiste cambios de DOM)
            lds = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
                    .map(s => s.textContent);
            }""")
            for ld_text in lds:
                try:
                    data = json.loads(ld_text)
                    if isinstance(data, list):
                        data = data[0]
                    offers = data.get("offers", data)
                    if isinstance(offers, list):
                        offers = offers[0]
                    p = offers.get("price") or offers.get("lowPrice")
                    if p:
                        precio = float(str(p).replace(",", "."))
                        nombre = data.get("name", producto)
                        break
                except Exception:
                    continue

            # 2. Atributo content en meta / span
            if not precio:
                p = await page.evaluate("""() => {
                    const el = document.querySelector('[itemprop="price"]');
                    return el ? (el.getAttribute('content') || el.textContent) : null;
                }""")
                if p:
                    precio = _parsear_precio(str(p))

            # 3. Selectores CSS en cascada
            if not precio:
                for sel in _SELECTORES_PRECIO:
                    try:
                        el = await page.query_selector(sel)
                        if el:
                            txt = await el.inner_text()
                            precio = _parsear_precio(txt)
                            if precio:
                                break
                    except Exception:
                        continue

            await browser.close()

            if precio and 1.0 < precio < 100000:
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

    tasks = [_extraer_precio_url(url, producto) for url in urls[:12]]
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
