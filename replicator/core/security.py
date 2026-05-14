import asyncio
import re
import ipaddress
from urllib.parse import urlparse

# ─── Aegis Shield (Browser Route Interception) ────────────────────────────────

_BLOCKED_SSRF_SUBSTRINGS = (
    "127.0.0.1", "localhost", "0.0.0.0", "::1", "[::1]",
    "192.168.", "10.0.", "10.1.", "172.16.", "172.17.", "172.18.",
    "172.19.", "172.2", "172.3",
)
_BLOCKED_SCHEMES_BROWSER = ("data:", "file://", "javascript:", "blob:", "vbscript:")


class AegisShield:
    @staticmethod
    async def interceptar_recursos(route):
        url_req = route.request.url.lower()
        tipo = route.request.resource_type

        # Bloqueo de red local + IPv6 loopback + schemes peligrosos
        if (any(x in url_req for x in _BLOCKED_SSRF_SUBSTRINGS) or
                any(url_req.startswith(s) for s in _BLOCKED_SCHEMES_BROWSER)):
            await route.abort()
            return

        # Bloqueo de archivos peligrosos
        if any(url_req.endswith(ext) for ext in [".exe", ".zip", ".rar", ".bat", ".sh"]):
            await route.abort()
            return

        # Filtro de rastreo
        if tipo in ["websocket", "manifest", "font"]:
            await route.abort()
            return

        await route.continue_()

    @staticmethod
    async def apply_js_protections(ctx):
        # Desactiva eval, Function constructor y ServiceWorker
        # setTimeout/setInterval con string también se bloquean
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


# ─── CSS Selector Sanitizer ───────────────────────────────────────────────────

# Allowlist: solo caracteres válidos en selectores CSS reales
_CSS_SAFE_RE = re.compile(r'^[a-zA-Z0-9_\-\.\[\]#:=\'"^$*|~>+\s,()\d]+$')


def sanitize_css_selector(sel: str) -> str | None:
    """
    Devuelve el selector si pasa la allowlist de caracteres CSS válidos.
    Devuelve None si contiene caracteres peligrosos (bloquea inyección JS).
    Nunca pasar None a page.evaluate().
    """
    if not sel or not isinstance(sel, str):
        return None
    if len(sel) > 256:
        return None
    if _CSS_SAFE_RE.match(sel):
        return sel
    return None


# ─── URL Validator (SSRF + malicious schemes) ─────────────────────────────────

_BLOCKED_SCHEMES = {"file", "data", "javascript", "ftp", "blob", "vbscript", "mailto"}
_BLOCKED_HOSTS = {
    "localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]", "0x7f000001",
}
_PRIVATE_PREFIXES = (
    "192.168.", "10.", "172.16.", "172.17.", "172.18.",
    "172.19.", "172.2", "172.3",
)


def validate_url(url: str, allow_local: bool = False) -> str | None:
    """
    Devuelve la URL si es segura para abrir (http/https, no IPs privadas).
    Devuelve None si está bloqueada (SSRF, scheme malicioso, IP privada/loopback).
    """
    if not url or not isinstance(url, str):
        return None
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    scheme = parsed.scheme.lower()
    if scheme in _BLOCKED_SCHEMES:
        return None
    if scheme not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    if not allow_local:
        if host in _BLOCKED_HOSTS:
            return None
        if any(host.startswith(p) for p in _PRIVATE_PREFIXES):
            return None
        # Verificar IPs IPv4/IPv6 privadas o loopback
        try:
            addr = ipaddress.ip_address(host)
            if addr.is_loopback or addr.is_private or addr.is_link_local:
                return None
        except ValueError:
            pass  # Es un hostname, no una IP — correcto
    return url


# ─── Styles JSON Schema Validator ─────────────────────────────────────────────

_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
_STYLES_DEFAULTS = {
    "bg_color": "#1a1a1a",
    "card_color": "#2d2d2d",
    "text_color": "#ffffff",
    "accent_color": "#8E44AD",
    "accent_hover": "#9B59B6",
    "button_radius": 8,
    "font_family": "Consolas",
    "title_size": 24,
}


def validate_styles_json(data: dict) -> dict:
    """
    Valida un dict de estilos generado por LLM.
    Devuelve un dict seguro, usando defaults para campos inválidos.
    """
    result = {}
    for key, default in _STYLES_DEFAULTS.items():
        val = data.get(key, default)
        if key == "button_radius":
            try:
                result[key] = max(0, min(50, int(val)))
            except (TypeError, ValueError):
                result[key] = default
        elif key == "title_size":
            try:
                result[key] = max(8, min(72, int(val)))
            except (TypeError, ValueError):
                result[key] = default
        elif key == "font_family":
            # Solo letras, espacios y guiones
            if isinstance(val, str) and re.match(r'^[a-zA-Z\s\-]+$', val) and len(val) <= 64:
                result[key] = val
            else:
                result[key] = default
        else:
            # Campo de color: debe ser #RRGGBB
            if isinstance(val, str) and _COLOR_RE.match(val):
                result[key] = val
            else:
                result[key] = default
    return result


# ─── LLM JSON Response Validator ─────────────────────────────────────────────

def validate_llm_json(raw: dict, required_keys: dict) -> bool:
    """
    Valida que un dict devuelto por el LLM contenga los campos requeridos con tipos correctos.
    required_keys: {nombre_campo: tipo_esperado}  ej. {"es_producto_correcto": bool, "precio_eur": float}
    Devuelve True si es válido, False si falta algún campo o tiene tipo incorrecto.
    """
    if not isinstance(raw, dict):
        return False
    for key, expected_type in required_keys.items():
        if key not in raw:
            return False
        # Permitir int donde se espera float
        if expected_type is float and isinstance(raw[key], int):
            continue
        if not isinstance(raw[key], expected_type):
            return False
    return True
