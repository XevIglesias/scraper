# config.py - Configuración global del scraper

# URLs basura que nunca nos interesan (Blogs, noticias, redes, comparadores genéricos, etc.)
BASURA = {
    "aliexpress", "wallapop", "milanuncios", "idealo",
    "chollometro", "pinterest", "youtube", "facebook", "instagram", 
    "twitter", "reddit", "wikipedia", "ebay", "mercadolibre", "kabum",

    "zoom.com.br", "buscape", "magazineluiza", "americanas",
    "tiktok", "linkedin", "google", "bing", "yahoo", "duckduckgo",
    "temu", "shein", "wish", "alibaba", "shopee",
    "xataka", "applesfera", "elandroidelibre", "proandroid", "computerhoy",
    "elconfidencial", "elpais", "elmundo", "abc.es", "lavanguardia",
    "genbeta", "microsiervos", "gizmodo", "engadget", "gsmarena",
    "motorpasion", "vandal", "hobbyconsolas", "muycomputer", "bandaancha",
    "adslzone", "softzone", "hardzone", "topesdegama", "andro4all", 
    "comunidad.orange", "comunidad.movistar", "foro.vodafone"
}

# Rango de precios lógicos
PRECIO_RANGO = (0.5, 100_000)

# Configuración de búsqueda
DDG_MAX_RESULTS = 8
MAX_URLS_ANALIZAR = 10
PLAYWRIGHT_CONCURRENCY = 3
MIN_URLS_ACEPTABLE = 3
MAX_URLS_TOTAL = 8

