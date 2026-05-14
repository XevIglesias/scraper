# SKILL: Bucle de Evolución Total

Cuando el usuario diga "ejecuta la skill de evolución" o "/evolve", sigue EXACTAMENTE estas fases en orden de forma autónoma. Usa `git commit` antes de cada cambio destructivo. Si algo falla, revierta con `git restore` o `git reset --hard HEAD~1`.

---

## FASE 0: Gestión de Tokens (SIEMPRE antes de empezar)

Antes de hacer CUALQUIER cosa, evalúa el contexto disponible:

1. **Estima el tamaño de la sesión**: lee solo los archivos que vas a tocar (no todos). Máximo 3-4 archivos por sesión.
2. **Prioriza por impacto**: si el contexto es limitado, haz UNA mejora grande en vez de cinco pequeñas.
3. **Compacta antes de la Fase 3**: antes de leer código de parsers/motores, usa `/compact` para liberar contexto.
4. **Regla de oro**: si llevas más de 15 mensajes en la conversación, crea `CHECKPOINT.md` con el estado actual y pide al usuario que abra una conversación nueva pegando ese checkpoint.

### Plantilla de CHECKPOINT.md
```
# Checkpoint de sesión
Fecha: [fecha]
Fase completada: [0/1/2/3]
Archivos modificados: [lista]
Próximo paso: [descripción exacta]
Git hash actual: [git rev-parse HEAD]
```

---

## FASE 1: Innovador — Mercado y Planificación

**Objetivo**: encontrar 3 mejoras concretas a implementar.

1. Escribe y ejecuta este script temporal (bórralo después):
```python
# tmp_research.py
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

queries = [
    "python ecommerce scraper best practices 2025",
    "tkinter customtkinter UI modern design patterns",
    "price comparison app features 2025"
]
with DDGS() as d:
    for q in queries:
        results = list(d.text(q, max_results=2))
        for r in results:
            print(r.get("title",""), "|", r.get("href",""))
```

2. Lee `ESTADO_PROYECTO.md` (sección de ideas pendientes).
3. Elige **3 mejoras** ordenadas por impacto/esfuerzo. Escríbelas en `ESTADO_PROYECTO.md` bajo `## Ideas FASE 1 [fecha]`.
4. Borra `tmp_research.py`.
5. `git add ESTADO_PROYECTO.md && git commit -m "Fase 1: 3 ideas identificadas"`

---

## FASE 2: Diseñador UI — Frontend

**Objetivo**: aplicar UNA mejora visual concreta y verificarla.

1. Lee `replicator/ui/interface.py` y `styles.json`.
2. Elige la mejora visual de mayor impacto de las 3 ideas de Fase 1.
3. Aplica el cambio. Haz commit ANTES de mostrárselo al usuario:
   ```
   git add -p   # solo los archivos de UI
   git commit -m "UI: [descripción del cambio]"
   ```
4. Lanza la UI: `python replicator/main.py` (o `python buscador_app.py`).
5. Pregunta al usuario: "¿Se ve bien? (sí/no/ajustar)"
   - Si "no": `git reset --hard HEAD~1` y vuelve al paso 2 con otra idea.
   - Si "sí": continúa a Fase 3.

---

## FASE 3: Optimizador Backend — Código y Tests

**Objetivo**: mejorar un parser o motor y verificarlo con métricas reales.

### Preparación (solo una vez)
Si no existe `test_fitness.py`, créalo:
```python
# test_fitness.py — mide el fitness real del buscador desde precios.db
import sys
sys.path.insert(0, ".")
from replicator.core.scraper_fitness import ScraperFitness

f = ScraperFitness()
data = f.compute()
print(f"FITNESS: {data['fitness']}/100")
print(f"  Exito busquedas:   {data['tasa_exito']}%")
print(f"  Fiab. tiendas:     {data['tasa_confianza_tiendas']}%")
print(f"  Sin errores:       {data['tasa_sin_errores']}%")
# Salir con codigo 1 si fitness < 50 (para CI)
sys.exit(0 if data["fitness"] >= 50 else 1)
```

### Bucle de mejora
1. Mide fitness base: `python test_fitness.py` → guarda el número.
2. Lee el parser/motor con peor fitness (usa `replicator/agents/scout.py` como referencia para saber cuál).
3. Identifica UNA función concreta a mejorar (máx 80 líneas).
4. Aplica el cambio con tu criterio completo (no un LLM local de 7B — TÚ eres el LLM).
5. `python test_fitness.py` de nuevo.
   - **Sube o igual + sin errores de sintaxis**: `git commit -m "Backend: [archivo] [función] +X%"`
   - **Baja o SyntaxError**: `git restore [archivo]` y documenta por qué en `ESTADO_PROYECTO.md`.
6. Máximo 3 intentos por función. Si falla 3 veces, pasa a la siguiente.

---

## Reglas de seguridad absoluta

- **NUNCA** toques: `replicator/core/security.py`, `replicator/agents/guardian.py`, `.env`
- **NUNCA** hagas `git push --force` sin confirmación explícita del usuario
- **SIEMPRE** haz `git diff` antes de un commit para verificar qué cambió
- Si el buscador deja de arrancar: `git reset --hard HEAD~1` inmediatamente
- Si el usuario dice "esto ha quedado fatal": `git reset --hard` sin preguntar

---

## Comandos de referencia rápida

```bash
# Ver qué cambió
git diff
git log --oneline -5

# Revertir último commit (pero mantener cambios en disco)
git reset HEAD~1

# Revertir último commit Y descartar cambios
git reset --hard HEAD~1

# Volver al commit base original
git reset --hard b06d80f

# Ver el fitness del buscador
python test_fitness.py

# Lanzar el buscador
python buscador_app.py

# Lanzar replicator manual
python replicator/night_runner.py --cycles 2 --delta 3
```
