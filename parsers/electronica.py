"""
parsers/electronica.py — Parsers para tiendas de electrónica españolas.
Cubre: PcComponentes, MediaMarkt, Fnac, El Corte Inglés, Amazon.es.
"""
from parsers.base import TiendaParser, ResultadoParser



class AmazonParser(TiendaParser):

    dominio = "amazon.es"
    plataforma = "Custom"

    async def parse(self, page) -> ResultadoParser:
        # Amazon tiene selectores muy variados según la categoría
        nombre = await self._texto(page,
            "#productTitle",
            "h1",
            ".qa-title-text"
        ) or "Amazon.es"

        # Amazon usa .a-price-whole y .a-price-fraction para el precio principal
        # Pero a veces está en un input o en un meta
        precio_entero = await self._texto(page, ".a-price-whole")
        precio_decimal = await self._texto(page, ".a-price-fraction")
        
        if precio_entero:
            # Limpiamos el punto de miles si existe
            precio_txt = precio_entero.replace(".", "").replace(",", ".")
            if precio_decimal:
                precio_txt += f".{precio_decimal}"
            precio = self._parse_precio(precio_txt)
        else:
            # Fallback a selectores de oferta o secundarios
            precio_txt = await self._texto(page, ".apexPriceToPay", ".priceToPay", "#priceblock_ourprice")
            precio = self._parse_precio(precio_txt)

        return ResultadoParser(
            nombre=nombre.strip(),
            precio=precio,
            envio=0.0, # Amazon suele ser Prime/Gratis o variable
            en_stock=precio > 0,
            stock_label="✅ En stock" if precio > 0 else "❌ Agotado",
            fuente="Amazon.es (Parser)"
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
