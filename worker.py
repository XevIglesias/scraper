"""
worker.py — Búsqueda autónoma 24/7.
Recorre la watchlist y busca cada producto cuando toca (según su intervalo_min).
Los errores se registran en memoria_errores para que /evolve los detecte y corrija los parsers.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from db import PreciosDB
from motores.motor_cascada import MotorCascada

log = logging.getLogger("worker")

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


async def _buscar_producto(producto: str, nuevo: bool = True) -> list[dict]:
    from playwright.async_api import async_playwright
    from buscador_app import planificar, analizar_url

    plan = await planificar(producto, modo_barato=False)
    if not plan:
        raise RuntimeError("planificar() devolvió None")

    motor = MotorCascada()
    urls = motor.buscar(plan.get("queries_busqueda", [producto]), producto=producto, buscar_nuevo=nuevo)

    resultados = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        tasks = [
            analizar_url(
                url, browser, plan,
                modo_barato=False,
                query_original=producto,
                callback=lambda r: resultados.append(r) if r else None,
                auto_aprendizaje=True,
            )
            for url in urls[:5]
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
        await browser.close()
    return [r for r in resultados if r]


def _seed_watchlist(db: PreciosDB):
    existentes = {p["producto"] for p in db.watchlist_listar()}
    for producto, categoria in PRODUCTOS_SEED:
        if producto not in existentes:
            db.watchlist_añadir(producto, categoria)
            log.info(f"[WORKER] Seed añadido: {producto}")


async def run_worker():
    db = PreciosDB()
    _seed_watchlist(db)
    _estado["activo"] = True
    _estado["inicio"] = datetime.now().isoformat()
    log.info("[WORKER] Arrancado — monitorizando watchlist 24/7")

    while True:
        productos = db.watchlist_listar()
        for p in productos:
            if not _toca_buscar(p):
                continue

            _estado["ultimo_producto"] = p["producto"]
            log.info(f"[WORKER] Buscando: {p['producto']}")

            try:
                resultados = await _buscar_producto(p["producto"])
                db.watchlist_marcar_busqueda(p["id"])
                _estado["busquedas_hoy"] += 1

                for r in resultados:
                    if r.get("precio_eur", 0) > 0:
                        db.guardar_resultado({
                            "nombre_detectado": r.get("nombre_detectado", p["producto"]),
                            "url": r.get("url", ""),
                            "precio_eur": r.get("precio_eur", 0),
                            "envio_eur": r.get("envio_eur", 0),
                            "total_eur": r.get("total_eur", 0),
                            "stock_label": r.get("stock_label", ""),
                        })

                log.info(f"[WORKER] {p['producto']}: {len(resultados)} resultados guardados")

            except Exception as e:
                db.watchlist_marcar_error(p["id"])
                db.registrar_error_aprendizaje(
                    dominio=p["categoria"],
                    url=p["producto"],
                    tipo_error=type(e).__name__,
                    leccion=str(e)[:400],
                )
                log.warning(f"[WORKER] Error en '{p['producto']}': {e}")

        await asyncio.sleep(60)


def get_estado() -> dict:
    return dict(_estado)
