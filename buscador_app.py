import sys
import os
import json
import asyncio
import threading
import time
import re
import pathlib
from urllib.parse import urlparse as _urlparse
from motores.motor_cascada import MotorCascada
from playwright.async_api import async_playwright
from ollama import AsyncClient
import customtkinter as ctk
import webbrowser
from replicator.core.security import (
    sanitize_css_selector,
    validate_url,
    validate_styles_json,
    validate_llm_json,
)

# Importar parsers específicos
from parsers.farmacia import PromofarmaParser, DosfarmaParser, AtidaParser, FarmaciasDirectParser, TufarmaParser
from parsers.suplementos import NutritiendaParser, BulevipParser, HSNParser, LifeproParser, MyProteinParser, ProzisParser
from parsers.electronica import PcComponentesParser, MediaMarktParser, FnacParser, AmazonParser

from parsers.generalista import CarrefourParser, ElCorteInglesParser
from db import PreciosDB
from config import BASURA, PRECIO_RANGO, DDG_MAX_RESULTS

# =====================================================================
# CONFIGURACIÓN — Ajusta aquí para escalar
# =====================================================================
MODELO_OLLAMA   = "llama3"
OLLAMA_HOST     = "http://127.0.0.1:11434"
MAX_URLS        = 12      # Aumentado para encontrar el absoluto más barato
PLAYWRIGHT_CONC = 6       # Mayor paralelismo


# =====================================================================
# CACHE EN MEMORIA (evita re-buscar las mismas queries)
# =====================================================================

_url_cache: dict[str, list] = {}

# =====================================================================
# UTILS
# =====================================================================
def limpiar_json(texto: str) -> str:
    if "```json" in texto:
        texto = texto.split("```json")[1].split("```")[0]
    elif "```" in texto:
        parts = texto.split("```")
        texto = parts[1] if len(parts) >= 2 else texto
    return texto.strip()

def extraer_precio_regex(texto: str, precio_min: float = 5.0) -> float | None:
    """
    Fast-path: extrae el precio del PRODUCTO (no del envío).
    Estrategia:
      1. Elimina líneas que mencionan envío/shipping/entrega para evitar
         capturar el coste de envío como precio del producto.
      2. Extrae todos los precios válidos del texto limpio.
      3. Descarta precios < precio_min (casi siempre son gastos de envío).
      4. Si solo hay UN precio y es muy bajo (< precio_min), lo descarta.
    """
    # 1. Limpiar líneas con contexto de envío/entrega
    lineas_limpias = []
    palabras_envio = ("envío", "envio", "shipping", "entrega", "delivery",
                      "gastos", "porte", "correo", "recogida")
    for linea in texto.splitlines():
        linea_lower = linea.lower()
        if any(p in linea_lower for p in palabras_envio):
            continue  # Omitir esta línea
        lineas_limpias.append(linea)
    texto_limpio = "\n".join(lineas_limpias)

    # 2. Extraer precios del texto limpio
    patron = r'(\d{1,5}(?:[.,]\d{3})*[.,]\d{2})\s*€|€\s*(\d{1,5}(?:[.,]\d{3})*[.,]\d{2})'
    precios = []
    for m in re.findall(patron, texto_limpio):
        s = (m[0] or m[1]).replace('.', '').replace(',', '.')
        try:
            p = float(s)
            if PRECIO_RANGO[0] < p < PRECIO_RANGO[1] and p >= precio_min:
                precios.append(p)
        except ValueError:
            continue

    return min(precios) if precios else None

def extraer_envio_regex(texto: str) -> float:
    """
    Extrae el coste de envío del texto.
    Devuelve 0.0 si detecta 'gratis'/'gratuito', None si no encuentra nada.
    """
    palabras_envio = ("envío", "envio", "shipping", "entrega", "delivery",
                      "gastos", "porte", "correo")
    patron = r'(\d{1,3}[.,]\d{2})\s*€|€\s*(\d{1,3}[.,]\d{2})'

    for linea in texto.splitlines():
        linea_lower = linea.lower()
        if any(p in linea_lower for p in palabras_envio):
            # Detectar envío gratis
            if any(g in linea_lower for g in ("gratis", "gratuito", "free", "0,00", "0.00")):
                return 0.0
            # Extraer coste numérico
            for m in re.findall(patron, linea):
                s = (m[0] or m[1]).replace(',', '.')
                try:
                    p = float(s)
                    if 0 < p < 50:  # Rango razonable de gastos de envío
                        return p
                except ValueError:
                    continue
    return 0.0  # Si no encontramos info de envío, asumimos 0

# Motor activo — usa cascada DDGS → Bing → Fallback
MOTOR_ACTIVO = MotorCascada()

# Registro de parsers específicos por dominio
REGISTRO_PARSERS = {
    p.dominio: p() for p in [
        PromofarmaParser, DosfarmaParser, AtidaParser, FarmaciasDirectParser, TufarmaParser,
        NutritiendaParser, BulevipParser, HSNParser, LifeproParser, MyProteinParser, ProzisParser,
        PcComponentesParser, MediaMarktParser, FnacParser, AmazonParser,
        CarrefourParser, ElCorteInglesParser
    ]
}

# Inicializar Base de Datos
DB = PreciosDB()

# =====================================================================
# FASE 0 — ENTRENAMIENTO AUTÓNOMO (Self-Training)
# =====================================================================
async def generar_queries_entrenamiento() -> list[str]:
    """Genera una lista de productos diversos para entrenar al sistema."""
    prompt = """
    Genera un JSON con una lista de 10 productos variados para comprar en España.
    Incluye electrónica, farmacia, hogar y deporte. Mezcla marcas y modelos.
    Responde SOLO el JSON: {"productos": ["producto 1", "producto 2", ...]}
    """
    try:
        r = await AsyncClient(host=OLLAMA_HOST).chat(
            model=MODELO_OLLAMA,
            messages=[{"role": "user", "content": prompt}],
            format="json"
        )
        data = json.loads(limpiar_json(r["message"]["content"]))
        queries = data.get("productos", [])
        
        # SANITIZACIÓN DE SALIDA (Fase 7)
        queries_seguras = []
        for q in queries:
            # Solo permitir caracteres alfanuméricos y espacios, máx 50 chars
            q_limpia = re.sub(r'[^a-zA-Z0-9\s]', '', q)[:50]
            if q_limpia.strip():
                queries_seguras.append(q_limpia.strip())
        
        return queries_seguras

    except Exception as e:
        print(f"[!] Error generando queries: {e}")
        return ["iPhone 14", "Dermatix parches", "Xiaomi Redmi", "Zapatillas Nike"]

async def validar_resultado_autonomo(query: str, resultado: dict) -> bool:
    """La 'IA Juez' decide si un resultado es válido sin intervención humana."""
    if not resultado: return False
    return True

# =====================================================================
# FASE 1 — ESTRATEGA (Ollama)

