"""
motor_bing.py — Scraper del buscador Bing como fuente alternativa de URLs.
Usa requests + BeautifulSoup. Sin API key. Sin coste.
"""
import time
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

BASURA = {
    "amazon", "aliexpress", "wallapop", "milanuncios", "idealo",
    "chollometro", "pinterest", "youtube", "facebook", "instagram",
    "twitter", "reddit", "wikipedia", "ebay", "bing.com", "microsoft.com"
}

# Selectores de resultados orgánicos de Bing (en orden de preferencia por versión del HTML)
_RESULT_SELECTORS = [
    ("li.b_algo h2 a", "b_algo clásico"),
    ("div.b_tpcn a.tilk", "Bing ads/shopping"),
    (".b_results .b_algo a[href^='http']", "b_results genérico"),
]


def _extraer_links_bing(soup: BeautifulSoup) -> list[str]:
    """Intenta múltiples selectores para extraer links de resultados de Bing."""
    for selector, _ in _RESULT_SELECTORS:
        links = [a.get("href", "") for a in soup.select(selector)]
        links = [l for l in links if l.startswith("http")]
        if links:
            return links
    return []


def buscar_bing(queries: list[str], max_por_query: int = 8) -> list[str]:
    """
    Busca en Bing HTML y extrae URLs reales de resultados orgánicos.
    No requiere API key. Limitado a mercado español (mkt=es-ES).
    """
    urls: list[str] = []
    session = requests.Session()
    session.headers.update(HEADERS)

    for query in queries:
        try:
            params = {
                "q": query,
                "mkt": "es-ES",
                "setlang": "es",
                "count": str(max_por_query),
                "first": "1",
            }
            resp = session.get("https://www.bing.com/search", params=params, timeout=10)
            if resp.status_code != 200:
                print(f"    [Bing] HTTP {resp.status_code} para '{query[:40]}'")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            if "captcha" in resp.text.lower():
                print("    [Bing] CAPTCHA detectado — Bing está bloqueando el scraper. Motor 2 desactivado.")
                return []

            links = _extraer_links_bing(soup)
            if not links:
                print(f"    [Bing] Sin resultados orgánicos para '{query[:40]}' (posible cambio de estructura HTML)")
                continue

            for href in links[:max_por_query]:
                if any(b in href.lower() for b in BASURA):
                    continue
                if href not in urls:
                    urls.append(href)

            time.sleep(1.0)

        except Exception as e:
            print(f"    [Bing] Error en query '{query[:40]}': {e}")
            continue

    return urls
