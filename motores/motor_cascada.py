"""
motor_cascada.py — Motor de búsqueda en cascada.
Intenta fuentes en orden hasta obtener suficientes URLs.
Nunca devuelve 0 resultados si el producto existe en alguna tienda española.

Orden de prioridad:
  1. DDGS (DuckDuckGo)   — más rápido, menos bloqueado
  2. Bing HTML            — alternativa sólida sin API key
  3. Fallback por categoría — URLs hardcodeadas, siempre funciona
"""
import time
from ddgs import DDGS
from motores.motor_bing import buscar_bing
from motores.motor_fallback import get_fallback_urls
from config import BASURA, MIN_URLS_ACEPTABLE, MAX_URLS_TOTAL
from db import PreciosDB

_DB = PreciosDB()  # singleton — evita crear una conexión nueva por cada URL filtrada
_DOMINIOS_BLOQUEADOS = frozenset([".ar", ".mx", ".cl", ".co", ".pe", ".ve", ".uy", ".br", ".us"])


def _filtrar(url: str, buscar_nuevo: bool = False) -> bool:
    """True si la URL es válida para analizar."""
    if not url or not url.startswith("http"):
        return False
    url_lower = url.lower()

    if any(b in url_lower for b in BASURA):
        return False

    if any(url_lower.endswith(d) or f"{d}/" in url_lower for d in _DOMINIOS_BLOQUEADOS):
        return False

    dominio = url.split("/")[2].replace("www.", "")
    if _DB.es_tienda_bloqueada(dominio, buscar_nuevo):
        print(f"    [!] Salto automático (Reputación): {dominio} es solo reacondicionados.")
        return False

    _PATRONES_LISTADO = [
        "/buscar", "/search", "/busqueda", "?q=", "/q", "search_query",
        "category", "categoria", "listado", "browse", "/c/",
        "/telefonia", "/moviles", "/smartphones", "/electronica", "/informatica",
    ]
    if any(p in url_lower for p in _PATRONES_LISTADO):
        if url_lower.endswith("/q") or "/search" in url_lower or "/buscar" in url_lower:
            return False

    # Rutas numéricas de categoría tipo /1959-telefonia — independiente de patrones
    import re as _re
    path = url_lower.split("?")[0]
    if _re.search(r'/\d{3,}-[a-z]', path):
        return False

    return True



def buscar_ddgs(queries: list[str], buscar_nuevo: bool = False) -> list[str]:
    urls: list[str] = []
    try:
        with DDGS() as ddgs:
            for q in queries:
                try:
                    # Forzamos región España y añadimos "España" a la query si no está
                    query_refinada = q if "españa" in q.lower() else f"{q} España"
                    for r in ddgs.text(query_refinada, region="es-es", max_results=8):
                        url = r.get("href") or r.get("url", "")

                        if _filtrar(url, buscar_nuevo) and url not in urls:
                            urls.append(url)
                    time.sleep(0.4)
                except Exception as e:
                    print(f"    [DDGS] Error: {e}")
    except Exception as e:
        print(f"    [DDGS] Fallo crítico: {e}")
    return urls



class MotorCascada:
    """
    Motor de búsqueda en cascada.
    Nunca falla: si DDGS y Bing fallan, usa URLs hardcodeadas por categoría.
    """
    nombre = "Cascada (DDGS → Bing → Fallback)"

    def buscar(self, queries: list[str], producto: str = "", buscar_nuevo: bool = False) -> list[str]:
        urls: list[str] = []
        fuentes_usadas: list[str] = []

        # ── FUENTE 1: DuckDuckGo ─────────────────────────────────────
        print("[*] Motor 1/3: DuckDuckGo...")
        ddgs_urls = buscar_ddgs(queries, buscar_nuevo)
        for u in ddgs_urls:
            if u not in urls:
                urls.append(u)
        if ddgs_urls:
            fuentes_usadas.append(f"DDGS({len(ddgs_urls)} URLs)")
            print(f"    [✓] DDGS: {len(ddgs_urls)} URLs")
        else:
            print("    [-] DDGS: sin resultados")

        # ── FUENTE 2: Bing (si DDGS insuficiente) ────────────────────
        if len(urls) < MIN_URLS_ACEPTABLE:
            print("[*] Motor 2/3: Bing HTML...")
            bing_urls = buscar_bing(queries)
            nuevas = 0
            for u in bing_urls:
                # Filtrar con contexto de reputación
                if _filtrar(u, buscar_nuevo) and u not in urls:
                    urls.append(u)
                    nuevas += 1
            if bing_urls:
                fuentes_usadas.append(f"Bing({nuevas} nuevas)")
                print(f"    [✓] Bing: {nuevas} nuevas URLs")
            else:
                print("    [-] Bing: sin resultados")
        else:
            print(f"    [skip] Bing omitido (ya tenemos {len(urls)} URLs)")


        # ── FUENTE 3: Fallback hardcodeado (siempre disponible) ───────
        if len(urls) < MIN_URLS_ACEPTABLE:
            print("[*] Motor 3/3: Fallback por categoría...")
            fallback_urls = get_fallback_urls(producto or (queries[0] if queries else ""), 6)
            nuevas = 0
            for u in fallback_urls:
                if u not in urls:
                    urls.append(u)
                    nuevas += 1
            fuentes_usadas.append(f"Fallback({nuevas} URLs)")
            print(f"    [✓] Fallback: {nuevas} URLs de tiendas especializadas")
        else:
            print(f"    [skip] Fallback omitido (ya tenemos {len(urls)} URLs)")

        resultado = urls[:MAX_URLS_TOTAL]
        print(f"\n[*] Total tras cascada: {len(resultado)} URLs | Fuentes: {' + '.join(fuentes_usadas)}")
        return resultado