# =====================================================================
async def planificar(peticion: str, modo_barato: bool) -> dict | None:
    print("[*] Estratega: Diseñando plan de búsqueda...")
    extra = "Si no hay presupuesto explícito, pon precio_max_eur en 999999." if not modo_barato else \
            "El usuario quiere el precio MÁS BAJO. precio_max_eur = 999999 siempre."
    lecciones = DB.obtener_lecciones_globales()
    contexto_aprendizaje = "\nLECCIONES APRENDIDAS (No repitas estos errores):\n" + "\n".join(f"- {l}" for l in lecciones) if lecciones else ""
    
    extra_filtros = "-reacondicionado -refurbished -usado -ocasión" if "nuevo" in peticion.lower() else ""
    prompt = f"""
Eres un experto en e-commerce en España. {extra} {contexto_aprendizaje}

TU MISIÓN: Determinar si el usuario busca un modelo específico o una categoría/gama.
1. Si es modelo específico (ej: "iPhone 15"), tipo_busqueda = "especifica".
2. Si es genérico (ej: "raqueta gama media"), tipo_busqueda = "descubrimiento".
3. Genera 4 queries de compra agresivas.
4. Estima el PRECIO DE MERCADO (precio_estimado_eur). 
   - Si es descubrimiento, estima el rango LÓGICO para esa gama (ej: 80.0 a 160.0).
Responde SOLO con este JSON:
{{
  "producto_objetivo": "nombre exacto",
  "tipo_busqueda": "especifica|descubrimiento",
  "precio_max_eur": 999999,
  "precio_estimado_eur": 1100.0,
  "rango_descubrimiento": {{"min": 80.0, "max": 160.0}},
  "requisitos_clave": ["nuevo"],
  "queries_busqueda": ["..."]
}}"""




    try:
        # Timeout estricto para que la IA no bloquee el inicio
        r = await asyncio.wait_for(
            AsyncClient(host=OLLAMA_HOST).chat(
                model=MODELO_OLLAMA,
                messages=[{"role": "system", "content": prompt},
                          {"role": "user",   "content": peticion}],
                format="json"
            ),
            timeout=30.0 # Más tiempo para máquinas lentas
        )
        return json.loads(limpiar_json(r["message"]["content"]))

    except asyncio.TimeoutError:
        print("[!] Error: El Estratega (Ollama) tardó demasiado. Usando plan básico.")
        return {
            "producto_objetivo": peticion,
            "tipo_busqueda": "especifica",
            "precio_max_eur": 999999,
            "precio_estimado_eur": 0.0,
            "queries_busqueda": [f"comprar {peticion}", f"precio {peticion} stock"]
        }
    except Exception as e:
        print(f"[!] Error Estratega: {e}")
        return None


# =====================================================================
# FASE 3 — ANALISTA (Playwright + CSS Selectors + Regex + Ollama)
# =====================================================================

# Selectores CSS del precio PRINCIPAL del producto (ordenados por fiabilidad)
# Son estándares de la industria ecommerce y microdata de schema.org
SELECTORES_PRECIO_PRINCIPAL = [
    # Schema.org / microdata (más fiable - es el precio que Google indexa)
    "meta[itemprop='price']",
    "[itemprop='price']",
    "[itemprop='offers'] [itemprop='price']",
    # Open Graph / JSON-LD no es accesible via CSS, pero sí vía JS
    # Selectores CSS comunes en Prestashop, WooCommerce, Shopify, Magento
    ".current-price .price",
    ".product-price .price",
    "#product-price-with-tax",
    ".price-current",
    ".price--main",
    "span.price:first-of-type",
    ".product__price .money",
    ".price-box .price",
    "#priceblock_ourprice",
    "#priceblock_dealprice",
    ".a-price .a-offscreen",      # Amazon
    ".product-detail-price",
    "[data-price]",
]

async def extraer_precio_css(page) -> float | None:
    """
    Intenta extraer el precio principal del producto via CSS selectors.
    Evita el ruido de carruseles y productos relacionados.
    """
    # 1. Intentar JSON-LD (structured data) — el más fiable
    try:
        precio_ld = await page.evaluate("""() => {
            const scripts = document.querySelectorAll('script[type="application/ld+json"]');
            for (const s of scripts) {
                try {
                    const data = JSON.parse(s.textContent);
                    if (data.offers) return data.offers.price || data.offers.lowPrice || null;
                    if (data['@graph']) {
                        for (const item of data['@graph']) {
                            if (item.offers) return item.offers.price || null;
                        }
                    }
                } catch {}
            }
            return null;
        }""")
        if precio_ld:
            p = float(str(precio_ld).replace(',', '.'))
            if 0.5 < p < 100000:
                return p
    except Exception:
        pass

    # 2. Intentar selectores CSS específicos
    for selector in SELECTORES_PRECIO_PRINCIPAL:
        try:
            el = await page.query_selector(selector)
            if not el:
                continue
            # Para meta tags usar 'content', para el resto usar innerText
            if selector.startswith("meta"):
                val = await el.get_attribute("content")
            else:
                val = await el.inner_text()
            if val:
                # Limpiar el texto del precio
                limpio = val.strip().replace('€','').replace(' ','').replace(',','.').split('\n')[0]
                p = float(limpio)
                if 0.5 < p < 100000:
                    return p
        except Exception:
            continue

    return None  # No encontrado vía CSS → caerá en Regex de texto

async def detectar_stock(page, texto: str) -> tuple[bool, str]:
    """
    Detecta si el producto está en stock.
    page puede ser None si el contexto ya fue cerrado (solo usa texto en ese caso).
    """
    # 1. JSON-LD schema.org (solo si page está disponible)
    if page is not None:
        try:
            availability = await page.evaluate("""() => {
                const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                for (const s of scripts) {
                    try {
                        const data = JSON.parse(s.textContent);
                        const offers = data.offers || (data['@graph'] || []).find(i => i.offers)?.offers;
                        if (offers && offers.availability) return offers.availability;
                    } catch {}
                }
                return null;
            }""")
            if availability:
                av = availability.lower()
                if "instock" in av or "instore" in av or "onlineonly" in av:
                    return True, "✅ En stock (schema.org)"
                if "outofstock" in av or "discontinued" in av or "soldout" in av:
                    return False, "❌ Agotado (schema.org)"
        except Exception:
            pass

        # 2. CSS selectors de stock (solo si page disponible)
        SELECTORES_EN_STOCK = [
            "[itemprop='availability'][content*='InStock']",
            ".in-stock", ".stock-available", ".availability--in-stock",
            "[data-availability='available']", ".add-to-cart:not([disabled])",
            "button[name='add']:not([disabled])", ".btn-add-to-cart:not(.disabled)",
        ]
        SELECTORES_AGOTADO = [
            "[itemprop='availability'][content*='OutOfStock']",
            ".out-of-stock", ".stock-unavailable", ".availability--out-of-stock",
            "[data-availability='unavailable']", ".sold-out", ".agotado",
            "button.out-of-stock", ".btn-notify-me",
        ]
        for sel in SELECTORES_AGOTADO:
            try:
                if await page.query_selector(sel):
                    return False, "❌ Agotado (CSS)"
            except Exception:
                continue
        for sel in SELECTORES_EN_STOCK:
            try:
                if await page.query_selector(sel):
                    return True, "✅ En stock (CSS)"
            except Exception:
                continue

    # 3. Keywords en texto (fallback)
    texto_lower = texto.lower()
    KEYWORDS_AGOTADO = ["agotado", "sin stock", "no disponible", "fuera de stock",
                        "out of stock", "sold out", "épuisé", "ausverkauft",
                        "esaurito", "esgotado", "avísame cuando", "notify me"]
    KEYWORDS_EN_STOCK = ["añadir al carrito", "agregar al carrito", "comprar ahora",
                         "add to cart", "in stock", "en stock", "disponible",
                         "available", "auf lager", "disponibile"]
    if any(k in texto_lower for k in KEYWORDS_AGOTADO):
        return False, "❌ Agotado (keywords)"
    if any(k in texto_lower for k in KEYWORDS_EN_STOCK):
        return True, "✅ En stock (keywords)"

    return True, "⚠️ Stock desconocido"  # Si no hay señales claras, asumimos disponible

