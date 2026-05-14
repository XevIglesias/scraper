"""
motor_fallback.py — URLs hardcodeadas por categoría de producto.
Se activa cuando todos los motores de búsqueda fallan.
Ollama detecta la categoría del producto y devuelve tiendas relevantes.
"""

# Estructura: categoria → lista de URLs base de tiendas relevantes
# Se construye la URL de búsqueda añadiendo el término de búsqueda como query
FALLBACK_POR_CATEGORIA: dict[str, list[str]] = {

    "farmacia": [
        "https://www.promofarma.com/es/search?q={}",
        "https://www.dosfarma.com/buscar?q={}",
        "https://www.atida.com/es-es/search?q={}",
        "https://www.farmaciasdirect.com/search?q={}",
        "https://www.tufarma.com/search?q={}",
        "https://www.farmacianuñez.com/search?q={}",
    ],

    "suplementos": [
        "https://www.nutritienda.com/es/search?text={}",
        "https://bulevip.com/es/search?q={}",
        "https://www.myprotein.com/es/search?term={}",
        "https://www.prozis.com/es/es/search?q={}",
        "https://www.hsnstore.com/search?q={}",
        "https://www.foodspring.es/search?query={}",
        "https://www.lifepro.es/search?q={}",
        "https://www.mmsupplementos.com/search?q={}",
    ],

    "electronica": [
        "https://www.pccomponentes.com/buscar/?query={}",
        "https://www.mediamarkt.es/es/search.html?query={}",
        "https://www.fnac.es/SearchResult/ResultList.aspx?Search={}",
        "https://www.elcorteingles.es/electrodomesticos/search?term={}",
        "https://www.coolmod.com/busqueda/?q={}",
        "https://www.ldlc.com/es-es/recherche/{}/",
    ],

    "moda": [
        "https://www.zalando.es/catalogo/?q={}",
        "https://www2.hm.com/es_es/buscar.html?q={}",
        "https://www.zara.com/es/es/search?searchTerm={}",
        "https://www.aboutyou.es/search?term={}",
    ],

    "deportes": [
        "https://www.decathlon.es/es/search?Ntt={}",
        "https://www.deporvillage.com/search?q={}",
        "https://www.tradeinn.com/es/search?q={}",
        "https://www.sport2000.es/search?q={}",
    ],

    "hogar": [
        "https://www.ikea.com/es/es/search/?q={}",
        "https://www.leroy-merlin.es/busqueda/q={}",
        "https://www.elcorteingles.es/hogar/search?term={}",
        "https://www.carrefour.es/s/?q={}",
    ],

    "mascotas": [
        "https://www.kiwoko.com/es/buscar?q={}",
        "https://www.zooplus.es/shop/search?query={}",
        "https://www.tractive.com/es/search?q={}",
        "https://www.tiendanimal.es/search?q={}",
    ],

    "general": [
        "https://www.carrefour.es/s/?q={}",
        "https://www.elcorteingles.es/search?term={}",
        "https://www.alcampo.es/compra-online/buscar?q={}",
        "https://www.fnac.es/SearchResult/ResultList.aspx?Search={}",
    ],
}

# Mapa de palabras clave → categoría
KEYWORDS_CATEGORIA: dict[str, list[str]] = {
    "farmacia": ["medicamento", "crema", "pomada", "apósito", "vendaje", "cicatriz",
                 "farmacia", "mepiform", "dermatix", "sutura", "antiséptico"],
    "suplementos": ["proteína", "whey", "creatina", "bcaa", "suplemento", "batido",
                    "scitec", "myprotein", "prozis", "gainers", "pre-entreno", "colágeno"],
    "electronica": ["portátil", "laptop", "smartphone", "iphone", "samsung", "monitor",
                    "gpu", "procesador", "ssd", "ram", "tablet", "auriculares", "teclado"],
    "moda": ["camiseta", "pantalón", "zapatillas", "zapatos", "vestido", "chaqueta",
             "abrigo", "bolso", "mochila", "ropa"],
    "deportes": ["bicicleta", "running", "fútbol", "tenis", "natación", "yoga",
                 "pesas", "gym", "esquí", "padel", "surf"],
    "hogar": ["sofá", "silla", "mesa", "armario", "cama", "lámpara", "alfombra",
              "cortina", "estantería", "colchón"],
    "mascotas": ["perro", "gato", "pienso", "arena", "correa", "veterinario",
                 "acuario", "hámster", "jaula"],
}


def detectar_categoria(producto: str) -> str:
    """Detecta la categoría del producto por palabras clave."""
    producto_lower = producto.lower()
    for categoria, keywords in KEYWORDS_CATEGORIA.items():
        if any(kw in producto_lower for kw in keywords):
            return categoria
    return "general"


def get_fallback_urls(producto: str, max_urls: int = 6) -> list[str]:
    """
    Devuelve URLs de fallback para un producto dado.
    Construye URLs de búsqueda en tiendas relevantes a la categoría.
    """
    from urllib.parse import quote_plus
    categoria = detectar_categoria(producto)
    print(f"    [Fallback] Categoría detectada: {categoria}")

    plantillas = FALLBACK_POR_CATEGORIA.get(categoria, FALLBACK_POR_CATEGORIA["general"])
    termino = quote_plus(producto)

    urls = []
    for plantilla in plantillas[:max_urls]:
        try:
            url = plantilla.format(termino)
            urls.append(url)
        except Exception:
            continue

    return urls
