"""
parsers/generalista.py — Parsers para grandes superficies y tiendas generalistas.
Cubre: Carrefour, El Corte Inglés, Alcampo.
"""
from parsers.base import TiendaParser, ResultadoParser


class CarrefourParser(TiendaParser):
    dominio = "carrefour.es"
    plataforma = "Custom"

    async def parse(self, page) -> ResultadoParser:
        nombre = await self._texto(page,
            "h1.product-header__title",
            "h1.pdp-title",
            "h1",
        ) or "Carrefour"

        # Carrefour tiene el precio en un formato complejo a veces
        precio_txt = await self._texto(page,
            ".buybox__price",
            ".product-header__price",
            "span.price",
            "[itemprop='price']",
        )
        if not precio_txt:
            precio_txt = await self._attr(page, "[itemprop='price']", "content")
        
        precio = self._parse_precio(precio_txt)

        # Envío en Carrefour suele variar por CP, intentamos capturar base
        envio_txt = await self._texto(page, ".shipping-cost", ".delivery-price")
        envio = self._parse_precio(envio_txt)
        if envio < 0: envio = 0.0

        agotado = await self._existe(page, ".product-unavailable")
        disponible = await self._existe(page, ".add-to-cart-button:not([disabled])")

        if agotado:
            en_stock, stock_label = False, "❌ Agotado (Carrefour)"
        elif disponible:
            en_stock, stock_label = True, "✅ En stock (Carrefour)"
        else:
            en_stock, stock_label = True, "⚠️ Desconocido"

        return ResultadoParser(
            nombre=nombre, precio=precio, envio=envio,
            en_stock=en_stock, stock_label=stock_label,
            fuente="Carrefour parser",
        )


class ElCorteInglesParser(TiendaParser):
    dominio = "elcorteingles.es"
    plataforma = "Custom"

    async def parse(self, page) -> ResultadoParser:
        nombre = await self._texto(page,
            "h1.title",
            "h1",
        ) or "El Corte Inglés"

        precio_txt = await self._texto(page,
            "span.price.sale",
            "span.price",
            ".product-price",
        )
        if not precio_txt:
            precio_txt = await self._attr(page, "[itemprop='price']", "content")
        
        precio = self._parse_precio(precio_txt)

        envio = 0.0 # ECI suele ocultar envío hasta el carrito o por compra mínima

        agotado = await self._existe(page, ".pdp-unavailable")
        disponible = await self._existe(page, "#add-to-cart:not([disabled])")

        if agotado:
            en_stock, stock_label = False, "❌ Agotado (ECI)"
        elif disponible:
            en_stock, stock_label = True, "✅ En stock (ECI)"
        else:
            en_stock, stock_label = True, "⚠️ Desconocido"

        return ResultadoParser(
            nombre=nombre, precio=precio, envio=envio,
            en_stock=en_stock, stock_label=stock_label,
            fuente="ECI parser",
        )