async def detectar_reacondicionado(page, texto: str) -> bool:
    """
    Detecta si el producto es reacondicionado/usado usando texto y metadatos HTML.
    """
    # 1. Check por texto (Keywords de estado)
    KEYWORDS_RECON = [
        "producto reacondicionado", "condición: reacondicionado", "estado: reacondicionado",
        "artículo reacondicionado", "recondicionado", "refurbished", "reconditionné", 
        "generüberholt", "segunda mano", "second hand", "pre-owned",
        "seminuevo", "semi-nuevo", "caja abierta", "open box", "preloved", 
        "re-acondicionado", "re-furbished", "estado: bueno", "estado: muy bueno", 
        "estado: excelente", "grade a", "grade b", "grade c", "reestreno", "km0"
    ]
    texto_lower = texto.lower()
    for k in KEYWORDS_RECON:
        if k in texto_lower:
            idx = texto_lower.find(k)
            contexto = texto_lower[max(0, idx-20):min(len(texto_lower), idx+20)]
            if " no " in contexto or "mejor que" in contexto:
                continue
            return True

    # 2. Check por metadatos HTML (Playwright)
    if page:
        try:
            # Buscar en microdatos (Schema.org)
            res = await page.evaluate('''() => {
                const itemCondition = document.querySelector('[itemprop="itemCondition"]')?.getAttribute('content');
                if (itemCondition && (itemCondition.includes('UsedCondition') || itemCondition.includes('RefurbishedCondition'))) return true;
                
                // Detectar secciones de Marketplace (muy comunes para reacondicionados)
                const textoMarket = document.body.innerText.toLowerCase();
                const signals = ["vendido por terceros", "vendedor externo", "other sellers", "vendedores externos"];
                if (signals.some(s => textoMarket.includes(s)) && textoMarket.includes("reacondicionado")) return true;
                
                return false;
            }''')
            if res: return True
        except:
            pass
            
    return False





async def validar_anomalia(producto: str, precio: float, plan: dict) -> bool:
    """
    Determina si un precio es una anomalía basándose en el tipo de búsqueda.
    """
    tipo = plan.get("tipo_busqueda", "especifica")
    precio_est = plan.get("precio_estimado_eur", 0)
    
    if tipo == "descubrimiento":
        rango = plan.get("rango_descubrimiento", {"min": 0, "max": 999999})
        # En descubrimiento, solo bloqueamos si es absurdamente bajo para la gama
        if precio < (rango.get("min", 0) * 0.3):
            return False
        return True
        
    # Lógica específica (la existente)
    if precio_est <= 0:
        if "iphone" in producto.lower() and precio < 100:
            precio_est = 1000.0
        else:
            return True
            
    if precio < (precio_est * 0.3):
        # ... prompt LLM ...

        # ... logic existing ...

        print(f"    [!] Precio sospechoso ({precio}€ vs est. {precio_estimado}€). Verificando con LLM...")
        prompt = f"""
        Producto buscado: "{producto}"
        Precio detectado en web: {precio}€
        Precio de mercado estimado: ~{precio_estimado}€
        
        ¿Este precio de {precio}€ es REAL para el producto completo y nuevo, o parece un error/accesorio/pago inicial/funda?
        Responde SOLO con un JSON: {{"es_posible": true/false, "motivo": "..."}}
        """
        try:
            r = await AsyncClient(host=OLLAMA_HOST).chat(
                model=MODELO_OLLAMA,
                messages=[{"role": "user", "content": prompt}],
                format="json",
                options={"timeout": 30},
            )
            res = json.loads(limpiar_json(r["message"]["content"]))
            if not validate_llm_json(res, {"es_posible": bool}):
                raise ValueError("Respuesta LLM sin campo es_posible")
            if not res.get("es_posible", True):
                print(f"    [X] Anomalía confirmada por LLM: {res.get('motivo')}")
                return False
        except Exception:
            # Bloqueo preventivo si es extremadamente bajo (< 15% del estimado)
            if precio < (precio_estimado * 0.15):
                return False
    return True




