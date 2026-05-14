"""
parsers/base.py — Clase base abstracta para parsers de tiendas.

Cada parser implementa extracción de precio, stock, envío y nombre
usando selectores CSS exactos del DOM de esa tienda.
Esto elimina la llamada a Ollama para tiendas conocidas.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ResultadoParser:
    nombre: str
    precio: float        # -1 si no detectado
    envio: float         # 0 = gratis, -1 = no detectado
    en_stock: bool
    stock_label: str
    fuente: str          # qué selector encontró el precio


class TiendaParser(ABC):
    """
    Clase base para parsers específicos de tienda.
    Todas las subclases deben implementar parse().
    """
    dominio: str         # Ej: "promofarma.com"
    plataforma: str      # Ej: "PrestaShop", "WooCommerce", "Custom"

    @abstractmethod
    async def parse(self, page) -> ResultadoParser:
        """Extrae precio, stock, envío y nombre del producto de la página."""
        ...

    # ── Helpers compartidos ────────────────────────────────────────────

    async def _texto(self, page, *selectores: str) -> str | None:
        """Prueba selectores en orden y devuelve el primer texto encontrado."""
        for sel in selectores:
            try:
                # Soporte para lista de selectores CSS alternativos separados por |
                partes = [s.strip() for s in sel.split("|")]
                for parte in partes:
                    el = await page.query_selector(parte)
                    if el:
                        t = await el.inner_text()
                        if t and t.strip():
                            return t.strip()
            except Exception:
                continue
        return None

    async def _precio_json_ld(self, page) -> float:
        """Extrae precio desde JSON-LD (schema.org) — el mas fiable y resistente a cambios de DOM."""
        try:
            precio = await page.evaluate("""() => {
                for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
                    try {
                        const d = JSON.parse(s.textContent);
                        const offers = d.offers || (d['@graph'] || []).map(x => x.offers).find(Boolean);
                        if (offers) {
                            const p = offers.price || offers.lowPrice;
                            if (p) return parseFloat(String(p).replace(',', '.'));
                        }
                    } catch {}
                }
                return null;
            }""")
            if precio and 0.5 < float(precio) < 100000:
                return float(precio)
        except Exception:
            pass
        return -1.0

    async def _attr(self, page, selector: str, attr: str) -> str | None:
        """Devuelve el atributo de un elemento CSS."""
        try:
            el = await page.query_selector(selector)
            if el:
                return await el.get_attribute(attr)
        except Exception:
            pass
        return None

    async def _existe(self, page, selector: str) -> bool:
        """True si el selector existe en la página."""
        try:
            return await page.query_selector(selector) is not None
        except Exception:
            return False

    def _parse_precio(self, texto: str | None) -> float:
        """Convierte texto de precio a float. Devuelve -1 si falla."""
        if not texto:
            return -1.0
        import re
        limpio = re.sub(r'[^\d,.]', '', texto.strip())
        # Normalizar separadores europeos: 45.990,99 → 45990.99
        if ',' in limpio and '.' in limpio:
            limpio = limpio.replace('.', '').replace(',', '.')
        elif ',' in limpio:
            limpio = limpio.replace(',', '.')
        try:
            p = float(limpio)
            return p if 0.5 < p < 100_000 else -1.0
        except (ValueError, TypeError):
            return -1.0
