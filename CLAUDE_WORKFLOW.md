# SKILL: Bucle de Evolución Total — Fundamentos + Vanguardia

## Filosofía de evolución (leer siempre)

Hay dos modos que se aplican en orden estricto:

**Modo Cimientos** (hasta fitness 80/100):
Antes de innovar, la base tiene que ser sólida. Esto significa parsers que no se rompen,
tests que verifican cada cambio, UI que no tiene bugs visuales, código modular.
Sin cimientos, cualquier innovación se derrumba.

**Modo Vanguardia** (fitness > 80/100):
Una vez sólida la base, ser pionero. Esto significa:
- Ingeniería inversa de los mejores scrapers open source (Scrapy, Playwright-stealth, price-tracker repos en GitHub)
- Buscar qué hacen los líderes del sector (Idealo, CamelCamelCamel, Keepa) y replicar lo mejor
- Proponer mejoras que no existen todavía: parsing semántico con LLM como fallback, detección automática de cambios de DOM, alertas predictivas de precio

**Retroalimentación tipo Deep Learning**:
Cada sesión termina con una medición de fitness. La siguiente sesión lee ese resultado
y ajusta la estrategia — igual que gradient descent. Lo que funcionó: más de eso.
Lo que falló 2 veces: descartar y probar otro enfoque. Nunca repetir un error.

---

## FASE 0: Gestión de Tokens (SIEMPRE antes de empezar)

1. Lee solo los archivos que vas a tocar en esta sesión (máximo 4).
2. Ejecuta `python test_fitness.py` para tener la línea base.
3. Lee `ESTADO_PROYECTO.md` — sección "Próxima sesión" si existe.
4. Si llevas más de 20 mensajes en la conversación, crea `CHECKPOINT.md` y pide nueva sesión.
5. Usa `/compact` antes de la Fase 3 si el contexto está cargado.

### CHECKPOINT.md (plantilla)
```
# Checkpoint
Fecha: [fecha]
Fitness antes: [X]/100  |  Fitness después: [Y]/100
Fases completadas: [lista]
Archivos modificados: [lista con git hash]
Próximo objetivo: [descripción exacta de qué hacer]
Git hash: [git rev-parse HEAD]
```

---

## FASE 1: Investigador — Mercado, Competencia e Ingeniería Inversa

**Objetivo**: entender qué existe, qué falta, qué es posible hacer mejor.

### 1a. Buscar tendencias y competencia
Escribe y ejecuta este script (bórralo después):
```python
# tmp_research.py
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

queries = [
    "best price comparison scraper python 2025 github",
    "playwright anti-detection scraper techniques 2025",
    "price tracker app features idealo keepa camelcamelcamel",
    "customtkinter modern UI examples dark mode 2025",
    "python scraper dom change detection resilient parser"
]
with DDGS() as d:
    for q in queries:
        print(f"\n=== {q} ===")
        for r in d.text(q, max_results=2):
            print(" -", r.get("title",""), "|", r.get("href",""))
```

### 1b. Analizar competencia real
- Busca en GitHub: `scrapy price scraper`, `playwright price tracker`, `customtkinter app`
- Identifica: ¿qué tienen que nosotros no tenemos? ¿qué hacemos mejor?

### 1c. DAFO actualizado
Escribe en `ESTADO_PROYECTO.md` bajo `## DAFO [fecha]`:
- Fortalezas actuales del buscador
- Debilidades concretas (con archivo y línea)
- Oportunidades (features que la competencia tiene y nosotros no)
- Amenazas (anti-bot, cambios de DOM, mantenimiento de parsers)

### 1d. Plan de 3 mejoras priorizadas
Escribe en `ESTADO_PROYECTO.md` bajo `## Plan Sesión [fecha]`:
- Mejora 1: [impacto alto, esfuerzo bajo] → Fase 2 o 3
- Mejora 2: [impacto alto, esfuerzo medio]
- Mejora 3: [innovación / vanguardia]

Commit: `git add ESTADO_PROYECTO.md && git commit -m "Fase 1: investigacion y plan"`

---

## FASE 2: Diseñador UI — Frontend Real

**Objetivo**: UI que compita visualmente con apps comerciales.

### Qué mirar para inspiración
- CamelCamelCamel: historial de precios con gráfico
- Idealo: cards de producto con badge "mínimo histórico"
- Keepa: alertas visuales, sparklines de precio