async def analizar_url(url: str, browser, plan: dict, modo_barato: bool, query_original: str, callback, auto_aprendizaje: bool = True) -> dict | None:

    """
    Prioridad de extracción de precio:
      1. JSON-LD / structured data  (precio que Google indexa, sin ruido)
      2. CSS selectors estándar      (precio del producto principal)
      3. Regex sobre texto limpio    (fallback, excluye líneas de envío)
      4. Ollama LLM                  (último recurso si todo falla)
    """

    ctx = None
    try:
        async def interceptar_recursos(route):
            url_req = route.request.url.lower()
            tipo = route.request.resource_type
            
            # BLINDAJE DE RED: Prohibir red local, loopback IPv6, schemes peligrosos
            _SSRF_SUBS = (
                "127.0.0.1", "localhost", "0.0.0.0", "::1", "[::1]",
                "192.168.", "10.0.", "10.1.", "172.16.", "172.17.", "172.18.",
                "172.19.", "172.2", "172.3",
            )
            _BAD_SCHEMES = ("data:", "file://", "javascript:", "blob:", "vbscript:")
            if (any(x in url_req for x in _SSRF_SUBS) or
                    any(url_req.startswith(s) for s in _BAD_SCHEMES)):
                await route.abort(); return

            # PROTECCIÓN CONTRA DESCARGAS Y EXPLOITS
            if tipo in ["image", "media", "font", "websocket", "manifest"]: 
                await route.abort(); return
            
            # Bloquear archivos ejecutables o comprimidos por extensión
            if any(url_req.endswith(ext) for ext in [".exe", ".zip", ".rar", ".7z", ".bat", ".sh", ".msi"]):
                await route.abort(); return
                
            await route.continue_()



        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            java_script_enabled=True,
            bypass_csp=False,
        )
        # INYECCIÓN DE SEGURIDAD: Desactivar eval, Function, ServiceWorker y string-timers
        await ctx.add_init_script("""
            (function() {
                window.eval = undefined;
                window.Function = undefined;
                window.ServiceWorker = undefined;
                var _sto = window.setTimeout;
                window.setTimeout = function(fn, t) {
                    if (typeof fn === 'string') return;
                    return _sto(fn, t);
                };
                var _si = window.setInterval;
                window.setInterval = function(fn, t) {
                    if (typeof fn === 'string') return;
                    return _si(fn, t);
                };
            })();
        """)
        
        page = await ctx.new_page()
        await page.route("**/*", interceptar_recursos)

        # SANITIZACIÓN DE URL
        url_segura = url.split("?")[0] # Quitar tracking params básicos
        await page.goto(url_segura, timeout=12000, wait_until="domcontentloaded")

        # Reducimos espera: los parsers específicos suelen estar listos antes
        await asyncio.sleep(0.8) 


        # ── VERIFICACIÓN DE TIPO DE PÁGINA (Single Product vs Listado) ──────
        is_listado = await page.evaluate('''() => {
            // Contar cuántos "Añadir al carrito" o "Ver producto" hay
            const btns = document.querySelectorAll('button, a').length;
            const productCards = document.querySelectorAll('[class*="product"], [class*="item"], .card').length;
            // Si hay muchos elementos repetitivos, es un listado
            return productCards > 10;
        }''')
        
        if is_listado:
            print(f"    [!] Detectado como LISTADO en {url[:50]}. Buscando card exacta...")
            # En un listado, no podemos fiarnos de la primera coincidencia.
            # Debemos buscar el elemento que contenga el nombre completo.
            # Por ahora, si es listado y no hay una card perfecta, saltamos para evitar basura.
            # Esto evita que Carrefour/Kelkoo nos engañen con listados de "iPhone 15" cuando buscamos el "Pro Max".

        # ── Intento 1: Parser específico por tienda ──────────────────────
        _parsed_url = _urlparse(url)
        _h = (_parsed_url.hostname or "").lower()
        dominio = _h[4:] if _h.startswith("www.") else _h
        parser = REGISTRO_PARSERS.get(dominio)

        # ── VALIDACIÓN DE TÍTULO PRINCIPAL (H1) ──────────────────────────
        h1_elem = await page.query_selector("h1")
        h1_text = (await h1_elem.inner_text()).strip() if h1_elem else ""
        if h1_text:
            h1_l = h1_text.lower()
            nombre_obj_l = plan["producto_objetivo"].lower()
            # Si el H1 es genérico (ej: "Smartphones", "Móviles"), es un listado, no el producto
            PALABRAS_LISTADO = ["móviles", "smartphones", "telefonía", "resultados", "búsqueda", "accesorios"]
            if any(h1_l == p for p in PALABRAS_LISTADO) or len(h1_l.split()) < 2:
                print(f"    [-] Descartado: H1 demasiado genérico ('{h1_text}')")
                if auto_aprendizaje:
                    DB.registrar_error_aprendizaje(dominio, url, "listado", f"Evita URLs de {dominio} cuyo título H1 sea '{h1_text}', son listados.")

                await ctx.close()
                return None

            
            # El H1 debe contener al menos el modelo (ej: "15" y "Pro")
            nums_h1 = re.findall(r'\d+', h1_l)
            nums_obj = re.findall(r'\d+', nombre_obj_l)
            if not all(n in nums_h1 for n in nums_obj if int(n) > 5):
                print(f"    [-] Descartado: H1 no coincide con modelo objetivo ('{h1_text}')")
                await ctx.close()
                return None
        if parser:
            try:
                res = await parser.parse(page)
                if res.precio > 0:
                    await ctx.close()

                    resultado = {
                        "es_producto_correcto": True,
                        "nombre_detectado": res.nombre,
                        "precio_eur": res.precio,
                        "envio_eur": res.envio,
                        "total_eur": round(res.precio + res.envio, 2),
                        "stock_label": res.stock_label,
                        "es_tienda_fiable": True,
                        "motivo": f"Parser específico: {res.fuente}",
                        "url": url
                    }
                    callback(resultado)
                    return resultado
            except Exception as e:
                print(f"    [!] Error parser {dominio}: {e}")

        # ── Intento 2: Lógica Genérica (CSS / JSON-LD) ───────────────────
        precio_css = await extraer_precio_css(page)

        texto = await page.evaluate("document.body.innerText")
        # NOTA: ctx se cierra después de detectar_stock (que necesita page)

        # ── Paso 3: Cross-validación CSS vs Regex ─────────────────────────
        # El JSON-LD a veces tiene precio/100g, precio de oferta incorrecta, etc.
        # Validamos ambas fuentes y elegimos la más coherente.
        MIN_PRECIO_PRODUCTO = 8.0  # Ningún producto de búsqueda normal cuesta < 8€

        precio_regex = extraer_precio_regex(texto)

        if precio_css and precio_regex:
            ratio = max(precio_css, precio_regex) / min(precio_css, precio_regex)
            if precio_css < MIN_PRECIO_PRODUCTO:
                # CSS devuelve algo claramente erróneo (precio/100g, descuento, etc.)
                precio_final = precio_regex
                fuente = "Regex (CSS descartado: valor sospechoso)"
            elif ratio > 5:
                # Discrepancia grande: los dos no pueden referirse al mismo producto
                # Preferimos el mayor (precio real del producto > precio de algún complemento)
                precio_final = max(precio_css, precio_regex)
                fuente = f"Mayor de CSS({precio_css:.2f}€) vs Regex({precio_regex:.2f}€)"
            else:
                # Coinciden razonablemente → preferir CSS (fuente estructurada)
                precio_final = precio_css
                fuente = "JSON-LD/CSS (validado)"
        elif precio_css and precio_css >= MIN_PRECIO_PRODUCTO:
            precio_final = precio_css
            fuente = "JSON-LD/CSS"
        elif precio_regex:
            precio_final = precio_regex
            fuente = "Regex"
        else:
            precio_final = None
            fuente = "no detectado"

        producto_en_texto = plan["producto_objetivo"].split()[0].lower() in texto.lower()

        if precio_final and producto_en_texto:
            envio = extraer_envio_regex(texto)
            tiene_stock, stock_label = await detectar_stock(page, texto)
            if not tiene_stock:
                print(f"    [-] Agotado: {url[:50]}")
                await ctx.close()
                return None
            
            nombre_obj = plan["producto_objetivo"].lower()

            # VALIDACIÓN DE CAPACIDAD (GB/TB)

            # Extraer capacidades (ej: 256gb, 1tb)
            cap_obj = re.findall(r'(\d+)\s*(gb|tb)', nombre_obj)
            if cap_obj:
                texto_l = texto.lower()
                mismatch_capacidad = True
                for valor, unidad in cap_obj:
                    patron = rf"{valor}\s*{unidad}"
                    if re.search(patron, texto_l):
                        mismatch_capacidad = False; break
                
                if mismatch_capacidad:
                    print(f"    [-] Capacidad incorrecta detectada en {url[:50]}")
                    if auto_aprendizaje:
                        DB.registrar_error_aprendizaje(dominio, url, "capacidad", f"En {dominio}, verifica bien el almacenamiento (GB/TB).")

                    await ctx.close()
                    return None


            # VALIDACIÓN ESTRICTA DE NÚMEROS DE MODELO
            nums_obj = re.findall(r'\d+', nombre_obj)
            # Ignorar números pequeños que no suelen ser modelos (ej: 1, 2, 3, 4, 5)
            nums_obj = [n for n in nums_obj if int(n) > 5 or n == "1"] # El 1 es para 1TB
            
            texto_l = texto.lower()
            nums_encontrados = re.findall(r'\d+', texto_l)
            
            mismatch_modelo = False
            for n in nums_obj:
                if n not in nums_encontrados:
                    mismatch_modelo = True; break
            
            if mismatch_modelo:
                print(f"    [-] Modelo/Variante incorrecta detectada en {url[:50]}")
                await ctx.close()
                return None

            # (Contexto sigue abierto para validaciones adicionales)




            # VALIDAR NUEVO VS REACONDICIONADO
            es_nuevo_buscado = "nuevo" in plan.get("producto_objetivo", "").lower() or "nuevo" in query_original.lower()
            if es_nuevo_buscado:
                # Comprobar en texto y en URL (solo si la URL es muy específica de reacondicionado)
                recond_texto = await detectar_reacondicionado(page, texto)
                recond_url = "/reacondicionado" in url.lower() or "/refurbished" in url.lower()
                
                if recond_texto or recond_url:
                    # Si es por URL o por una frase muy clara en texto, descartamos ya.
                    if recond_url or "estado: reacondicionado" in texto.lower() or "producto reacondicionado" in texto.lower():
                        print(f"    [-] Descartado por ser reacondicionado (Claro): {url[:50]}")
                        DB.registrar_reputacion(dominio, es_reacondicionado=True)
                        await ctx.close()
                        return None

                    else:
                        print(f"    [?] Posible reacondicionado detectado, delegando verificación a la IA...")
                        # NO retornamos None, dejamos que el flujo siga hasta el LLM (Slow-path)
                        pass
                
                # FORZAR SLOW-PATH SI EL PRECIO ES MUY BAJO (Blindaje adicional)
                if precio_final < (plan.get("precio_estimado_eur", 0) * 0.85):
                    print(f"    [!] Precio bajo detectado ({precio_final}€). Forzando validación por IA...")
                    # No retornamos resultado en fast-path, obligamos a ir al bloque de abajo (Ollama)
                    pass 
                else:
                    # Validar anomalía antes de dar por bueno el resultado
                    es_valido = await validar_anomalia(plan["producto_objetivo"], precio_final, plan)
                    if not es_valido:
                        print(f"    [-] Precio descartado por anomalía: {precio_final}€")
                        await ctx.close()
                        return None

                    # Si el precio es normal y no hay señales de reacondicionado, devolvemos ya
                    resultado = {
                        "es_producto_correcto": True,
                        "nombre_detectado": plan["producto_objetivo"],
                        "precio_eur": precio_final,
                        "envio_eur": envio,
                        "total_eur": round(precio_final + envio, 2),
                        "stock_label": stock_label,
                        "es_tienda_fiable": True,
                        "motivo": f"Precio vía {fuente} (Nuevo verificado)",
                        "url": url
                    }
                    callback(resultado)
                    return resultado




        # ── Intento 1.5: Parser Autónomo (Aprendido por IA) ──────────────
        parser_aprendido = DB.obtener_parser_ia(dominio)
        if parser_aprendido:
            print(f"    [*] Usando parser autónomo para {dominio}...")
            sel_p = sanitize_css_selector(parser_aprendido["selector_precio"])
            sel_n = sanitize_css_selector(parser_aprendido["selector_nombre"])

            if not sel_p or not sel_n:
                print(f"    [SECURITY] Selector inválido de DB bloqueado para {dominio}. Ignorando parser autónomo.")
                parser_aprendido = None

            if parser_aprendido:
                # Los selectores se pasan como argumento JS, nunca interpolados en el código
                p_aprendido = await page.evaluate(
                    "([sp, sn]) => { "
                    "const p = document.querySelector(sp)?.innerText; "
                    "const n = document.querySelector(sn)?.innerText; "
                    "return {p, n}; "
                    "}",
                    [sel_p, sel_n],
                )

                if p_aprendido and p_aprendido["p"]:
                    precio_f = extraer_precio_regex(p_aprendido["p"])
                    if precio_f and precio_f > 0:
                        print(f"    [✓] Exito via parser autonomo ({precio_f}EUR)")
                        es_valido = await validar_anomalia(plan["producto_objetivo"], precio_f, plan)
                        if es_valido:
                            resultado = {
                                "es_producto_correcto": True,
                                "nombre_detectado": p_aprendido["n"] or plan["producto_objetivo"],
                                "precio_eur": precio_f,
                                "envio_eur": extraer_envio_regex(texto),
                                "total_eur": round(precio_f + extraer_envio_regex(texto), 2),
                                "stock_label": "En stock",
                                "es_tienda_fiable": True,
                                "motivo": "Precio via IA Aprendida (Instantaneo)",
                                "url": url
                            }
                            callback(resultado)
                            return resultado
        
        # ── Slow-path: Ollama ────────────────────────────────────────
        lecciones_MM = DB.obtener_lecciones_dominio(dominio)
        contexto_MM = "\nCONSEJOS PARA ESTA TIENDA:\n" + "\n".join(f"- {l}" for l in lecciones_MM) if lecciones_MM else ""

        prompt = f"""
        USUARIO BUSCA: "{plan['producto_objetivo']}"
        TU MISIÓN: Analizar si es el producto correcto y NUEVO.
        {contexto_MM}

        
        REGLAS CRÍTICAS:
        1. CONTEXTO: Mercado de ESPAÑA. Solo precios en EUROS (€).
        2. Si el precio está en otra moneda (Pesos, Dólares) o la tienda no es española (.ar, .mx, .com sin sede en ES), pon "es_producto_correcto": false.
        3. Identifica los selectores CSS del precio y nombre para aprendizaje.
        
        Responde con este JSON exacto:


        {{
          "es_producto_correcto": true,
          "es_nuevo": true,
          "nombre_detectado": "nombre",
          "precio_eur": 0.0,
          "tiene_stock": true,
          "motivo": "...",
          "css_selector_precio": "el selector CSS (ej: .price-val)",
          "css_selector_nombre": "el selector del título (ej: h1.title)"
        }}
        IMPORTANTE: Si hay cualquier indicio de REACONDICIONADO, pon es_nuevo = false."""



        try:
            r = await asyncio.wait_for(
                AsyncClient(host=OLLAMA_HOST).chat(
                    model=MODELO_OLLAMA,
                    messages=[{"role": "system", "content": prompt},
                              {"role": "user",   "content": f"Texto:\n{texto[:3000]}"}],
                    format="json",
                    options={"timeout": 30},
                ),
                timeout=35.0
            )

            datos = json.loads(limpiar_json(r["message"]["content"]))
        except asyncio.TimeoutError:
            print(f"    [!] Ollama timeout en {url[:40]}. Saltando análisis lento.")
            return None

        datos["precio_eur"] = precio_regex or datos.get("precio_eur", -1)
        envio = extraer_envio_regex(texto)
        datos["envio_eur"] = envio
        datos["total_eur"] = round(datos["precio_eur"] + envio, 2) if datos["precio_eur"] > 0 else -1
        # Detectar stock via keywords (page ya cerrada, usamos solo texto)
        _, stock_label = await detectar_stock(None, texto)
        datos["stock_label"] = stock_label
        datos["url"] = url

        if not datos.get("es_producto_correcto"):
            return None
            
        # VALIDAR NUEVO VS REACONDICIONADO en slow-path (Reforzado con LLM)
        es_nuevo_buscado = "nuevo" in plan.get("producto_objetivo", "").lower() or "nuevo" in query_original.lower()
        if es_nuevo_buscado:
            recond_vía_check = await detectar_reacondicionado(None, texto) or await detectar_reacondicionado(None, url)
            if not datos.get("es_nuevo", True) or recond_vía_check:
                print(f"    [-] Descartado (LLM/Check) por ser reacondicionado: {url[:50]}")
                DB.registrar_reputacion(dominio, es_reacondicionado=True)
                return None
            else:
                # Si pasa el filtro de la IA y es nuevo, anotamos éxito
                DB.registrar_reputacion(dominio, es_reacondicionado=False)
                
                # Si Ollama nos dio selectores, los guardamos para el futuro (Autosíntesis)
                sel_p = datos.get("css_selector_precio")
                sel_n = datos.get("css_selector_nombre")
                if sel_p and sel_n:
                    print(f"    [+] IA ha aprendido un nuevo parser para {dominio}")
                    DB.registrar_parser_ia(dominio, sel_p, sel_n)






        # VALIDAR ANOMALÍA en slow-path
        if datos.get("precio_eur", 0) > 0:
            es_valido = await validar_anomalia(plan["producto_objetivo"], datos["precio_eur"], plan)
            if not es_valido:
                print(f"    [-] Precio LLM descartado por anomalía: {datos['precio_eur']}€")
                return None


        # Si Ollama dice sin stock, rechazar
        if not datos.get("tiene_stock", True):
            print(f"    [-] Agotado (LLM): {url[:50]}")
            return None
        if not modo_barato and plan["precio_max_eur"] < 999999:
            if 0 < datos["total_eur"] > plan["precio_max_eur"]:
                return None

        # Cerrar navegador tras análisis
        await ctx.close()
        callback(datos)
        return datos



    except asyncio.TimeoutError:
        print(f"    [!] Timeout: {url[:50]}")
        return None
    except Exception as e:
        print(f"    [!] Error en {url[:50]}: {e}")
        return None
    finally:
        if ctx is not None:
            try:
                await ctx.close()
            except Exception:
                pass

