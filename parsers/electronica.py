"""
parsers/electronica.py — Parsers para tiendas de electrónica españolas.
Cubre: PcComponentes, MediaMarkt, Fnac, El Corte Inglés, Amazon.es.
"""
from parsers.base import TiendaParser, ResultadoParser



class AmazonParser(TiendaParser):

    dominio = "amazon.es"
    plataforma = "Custom"

    # Selectores de precio ordenados por fiabilidad (2025).
    # Si Amazon cambia el DOM, añadir el nuevo selector aquí sin tocar nada más.
    _PRICE_SELECTORS = [
        ".a-price.priceToPay .a-offscreen",  # precio "paga ahora" (más fiable)
        ".a-price.apexPriceToPay .a-offscreen",
        "#corePriceDisplay_desktop_feature_div .a-offscreen",
        ".a-price .a-offscreen",             # fallback genérico
        "#priceblock_ourprice",              # legacy
        "#priceblock_dealprice",
        ".a-price-whole",                    # solo entero (último recurso)
    ]

    async def parse(self, page) -> ResultadoParser:
        nombre = await self._texto(page,
            "#productTitle",
            "#title span",
            "h1.a-size-large",
            "h1",
        ) or "Amazon.es"

        # 1. JSON-LD primero (más resistente a cambios DOM)
        precio = await self._precio_json_ld(page)

        # 2. Selectores CSS con fallback en cascada
        if precio <= 0:
            for sel in self._PRICE_SELECTORS:
                txt = await self._texto(page, sel)
                if txt:
                    precio = self._parse_precio(txt)
                    if precio > 0:
                        break

        # 3. Detectar stock por botón de añadir al carrito
        en_stock = await self._existe(page, "#add-to-cart-button:not([disabled])")
        if precio > 0 and not en_stock:
            en_stock = True  # precio visible = producto disponible

        return ResultadoParser(
            nombre=nombre.strip(),
            precio=precio,
            envio=0.0,
            en_stock=en_stock,
            stock_label="En stock" if en_stock else "Agotado",
            fuente="Amazon.es (Parser)",
        )



class PcComponentesParser(TiendaParser):
    dominio = "pccomponentes.com"
    plataforma = "Custom"

    async def parse(self, page) -> ResultadoParser:
        nombre = await self._texto(page,
            "h1.product-title",
            "h1[itemprop='name']",
            "h1",
        ) or "PcComponentes"

        precio_txt = (
            await self._texto(page,
                "[data-price]",
                ".price-container .price",
                ".product-price",
                "#precio-main",
            ) or
            await self._attr(page, "[itemprop='price']", "content") or
            await self._attr(page, "[data-price]", "data-price")
        )
        precio = self._parse_precio(precio_txt)

        agotado = (
            await self._existe(page, ".out-of-stock") or
            await self._existe(page, "[class*='agotado']") or
            await self._existe(page, ".btn-add-cart[disabled]")
        )
        disponible = await self._existe(page, ".btn-add-cart:not([disabled])")

        if agotado:
            en_stock, stock_label = False, "❌ Agotado (PcComponentes)"
        elif disponible:
            en_stock, stock_label = True, "✅ En stock (PcComponentes)"
        else:
            en_stock, stock_label = True, "⚠️ Desconocido"

        return ResultadoParser(
            nombre=nombre, precio=precio, envio=0.0,
            en_stock=en_stock, stock_label=stock_label,
            fuente="PcComponentes parser",
        )


class MediaMarktParser(TiendaParser):
    dominio = "mediamarkt.es"
    plataforma = "Custom/React"

    async def parse(self, page) -> ResultadoParser:
        nombre = await self._texto(page,
            "h1[data-test='product-title']",
            "h1.product-name",
            "h1",
        ) or "MediaMarkt"

        precio_txt = (
            await self._texto(page,
                "[data-test='product-price'] span",
                ".price span",
                "[class*='Price'] span",
            ) or
            await self._attr(page, "[itemprop='price']", "content")
        )
        precio = self._parse_precio(precio_txt)

        agotado = await self._existe(page, "[data-test='out-of-stock']")
        disponible = await self._existe(page, "[data-test='add-to-cart']:not([disabled])")

        if agotado:
            en_stock, stock_label = False, "❌ Agotado (MediaMarkt)"
        elif disponible:
            en_stock, stock_label = True, "✅ En stock (MediaMarkt)"
        else:
            en_stock, stock_label = True, "⚠️ Desconocido"

        return ResultadoParser(
            nombre=nombre, precio=precio, envio=0.0,
            en_stock=en_stock, stock_label=stock_label,
            fuente="MediaMarkt parser",
        )


class FnacParser(TiendaParser):
    dominio = "fnac.es"
    plataforma = "Custom"

    async def parse(self, page) -> ResultadoParser:
        nombre = await self._texto(page,
            "h1.f-productHeader-Title",
            "h1.Article-title",
            "h1",
        ) or "Fnac"

        precio_txt = (
            await self._texto(page,
                ".userPrice .finalPrice",
                ".f-priceBox-price",
                ".Article-price",
            ) or
            await self._attr(page, "[itemprop='price']", "content")
        )
        precio = self._parse_precio(precio_txt)

        agotado = await self._existe(page, ".Article-stockLabel--outOfStock")
        disponible = await self._existe(page, ".f-buyBox-addToCart:not([disabled])")

        if agotado:
            en_stock, stock_label = False, "❌ Agotado (Fnac)"
        elif disponible:
            en_stock, stock_label = True, "✅ En stock (Fnac)"
        else:
            en_stock, stock_label = True, "⚠️ Desconocido"

        return ResultadoParser(
            nombre=nombre, precio=precio, envio=0.0,
            en_stock=en_stock, stock_label=stock_label,
            fuente="Fnac parser",
        )
