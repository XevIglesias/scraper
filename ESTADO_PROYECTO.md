# ESTADO DEL PROYECTO — REPLICATOR V3
**Fecha:** 2026-05-14  
**Sesión anterior terminó al 62% del contexto (124k/200k tokens)**

---

## 1. ARQUITECTURA ACTUAL

```
C:\Users\xevi2\Desktop\scraper\
├── buscador_app.py          ← App principal (GUI + búsqueda + Ollama)
├── config.py                ← Constantes globales
├── db.py                    ← SQLite para precios (AUDITADO + thread-safe)
├── styles.json              ← Tema visual de la UI
├── .env                     ← Credenciales SMTP (ROTAR PASSWORD YA)
├── .env.example             ← Plantilla segura (NUEVO)
├── .gitignore               ← Excluye .env, *.db (NUEVO)
│
├── motores/
│   ├── motor_cascada.py     ← Orquesta DDGS → Bing → Fallback
│   ├── motor_bing.py        ← Scraper HTML de Bing
│   └── motor_fallback.py    ← URLs hardcoded por categoría
│
├── parsers/
│   ├── base.py              ← TiendaParser (abstracto)
│   ├── farmacia.py          ← Promofarma, Dosfarma, Atida, etc.
│   ├── suplementos.py       ← Nutritienda, Bulevip, HSN, etc.
│   ├── electronica.py       ← PcComponentes, MediaMarkt (1 clase, NO duplicada), Fnac, Amazon
│   └── generalista.py      ← Carrefour, El Corte Inglés
│
└── replicator/
    ├── main.py              ← Entry point del sistema multi-agente
    ├── core/
    │   ├── governor.py      ← Monitor de RAM (límite 13.5GB)
    │   ├── orchestrator.py  ← Ciclo de evolución (PENDIENTE actualizar con EvolutionEngine)
    │   ├── alerts.py        ← SMTP seguro (AUDITADO)
    │   ├── security.py      ← AegisShield + 4 helpers (AUDITADO, AMPLIADO)
    │   ├── db_manager.py    ← ReplicatorDB con tablas generations + metrics_history (NUEVO)
    │   ├── version_control.py ← Snapshots de .py sin git (NUEVO - COMPLETO)
    │   └── metrics.py       ← MetricsTracker AST (NUEVO - COMPLETO)
    │
    ├── agents/
    │   ├── base_agent.py    ← BaseAgent abstracto
    │   ├── guardian.py      ← AST scanner + LLM (AUDITADO, AST-based)
    │   ├── optimizer.py     ← Sin exec(), path traversal guard (AUDITADO)
    │   ├── innovator.py     ← DDGS research (funcional pero básico)
    │   ├── designer.py      ← Stub (propone estilos)
    │   ├── architect.py     ← Stub (estructura)
    │   └── scout.py         ← PENDIENTE CREAR (sesión siguiente)
    │
    ├── snapshots/           ← Directorio creado, vacío (snapshots van aquí)
    └── ui/
        ├── interface.py     ← GUI CustomTkinter (PENDIENTE actualizar)
        └── approval_panel.py ← PENDIENTE CREAR (sesión siguiente)
```

---

## 2. HITOS COMPLETADOS (100%)

### Auditoría de seguridad completa
- [x] `.gitignore` + `.env.example` creados
- [x] `db.py` — threading.Lock, SQL LIKE ESCAPE, urlparse
- [x] `replicator/core/security.py` — 4 helpers: `sanitize_css_selector`, `validate_url`, `validate_styles_json`, `validate_llm_json`
- [x] `guardian.py` — reescrito con AST scanner real (no bypasseable)
- [x] `optimizer.py` — exec() eliminado, path traversal guard
- [x] `buscador_app.py` — 14 fixes: CSS injection, SSRF+IPv6, webbrowser.open seguro, threading.Event, lbl_status, btn_stop_ev, os._exit→sys.exit, price regex €99k
- [x] `alerts.py` — excepciones SMTP no filtran credenciales

### Bucle evolutivo — módulos base
- [x] `replicator/core/version_control.py` — Sistema de snapshots completo (snapshot, rollback, apply_patch, cleanup_old)
- [x] `replicator/core/metrics.py` — MetricsTracker con LOC, complejidad ciclomática, nesting depth, fitness score
- [x] `replicator/core/db_manager.py` — Tablas `generations` + `metrics_history` + métodos store/get

---

## 3. TRABAJO EN CURSO (sesión siguiente)

### Archivos PENDIENTES de crear (en orden):
1. **`replicator/agents/scout.py`** — ScoutAgent: analiza métricas + DDGS + LLM → devuelve `list[ImprovementOpportunity]`
2. **`replicator/agents/tester.py`** — TesterAgent: genera pytest con LLM + los ejecuta en `replicator/tmp/` con timeout
3. **`replicator/agents/benchmark.py`** — BenchmarkAgent: análisis AST estático de propuesta + `compute_delta()`
4. **`replicator/core/evolution_engine.py`** — El bucle principal: Scout→Optimizer→Guardian→Tester→Benchmark→ApprovalPanel
5. **`replicator/ui/approval_panel.py`** — Panel modal CustomTkinter: diff coloreado + test results + benchmark delta + botones Aprobar/Rechazar/Diferir
6. **`replicator/core/orchestrator.py`** — Actualizar para usar `EvolutionEngine.run_cycle()`
7. **`replicator/ui/interface.py`** — Añadir historial de generaciones y callback de aprobación