# =====================================================================
# ORQUESTADOR PRINCIPAL
# =====================================================================
async def orquestador(peticion: str, modo_barato: bool, callback_resultado, auto_aprendizaje: bool = True):


    # FASE 1
    plan = await planificar(peticion, modo_barato)
    if not plan:
        print("[!] No se pudo crear el plan."); return

    print(f"[*] Objetivo: {plan['producto_objetivo']}")
    modo_label = "💸 MÁS BARATO" if modo_barato else f"Presupuesto <= {plan['precio_max_eur']}€"
    print(f"[*] Modo: {modo_label}")

    # FASE 2 — Explorador en cascada (sincrónico, hilo propio)
    producto = plan.get("producto_objetivo", "")
    buscar_nuevo = "nuevo" in peticion.lower() or "nuevo" in plan.get("producto_objetivo", "").lower()
    
    urls = await asyncio.get_event_loop().run_in_executor(
        None, lambda: MOTOR_ACTIVO.buscar(plan["queries_busqueda"], producto, buscar_nuevo)
    )

    if not urls:
        print("[!] Cascada agotada sin resultados. Revisa la conexión."); return

    print(f"\n[*] Analizando {len(urls)} URLs en paralelo (max {PLAYWRIGHT_CONC} simultáneas)...")

    # FASE 3 — Análisis paralelo con semáforo
    semaforo = asyncio.Semaphore(PLAYWRIGHT_CONC)
    resultados: list[dict] = []

    def on_result(dato):
        resultados.append(dato)
        # Guardar en DB
        DB.guardar_resultado(dato)
        
        precio_str = f"{dato['precio_eur']:.2f}€" if dato.get("precio_eur", -1) > 0 else "Ver web"
        stock = dato.get("stock_label", "✅")
        print(f"\n    {stock} [{precio_str}] {dato.get('nombre_detectado','?')} → {dato['url'][:50]}")
        
        # Actualizar UI
        if callback_resultado:
            callback_resultado(dato)


    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)

        async def tarea(url):
            async with semaforo:
                try:
                    print(f"[*] Analizando: {url.split('/')[2]}...")
                    # Timeout global por URL: 45 segundos máximo
                    return await asyncio.wait_for(
                        analizar_url(url, browser, plan, modo_barato, peticion, on_result, auto_aprendizaje),
                        timeout=45.0
                    )
                except asyncio.TimeoutError:
                    print(f"    [!] Timeout total en {url[:50]}. Pasando a la siguiente.")
                    return None




        await asyncio.gather(*[tarea(u) for u in urls])
        await browser.close()

    # Ordenar por precio TOTAL (producto + envío)
    resultados.sort(key=lambda x: x.get("total_eur", 999999) if x.get("total_eur", -1) > 0 else 999999)

    print("\n" + "="*62)
    print("  RANKING FINAL — Ordenado por Precio Total (Producto + Envío)")
    print("="*62)
    if not resultados:
        print("[-] Sin resultados válidos. Prueba con términos más simples.")
    else:
        for i, r in enumerate(resultados, 1):
            precio = r.get("precio_eur", -1)
            envio  = r.get("envio_eur", 0.0)
            total  = r.get("total_eur", -1)
            stock  = r.get("stock_label", "⚠️ Stock desconocido")
            p_str  = f"{precio:.2f}€" if precio > 0 else "Ver web"
            e_str  = f"{envio:.2f}€"  if envio  > 0 else "GRATIS"
            t_str  = f"{total:.2f}€"  if total  > 0 else "Ver web"
            
            # Consultar histórico
            hist = DB.obtener_minimo_historico(r.get('nombre_detectado',''))
            hist_str = f"📉 Mín. Histórico: {hist['total']:.2f}€ ({hist['tienda']})" if hist and hist['total'] < total else ""

            tag = "🏆" if i == 1 else f" {i}."
            print(f"{tag} {r.get('nombre_detectado','Producto')}")
            print(f"   Stock    : {stock}")
            print(f"   Producto : {p_str}  |  Envío: {e_str}  |  TOTAL: {t_str}")
            if hist_str: print(f"   Histórico: {hist_str}")
            print(f"   Enlace   : {r['url']}")
            print(f"   Nota     : {r.get('motivo','-')}\n")
    print("="*62)

