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
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

BASURA = {
    "amazon", "aliexpress", "wallapop", "milanuncios", "idealo",
    "chollometro", "pinterest", "youtube", "facebook", "instagram",
    "twitter", "reddit", "wikipedia", "ebay", "bing.com", "microsoft.com"
}


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
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # Resultados orgánicos de Bing: <li class="b_algo"> → <h2> → <a href>
            for li in soup.select("li.b_algo"):
                a = li.select_one("h2 a")
                if not a:
                    continue
                href = a.get("href", "")
                if not href.startswith("http"):
                    continue
                if any(b in href.lower() for b in BASURA):
                    continue
                if href not in urls:
                    urls.append(href)

            time.sleep(1.0)  # Pausa educada entre queries

        except Exception as e:
            print(f"    [Bing] Error en query '{query[:40]}': {e}")
            continue

    return urls