### Dataclasses que scout.py necesita definir:
```python
@dataclass
class ImprovementOpportunity:
    target_file: str       # ej: "buscador_app.py"
    func_name: str         # ej: "extraer_precio_regex"
    priority: int          # 1-5
    rationale: str
    metric_current: float  # fitness score actual

@dataclass
class TestResult:
    passed: int; failed: int; errors: int; output: str
    @property
    def all_pass(self): return self.failed == 0 and self.errors == 0

@dataclass
class BenchmarkResult:
    is_improvement: bool; delta_pct: float
    fitness_before: float; fitness_after: float; details: dict
```

---

## 4. BUGS / PENDIENTES CONOCIDOS

### ⚠️ ACCIÓN MANUAL URGENTE
- **Rotar el Gmail app password** `qdmp bwwx vcqn umog` en Google Account → Security → App passwords
- Actualizar `.env` con el nuevo password

### Técnicos
- `replicator/ui/interface.py` — el método `apply_dynamic_styles()` contiene el código de construcción de la UI (mezcla construcción + estilos). No se rompe nada pero es un code smell. Se puede refactorizar opcionalmente.
- `replicator/agents/designer.py` y `architect.py` — son stubs con lógica hardcodeada. Se pueden implementar en una iteración futura.
- `replicator/logic/search_engine.py` — tiene un `analizar_url` que duplica parte de `buscador_app.py`. Candidato a refactor.

---

## 5. CÓMO ABRIR LA SIGUIENTE SESIÓN

### Carpeta a abrir en Claude Code:
```
C:\Users\xevi2\Desktop\scraper\replicator\
```
**Solo esa subcarpeta**, no todo el proyecto.

### Archivos a adjuntar en el primer mensaje:
1. Este archivo `ESTADO_PROYECTO.md`
2. `replicator/core/version_control.py` (para contexto de cómo funciona el patrón)
3. `replicator/core/metrics.py` (para contexto de las métricas)
4. `replicator/core/db_manager.py` (para contexto del esquema de DB)
5. `replicator/agents/base_agent.py` (la interfaz de los agentes)

### Prompt exacto para abrir la sesión:
```
Soy el dueño de REPLICATOR V3. Lee ESTADO_PROYECTO.md primero.
Necesito que implementes, en orden, estos 3 archivos nuevos:
1. replicator/agents/scout.py
2. replicator/agents/tester.py  
3. replicator/agents/benchmark.py

Luego, cuando esos 3 estén listos:
4. replicator/core/evolution_engine.py
5. replicator/ui/approval_panel.py

Usa Ollama local (llama3). Sin git. Los snapshots ya existen en version_control.py.
Los dataclasses ImprovementOpportunity, TestResult y BenchmarkResult los definimos
en los propios módulos donde se usan.
```

---

## 6. DEPENDENCIAS DEL PROYECTO

```
playwright       ← scraping web
ollama           ← LLM local (llama3)
duckduckgo-search ← DDGS para Scout/Innovator
customtkinter    ← GUI
psutil           ← monitor RAM (Governor)
python-dotenv    ← cargar .env
```

No se añadió ninguna dependencia nueva en la auditoría (todo con stdlib).
Para el bucle evolutivo tampoco se añaden: pytest ya está disponible si está instalado.

---

## 7. ARQUITECTURA DEL BUCLE EVOLUTIVO (para la próxima sesión)

```
EvolutionEngine.run_cycle()
    │
    ├─ ScoutAgent.think(context)
    │    ├─ MetricsTracker.measure_file(cada .py del proyecto)
    │    ├─ DDGS.text("python scraper optimization 2025")
    │    ├─ Ollama: "¿Qué función tiene más deuda técnica?"
    │    └─ → list[ImprovementOpportunity]
    │
    ├─ [Para cada oportunidad, max 3 por ciclo]
    │    │
    │    ├─ VersionControl.snapshot(label)       ← BACKUP
    │    ├─ OptimizerAgent.think(file, func)      ← propone código
    │    ├─ GuardianAgent.validate_code(code)     ← AST + LLM
    │    ├─ TesterAgent.generate_tests(code)      ← genera pytest
    │    ├─ TesterAgent.run_tests(tests)          ← ejecuta en tmp/
    │    ├─ BenchmarkAgent.compare(before, after) ← delta fitness
    │    │
    │    └─ Si mejora → ApprovalPanel.show()
    │         ├─ Usuario aprueba → VersionControl.apply_patch()
    │         └─ Usuario rechaza → VersionControl.rollback()
    │
    └─ DB.store_generation(resultado)
```