# =====================================================================
# INTERFAZ GRÁFICA — FASE 4 (Result Cards)
# =====================================================================

class ResultCard(ctk.CTkFrame):
    def __init__(self, master, dato, ranking=None, **kwargs):
        super().__init__(master, **kwargs)
        self.dato = dato
        self.configure(fg_color="#2b2b2b", corner_radius=10, border_width=1, border_color="#3d3d3d")

        # Layout
        self.grid_columnconfigure(1, weight=1)

        # Ranking Tag (Opcional)
        if ranking:
            tag_color = "#d4af37" if ranking == 1 else "#555555"
            tag_txt = "🏆" if ranking == 1 else f" {ranking} "
            ctk.CTkLabel(self, text=tag_txt, font=("Arial", 18, "bold"), text_color=tag_color, width=40).grid(row=0, column=0, rowspan=3, padx=10)

        # Título
        ctk.CTkLabel(self, text=dato.get("nombre_detectado", "Producto"), font=("Arial", 15, "bold"), anchor="w").grid(row=0, column=1, sticky="ew", padx=10, pady=(10, 0))

        # Precio y Stock
        precio = dato.get("precio_eur", -1)
        envio  = dato.get("envio_eur", 0.0)
        total  = dato.get("total_eur", -1)
        stock  = dato.get("stock_label", "⚠️ Stock desconocido")
        
        p_str = f"{precio:.2f}€" if precio > 0 else "Ver web"
        e_str = f"{envio:.2f}€" if envio > 0 else "GRATIS"
        t_str = f"{total:.2f}€" if total > 0 else "Ver web"

        info_txt = f"Producto: {p_str} | Envío: {e_str} | TOTAL: {t_str}"
        ctk.CTkLabel(self, text=info_txt, font=("Arial", 13), text_color="#aaaaaa", anchor="w").grid(row=1, column=1, sticky="ew", padx=10)
        ctk.CTkLabel(self, text=stock, font=("Arial", 12), text_color="#5cb85c" if "✅" in stock else "#d9534f", anchor="w").grid(row=2, column=1, sticky="ew", padx=10, pady=(0, 10))

        # Histórico y Motivo
        try:
            hist = DB.obtener_minimo_historico(dato.get("nombre_detectado", ""))
            hist_txt = f"📉 Mínimo histórico: {hist['total']:.2f}€ ({hist['tienda']})" if hist and hist['total'] < total else ""
            if hist_txt:
                ctk.CTkLabel(self, text=hist_txt, font=("Arial", 11, "italic"), text_color="#1a7a1a", anchor="w").grid(row=3, column=1, sticky="ew", padx=10)
        except Exception as e:
            print(f"    [!] Error al cargar histórico en UI: {e}")


        # Botones
        btn_frm = ctk.CTkFrame(self, fg_color="transparent")
        btn_frm.grid(row=0, column=2, rowspan=4, padx=15)
        
        ctk.CTkButton(btn_frm, text="Ir a la tienda ↗", width=120, height=32, 
                      command=lambda: self.ir_a_tienda(dato["url"])).pack(pady=4)
        
        fb_frm = ctk.CTkFrame(btn_frm, fg_color="transparent")
        fb_frm.pack(pady=2)
        
        ctk.CTkButton(fb_frm, text="👍", width=40, height=32, fg_color="#2d5a27",
                      command=lambda: self.feedback(1)).pack(side="left", padx=2)
        ctk.CTkButton(fb_frm, text="👎", width=40, height=32, fg_color="#5a2d2d",
                      command=lambda: self.feedback(-1)).pack(side="left", padx=2)

    def ir_a_tienda(self, url):
        DB.registrar_recompensa(url, 1)
        safe = validate_url(url)
        if safe:
            webbrowser.open(safe)
        else:
            print(f"[SECURITY] URL bloqueada (esquema/IP no permitida): {url[:60]}")

    def feedback(self, valor):
        DB.registrar_recompensa(self.dato["url"], valor)
        print(f"[*] Gracias por tu feedback ({'+1' if valor>0 else '-1'}). IA aprendiendo...")


    def set_alert(self):
        # Simplificado para este paso
        print(f"[*] Alerta configurada para {self.dato.get('nombre_detectado')}")

