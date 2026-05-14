"""
parsers/farmacia.py — Parsers para farmacias online españolas.
Cubre: Promofarma, Dosfarma, Atida, Farmacias Direct, Tufarma.
La mayoría usa PrestaShop, que tiene selectores bastante estándar.
"""
from parsers.base import TiendaParser, ResultadoParser


class PrestaShopFarmaciaParser(TiendaParser):
    """
    Parser genérico para farmacias basadas en PrestaShop.
    Compatible con: Promofarma, Dosfarma, Atida, Farmaciasdirect, y similares.
    """
    plataforma = "PrestaShop"

    async def parse(self, page) -> ResultadoParser:
        # ── Nombre del producto ────────────────────────────────────────
        nombre = await self._texto(page,
            "h1.product-detail-name",
            "h1.page-title",
            "h1[itemprop='name']",
            "h1",
        ) or "Producto farmacia"

        # ── Precio ────────────────────────────────────────────────────
        # PrestaShop estándar: precio con IVA en span.current-price
        precio_txt = await self._texto(page,
            "span.current-price-value",
            "[itemprop='price']",
            "span.price",
            ".product-price",
            "#our_price_display",
        )
        # Fallback: atributo content del microdata
        if not precio_txt:
            precio_txt = await self._attr(page, "[itemprop='price']", "content")

        precio = self._parse_precio(precio_txt)

        # ── Envío ──────────────────────────────────────────────────────
        envio_txt = await self._texto(page,
            ".carrier-price",
            ".shipping-cost",
            "[class*='shipping'] .price",
        )
        envio = self._parse_precio(envio_txt)
        if envio < 0:
            envio = 0.0  # No detectado → asumimos gratis por defecto en farmacias

        # ── Stock ──────────────────────────────────────────────────────
        agotado = (
            await self._existe(page, ".product-unavailable") or
            await self._existe(page, ".out-of-stock") or
            await self._existe(page, "[class*='unavailable']") or
            await self._existe(page, ".product-last-items")  # Últimas unidades
        )
        disponible = (
            await self._existe(page, "#add-to-cart-or-refresh button:not([disabled])") or
            await self._existe(page, ".add-to-cart:not(.disabled)") or
            await self._existe(page, "[data-button-action='add-to-cart']")
        )

        if agotado:
            en_stock, stock_label = False, "❌ Agotado (PrestaShop)"
        elif disponible:
            en_stock, stock_label = True, "✅ En stock (PrestaShop)"
        else:
            en_stock, stock_label = True, "⚠️ Stock desconocido"

        return ResultadoParser(
            nombre=nombre,
            precio=precio,
            envio=envio,
            en_stock=en_stock,
            stock_label=stock_label,
            fuente="PrestaShop parser",
        )


class PromofarmaParser(PrestaShopFarmaciaParser):
    dominio = "promofarma.com"


class DosfarmaParser(PrestaShopFarmaciaParser):
    dominio = "dosfarma.com"


class AtidaParser(PrestaShopFarmaciaParser):
    dominio = "atida.com"


class FarmaciasDirectParser(PrestaShopFarmaciaParser):
    dominio = "farmaciasdirect.com"


class TufarmaParser(PrestaShopFarmaciaParser):
    dominio = "tufarma.com"
