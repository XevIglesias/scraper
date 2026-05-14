"""
parsers/suplementos.py — Parsers para tiendas de nutrición deportiva españolas.
Cubre: Nutritienda, Bulevip, MyProtein, HSN Store, Prozis, Lifepro, Foodspring.
"""
from parsers.base import TiendaParser, ResultadoParser


class WooCommerceSupParser(TiendaParser):
    """
    Parser genérico para tiendas de suplementos basadas en WooCommerce.
    Compatible con: Nutritienda, Bulevip, HSN, Lifepro y similares.
    """
    plataforma = "WooCommerce"

    async def parse(self, page) -> ResultadoParser:
        nombre = await self._texto(page,
            ".product_title",
            "h1.entry-title",
            "h1[itemprop='name']",
            "h1",
        ) or "Suplemento"

        precio_txt = await self._texto(page,
            ".woocommerce-Price-amount.amount bdi",
            "p.price ins .woocommerce-Price-amount",
            "p.price .woocommerce-Price-amount",
            "[itemprop='price']",
        )
        if not precio_txt:
            precio_txt = await self._attr(page, "[itemprop='price']", "content")
        precio = self._parse_precio(precio_txt)

        # Envío en WooCommerce suele aparecer en tabla de checkout, no en producto
        envio = 0.0

        agotado = (
            await self._existe(page, ".out-of-stock") or
            await self._existe(page, ".stock.out-of-stock") or
            await self._existe(page, "p.stock.out-of-stock")
        )
        disponible = (
            await self._existe(page, ".single_add_to_cart_button:not(.disabled)") or
            await self._existe(page, "button.add_to_cart_button") or
            await self._existe(page, ".in-stock")
        )

        if agotado:
            en_stock, stock_label = False, "❌ Agotado (WooCommerce)"
        elif disponible:
            en_stock, stock_label = True, "✅ En stock (WooCommerce)"
        else:
            en_stock, stock_label = True, "⚠️ Stock desconocido"

        return ResultadoParser(
            nombre=nombre, precio=precio, envio=envio,
            en_stock=en_stock, stock_label=stock_label,
            fuente="WooCommerce parser",
        )


class NutritiendaParser(WooCommerceSupParser):
    dominio = "nutritienda.com"


class BulevipParser(WooCommerceSupParser):
    dominio = "bulevip.com"


class HSNParser(WooCommerceSupParser):
    dominio = "hsnstore.com"


class LifeproParser(WooCommerceSupParser):
    dominio = "lifepro.es"


class MyProteinParser(TiendaParser):
    """MyProtein tiene frontend custom (React)."""
    dominio = "myprotein.com"
    plataforma = "Custom/React"

    async def parse(self, page) -> ResultadoParser:
        nombre = await self._texto(page,
            "h1.productName_title",
            "h1[data-product-name]",
            "h1",
        ) or "MyProtein"

        precio_txt = await self._texto(page,
            "p.productPrice_price",
            "[data-product-price]",
            ".productPrice",
        )
        if not precio_txt:
            precio_txt = await self._attr(page, "[itemprop='price']", "content")
        precio = self._parse_precio(precio_txt)

        agotado = await self._existe(page, ".athenaProductVariations_soldOut")
        disponible = await self._existe(page, "button[data-product-id]")

        if agotado:
            en_stock, stock_label = False, "❌ Agotado (MyProtein)"
        elif disponible:
            en_stock, stock_label = True, "✅ En stock (MyProtein)"
        else:
            en_stock, stock_label = True, "⚠️ Stock desconocido"

        return ResultadoParser(
            nombre=nombre, precio=precio, envio=0.0,
            en_stock=en_stock, stock_label=stock_label,
            fuente="MyProtein custom parser",
        )


class ProzisParser(TiendaParser):
    dominio = "prozis.com"
    plataforma = "Custom"

    async def parse(self, page) -> ResultadoParser:
        nombre = await self._texto(page, "h1.product-name", "h1") or "Prozis"
        precio_txt = (
            await self._texto(page, ".product-price .price", ".price-value") or
            await self._attr(page, "[itemprop='price']", "content")
        )
        precio = self._parse_precio(precio_txt)
        agotado = await self._existe(page, ".out-of-stock-label")
        disponible = await self._existe(page, "button.add-to-cart:not([disabled])")
        if agotado:
            en_stock, stock_label = False, "❌ Agotado (Prozis)"
        elif disponible:
            en_stock, stock_label = True, "✅ En stock (Prozis)"
        else:
            en_stock, stock_label = True, "⚠️ Desconocido"
        return ResultadoParser(
            nombre=nombre, precio=precio, envio=0.0,
            en_stock=en_stock, stock_label=stock_label,
            fuente="Prozis parser",
        )