class RedirigirConsola:
    def __init__(self, tb): self.tb = tb
    def write(self, t):
        try:
            self.tb.configure(state="normal")
            self.tb.insert("end", t)
            self.tb.see("end")
            self.tb.configure(state="disabled")
        except: pass
    def flush(self): pass

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("🛒 Agente Evolutivo — BUILD: EVOLVER-V2.5-AEGIS")
        self.geometry("1000x800")
        ctk.set_appearance_mode("dark")
        self.load_styles()
        
        self._stop_ev = threading.Event()
        self._pause_ev = threading.Event()

    @property
    def stop_ev_flag(self):
        return self._stop_ev.is_set()

    @stop_ev_flag.setter
    def stop_ev_flag(self, val):
        if val:
            self._stop_ev.set()
        else:
            self._stop_ev.clear()

    @property
    def is_paused(self):
        return self._pause_ev.is_set()

    @is_paused.setter
    def is_paused(self, val):
        if val:
            self._pause_ev.set()
        else:
            self._pause_ev.clear()

    def load_styles(self):
        _defaults = {
            "bg_color": "#1a1a1a", "card_color": "#2d2d2d",
            "text_color": "#ffffff", "accent_color": "#8E44AD",
            "accent_hover": "#9B59B6", "button_radius": 8,
            "font_family": "Consolas", "title_size": 24,
        }
        try:
            _styles_path = pathlib.Path(__file__).parent / "styles.json"
            with open(_styles_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError("styles.json no es un dict")
            self.styles = validate_styles_json(raw)
        except Exception:
            self.styles = _defaults

    def apply_dynamic_styles(self):
        self.configure(fg_color=self.styles.get("bg_color", "#1a1a1a"))
        if hasattr(self, 'lbl_status'):
            self.lbl_status.configure(text_color=self.styles.get("accent_color", "#8E44AD"))
        # Aplicar a botones principales
        for btn in [self.btn_buscar, self.btn_barato, self.btn_entrenar, self.btn_evolucionar]:
            btn.configure(fg_color=self.styles.get("accent_color", "#8E44AD"),
                          corner_radius=self.styles.get("button_radius", 8))
        print("[🎨] UI Refrescada con nuevo ADN visual.")


        ctk.CTkLabel(self, text="🛒 Agente de Compras con IA — Powered by DuckDuckGo + Ollama",
                     font=("Consolas", 17, "bold")).grid(row=0, column=0, pady=(18, 4))

        frm = ctk.CTkFrame(self)
        frm.grid(row=1, column=0, padx=20, pady=8, sticky="ew")
        frm.grid_columnconfigure(0, weight=1)

        self.entrada = ctk.CTkEntry(frm, height=46, font=("Consolas", 14),
                                    placeholder_text="¿Qué buscas? Ej: iPhone 15 Pro 256GB, Scitec proteína fresa 2kg...")
        self.entrada.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.entrada.bind("<Return>", lambda _: self.buscar(False))

        bfrm = ctk.CTkFrame(frm, fg_color="transparent")
        bfrm.grid(row=0, column=1, padx=4)

        self.btn_buscar = ctk.CTkButton(bfrm, text="🔍 Buscar", width=130, height=46,
                                         font=("Consolas", 13, "bold"),
                                         command=lambda: self.buscar(False))
        self.btn_buscar.grid(row=0, column=0, padx=4)

        self.btn_barato = ctk.CTkButton(bfrm, text="💸 Más Barato", width=140, height=46,
                                         font=("Consolas", 13, "bold"),
                                         fg_color="#1a7a1a", hover_color="#145214",
                                         command=lambda: self.buscar(True))
        self.btn_barato.grid(row=0, column=1, padx=4)

        self.btn_limpiar = ctk.CTkButton(bfrm, text="🗑️ Limpiar Historial", width=140, height=46,
                                          font=("Consolas", 11),
                                          fg_color="#444444", hover_color="#666666",
                                          command=self.limpiar_db)
        self.btn_limpiar.grid(row=0, column=2, padx=4)
        
        self.btn_entrenar = ctk.CTkButton(bfrm, text="🏋️ Autoentreno", width=140, height=46,
                                           font=("Consolas", 11),
                                           fg_color="#D35400", hover_color="#E67E22",
                                           command=self.start_training)
        self.btn_entrenar.grid(row=1, column=2, padx=4, pady=5)

        self.btn_evolucionar = ctk.CTkButton(bfrm, text="🚀 Iniciar Evolución", width=140, height=46,
                                           font=("Consolas", 11, "bold"),
                                           fg_color="#8E44AD", hover_color="#9B59B6",
                                           command=self.start_evolution)
        self.btn_evolucionar.grid(row=1, column=0, padx=4, pady=5)

        self.btn_stop_ev = ctk.CTkButton(bfrm, text="⏹ Detener Evo", width=130, height=46,
                                          font=("Consolas", 11),
                                          fg_color="#7B241C", hover_color="#922B21",
                                          state="disabled",
                                          command=self.stop_evolution)
        self.btn_stop_ev.grid(row=1, column=3, padx=4, pady=5)

        self.btn_pausa = ctk.CTkButton(bfrm, text="⏸ Pausar", width=100, height=46,
                                           font=("Consolas", 11, "bold"),
                                           fg_color="#D4AC0D", hover_color="#F1C40F",
                                           command=self.toggle_pause)
        self.btn_pausa.grid(row=1, column=1, padx=4, pady=5)

        self.btn_apagar = ctk.CTkButton(bfrm, text="🔴 APAGAR", width=100, height=46,
                                           font=("Consolas", 11, "bold"),
                                           fg_color="#7B241C", hover_color="#922B21",
                                           command=self.shutdown_total)
        self.btn_apagar.grid(row=1, column=2, padx=4, pady=5)




        self.var_autoaprendizaje = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(frm, text="🚀 Autoaprendizaje Activo", variable=self.var_autoaprendizaje,
                        font=("Consolas", 11)).grid(row=2, column=0, columnspan=2, pady=5, sticky="w")




        # Área de Resultados (Cards)
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="nsew")

        # Barra de estado
        self.lbl_status = ctk.CTkLabel(self, text="Sistema listo.", font=("Consolas", 11), anchor="w")
        self.lbl_status.grid(row=3, column=0, padx=20, pady=(0, 2), sticky="ew")

        # Consola (Minimizada)
        self.consola = ctk.CTkTextbox(self, font=("Consolas", 11), state="disabled", height=80)
        self.consola.grid(row=4, column=0, padx=20, pady=(0, 10), sticky="ew")

        sys.stdout = RedirigirConsola(self.consola)

    def limpiar_db(self):
        try:
            DB.borrar_historial()
            print("[*] Base de datos de precios limpiada.")
        except Exception as e:
            print(f"[!] Error al limpiar DB: {e}")


    def add_card(self, dato, ranking=None):
        card = ResultCard(self.scroll, dato, ranking=ranking)
        card.pack(fill="x", padx=5, pady=5)

    def buscar(self, modo_barato: bool):
        q = self.entrada.get().strip()
        if not q: return
        
        # Limpiar resultados anteriores
        for widget in self.scroll.winfo_children():
            widget.destroy()

        self.btn_buscar.configure(state="disabled", text="⏳ Buscando...")
        self.btn_barato.configure(state="disabled")

        def run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            def callback_ui(dato):
                # Usar after para actualizar UI desde hilo
                print(f"[*] UI: Añadiendo card para {dato.get('url')}")
                self.after(0, lambda d=dato: self.add_card(d))

            try:
                auto_ap = self.var_autoaprendizaje.get()
                loop.run_until_complete(orquestador(q, modo_barato, callback_ui, auto_ap))

            except Exception as e:
                print(f"\n[!] Error en búsqueda: {e}")
            finally:
                loop.close()
                self.after(0, self.finalizar_busqueda)


        threading.Thread(target=run, daemon=True).start()

    def finalizar_busqueda(self):
        self.btn_buscar.configure(state="normal", text="🔍 Buscar")
        self.btn_barato.configure(state="normal")
        
        # Si no hay cards en el scroll, mostrar mensaje
        if not self.scroll.winfo_children():
            lbl = ctk.CTkLabel(self.scroll, text="❌ No se encontraron resultados válidos.\nPrueba con términos más generales.", 
                               font=("Arial", 14), pady=20)
            lbl.pack(expand=True)
            
        print("\n[*] Búsqueda finalizada.")

    def start_training(self):
        self.btn_entrenar.configure(state="disabled", text="🏋️ Entrenando...")
        threading.Thread(target=self.training_loop, daemon=True).start()

    def training_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Generar queries de entrenamiento
        queries = loop.run_until_complete(generar_queries_entrenamiento())
        for q in queries:
            print(f"\n[🏋️] ENTRENAMIENTO AUTÓNOMO: Buscando '{q}'...")
            self.after(0, lambda: self.lbl_status.configure(text=f"Entrenando con: {q}"))
            
            def callback_vacia(d): pass
            
            try:
                # El orquestador ya guarda lecciones si auto_aprendizaje=True
                loop.run_until_complete(orquestador(q, True, callback_vacia, True))
            except Exception as e:
                print(f"[!] Error entrenamiento: {e}")
            
            time.sleep(3) # Respiro para el CPU
            
        self.after(0, lambda: self.btn_entrenar.configure(state="normal", text="🏋️ Autoentreno"))
        self.after(0, lambda: self.lbl_status.configure(text="Entrenamiento completado. El sistema es ahora más sabio."))

    def toggle_pause(self):
        self.is_paused = not self.is_paused
        txt = "▶ Reanudar" if self.is_paused else "⏸ Pausar"
        self.btn_pausa.configure(text=txt)
        if self.is_paused:
            self.lbl_status.configure(text="SISTEMA PAUSADO. Evolución en espera.")
        else:
            self.lbl_status.configure(text="SISTEMA REANUDADO.")

    def shutdown_total(self):
        print("\n[APAGADO] Iniciado por el usuario...")
        self.stop_ev_flag = True
        self.after(300, self._do_shutdown)

    def _do_shutdown(self):
        try:
            self.destroy()
        except Exception:
            pass
        sys.exit(0)

    def stop_evolution(self):
        self.stop_ev_flag = True
        self.btn_stop_ev.configure(state="disabled")

    def start_evolution(self):
        self.stop_ev_flag = False
        self.is_paused = False
        self.btn_evolucionar.configure(state="disabled", text="🚀 Evolucionando...")
        self.btn_stop_ev.configure(state="normal")
        threading.Thread(target=self.evolution_loop, daemon=True).start()

    async def medir_eficiencia(self, func, *args):

        """Mide el tiempo real de ejecución de una función en ms."""
        inicio = time.perf_counter()
        await func(*args)
        fin = time.perf_counter()
        return (fin - inicio) * 1000

    def evolution_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Función objetivo para optimizar (Real)
        def target_func(data):
            return json.loads(re.sub(r'```json|```', '', data).strip())

        while not self._stop_ev.is_set():
            # Control de Pausa: espera eficiente sin busy-loop
            while self._pause_ev.is_set():
                if self._stop_ev.wait(timeout=1.0):
                    break

            if self._stop_ev.is_set():
                break
            
            self.after(0, lambda: self.lbl_status.configure(text="Evolucionando: Realizando Benchmark Real..."))

            
            test_data = '```json {"test": "data", "val": 123} ```'
            
            # 1. Medición de la función actual
            inicio = time.perf_counter()
            for _ in range(1000): target_func(test_data)
            t_base = (time.perf_counter() - inicio) * 1000
            
            print(f"\n[🚀] BENCHMARK ORIGINAL: {t_base:.4f}ms")
            
            if self.stop_ev_flag: break
            
            # 2. IA intentando mejorar el DISEÑO (Mutación Visual)
            self.after(0, lambda: self.lbl_status.configure(text="Evolucionando: Mutando interfaz (ADN Visual)..."))
            
            prompt_ui = f"""
            Genera un JSON de estilos mejorado para una app premium. 
            Colores actuales: {json.dumps(self.styles)}
            Responde SOLO el JSON con: bg_color, card_color, text_color, accent_color, accent_hover, button_radius.
            Usa colores elegantes (Deep Blues, Graphite, Neon accents).
            """
            try:
                r = loop.run_until_complete(asyncio.wait_for(
                    AsyncClient(host=OLLAMA_HOST).chat(
                        model=MODELO_OLLAMA,
                        messages=[{"role": "user", "content": prompt_ui}],
                        format="json",
                        options={"timeout": 30},
                    ),
                    timeout=35.0,
                ))
                raw_estilo = json.loads(limpiar_json(r["message"]["content"]))
                if not isinstance(raw_estilo, dict):
                    raise ValueError("LLM no devolvió un dict para styles")
                nuevo_estilo = validate_styles_json(raw_estilo)
                _styles_path = pathlib.Path(__file__).parent / "styles.json"
                with open(_styles_path, "w", encoding="utf-8") as f:
                    json.dump(nuevo_estilo, f, indent=4)
                self.styles = nuevo_estilo
                
                # APLICAR CAMBIO EN CALIENTE
                self.after(0, self.apply_dynamic_styles)
                print("    [✓] MUTACIÓN COMPLETADA: La interfaz ha evolucionado.")
            except Exception as e:
                print(f"    [X] Error en mutación: {e}")

            time.sleep(15) 
            
        self.after(0, lambda: self.btn_evolucionar.configure(state="normal", text="🚀 Iniciar Evolución"))
        self.after(0, lambda: self.btn_stop_ev.configure(state="disabled"))



if __name__ == "__main__":


    App().mainloop()