### Lo que puedo mejorar en CustomTkinter
- Tema oscuro OLED real (fondo #0a0a0a, no el gris por defecto)
- Cards de resultado con sombra, precio grande, badge de ahorro
- Barra de progreso animada durante la búsqueda (no spinner estático)
- Historial de precios inline (matplotlib embed o canvas simple)
- Layout responsive: si hay 1 resultado → tarjeta grande; si hay 5 → grid

### Protocolo
1. Lee `buscador_app.py` (solo la parte de UI — clase `App` y `add_card`)
2. Lee `styles.json`
3. Aplica el cambio más impactante visualmente
4. Commit antes de mostrar: `git commit -m "UI: [descripción]"`
5. Muestra al usuario y pregunta. Si "no" → `git reset --hard HEAD~1`

---

## FASE 3: Optimizador Backend — Parsers y Motor

**Objetivo**: subir la tasa de éxito de búsquedas del 50% al 80%+.

### Análisis de debilidades conocidas
- `analizar_url` en buscador_app.py es monolítica (1471 líneas en un solo archivo)
- Parsers con selectores hardcoded que rompen al cambiar el DOM
- Sin fallback semántico cuando los selectores fallan
- Motor cascada sin retry inteligente

### Mejoras por orden de impacto

**Cimientos (hacer primero):**
1. Separar `buscador_app.py` en `ui/`, `core/`, `utils/` — sin cambiar funcionalidad
2. Añadir selector fallback en cada parser: si el selector A falla, intentar B, luego C, luego regex
3. Tests con HTML guardado localmente (no hace requests reales)

**Vanguardia (cuando cimientos estén sólidos):**
1. Detección automática de cambios de DOM: si el selector falla 3 veces consecutivas, usar LLM para re-detectar el selector correcto desde el HTML
2. Playwright-stealth: rotar user-agents, delays aleatorios, fingerprint humano
3. Parser semántico: extraer precio con regex + LLM como último recurso (ya tienes Ollama)
4. Cache inteligente: no re-scrappear si el precio de esa tienda fue actualizado hace < 30 min

### Protocolo
1. `python test_fitness.py` → anota el número base
2. Aplica la mejora
3. `python test_fitness.py` de nuevo
   - Sube: `git commit -m "Backend: [archivo] [mejora] +X%"`
   - Baja: `git restore [archivo]` + documenta en ESTADO_PROYECTO.md
4. Máximo 3 intentos por función. Si falla 3 veces → siguiente.

---

## FASE 4: Retroalimentación — Cerrar el Bucle

Al final de cada sesión completa:

1. Ejecuta `python test_fitness.py` → fitness final
2. Escribe en `ESTADO_PROYECTO.md` bajo `## Sesión [fecha]`:
   ```
   Fitness: [antes] → [después]  (+X puntos)
   Aplicado: [lista de cambios]
   Fallido: [qué no funcionó y por qué]
   Próxima sesión: [objetivo concreto basado en lo aprendido]
   Modelo mental actualizado: [qué aprendí sobre esta app que antes no sabía]
   ```
3. Commit final: `git commit -m "Sesión [fecha]: fitness [antes]->[después]"`

Este log ES el sistema de retroalimentación. Cada sesión nueva empieza leyendo
la sección anterior y ajustando la estrategia — como leer el gradiente antes de
actualizar los pesos.

---

## Reglas de seguridad absoluta

- **NUNCA** toques: `replicator/core/security.py`, `replicator/agents/guardian.py`, `.env`
- **NUNCA** `git push --force` sin confirmación explícita
- **SIEMPRE** `git diff` antes de cualquier commit
- Si el buscador deja de arrancar: `git reset --hard HEAD~1` inmediatamente
- Si el usuario dice "esto ha quedado fatal": `git reset --hard` sin preguntar

---

## Comandos rápidos

```bash
python test_fitness.py              # medir fitness actual
python buscador_app.py              # lanzar buscador
python replicator/night_runner.py --cycles 2 --delta 3  # replicator local

git diff                            # ver cambios pendientes
git log --oneline -8                # historial reciente
git reset --hard HEAD~1             # deshacer último commit
git reset --hard b06d80f            # volver al estado base original
```
