"""
ScoutAgent: analiza métricas del proyecto + errores históricos de DB + DDGS + LLM.
Los parsers/dominios con más errores en memoria_errores tienen prioridad alta.
Nunca ejecuta código generado por LLM.
"""
import json
import pathlib
from collections import Counter
from dataclasses import dataclass
from ollama import AsyncClient
from agents.base_agent import BaseAgent
from core.metrics import MetricsTracker
from core.llm_config import MODEL

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_EXCLUDE_DIRS = {"__pycache__", "snapshots", ".venv", "venv", "env", "dist", "build", "tmp"}
_MAX_OPPORTUNITIES = 3

# Archivos que NUNCA se proponen como objetivo de mejora
# REPLICATOR no debe tocarse a si mismo — solo evoluciona la app huesped.
_PROTECTED_FILES = {
    "replicator/core/security.py",
    "replicator/core/version_control.py",
    "replicator/core/bug_fixer.py",
    "replicator/core/evolution_engine.py",
    "replicator/core/governor.py",
    "replicator/core/db_manager.py",
    "replicator/core/metrics.py",
    "replicator/core/orchestrator.py",
    "replicator/core/alerts.py",
    "replicator/core/scraper_fitness.py",
    "replicator/core/circuit_breaker.py",
    "replicator/agents/guardian.py",
    "replicator/agents/scout.py",
    "replicator/agents/optimizer.py",
    "replicator/agents/tester.py",
    "replicator/agents/benchmark.py",
    "replicator/agents/base_agent.py",
    "replicator/agents/architect.py",
    "replicator/agents/designer.py",
    "replicator/agents/innovator.py",
    "replicator/ui/interface.py",
    "replicator/ui/approval_panel.py",
    "replicator/night_runner.py",
    "replicator/main.py",
}

# Carpetas raiz que indican codigo de REPLICATOR (intocable por el propio motor)
_PROTECTED_PREFIXES = ("replicator/",)


@dataclass
class ImprovementOpportunity:
    target_file: str
    func_name: str
    priority: int       # 1-5
    rationale: str
    metric_current: float


class ScoutAgent(BaseAgent):
    def __init__(self, ollama_host: str = "http://localhost:11434", db=None):
        super().__init__("Scout", "Code Quality Analysis")
        self.ollama_host = ollama_host
        self.db = db  # ReplicatorDB opcional — para leer memoria_errores
        self._metrics = MetricsTracker()

    async def think(self, context: str = "") -> list[ImprovementOpportunity]:
        """
        1. Mide fitness AST de todos los .py.
        2. Consulta memoria_errores de DB para ponderar parsers con más fallos.
        3. Busca ideas en DDGS.
        4. Pide al LLM que priorice qué función tiene más deuda técnica.
        5. Devuelve hasta 3 ImprovementOpportunity, priorizando los parsers con errores reales.
        """
        print(f"[INFO - {self.name}] Escaneando proyecto...")

        file_scores = self._scan_project()
        if not file_scores:
            print(f"[{self.name}] No se encontraron archivos .py para analizar.")
            return []

        # Penalizar fitness de los parsers que más errores han cometido en producción
        error_weights = self._load_error_weights()
        if error_weights:
            file_scores = self._apply_error_penalty(file_scores, error_weights)
            print(f"[{self.name}] Errores históricos cargados: {len(error_weights)} dominios con fallos.")

        ddgs_context = self._ddgs_search()

        worst_5 = sorted(file_scores, key=lambda x: x["fitness"])[:5]

        # Estrategia MVP: ignorar el LLM y usar SOLO analisis AST determinista.
        # El LLM genera placeholders falsos ("analizar_archivo") que rompen el flujo.
        # Identificamos la funcion mas compleja de cada archivo via AST.
        opportunities = self._fallback_opportunities(worst_5, error_weights)

        self.learn(opportunities)
        return opportunities[:_MAX_OPPORTUNITIES]

    # ── Escaneo de métricas ───────────────────────────────────────────────────

    _MAX_FILE_KB = 150  # ignorar archivos muy grandes (lentos de analizar)

    def _scan_project(self) -> list[dict]:
        results = []
        for py_file in _PROJECT_ROOT.rglob("*.py"):
            if any(part in _EXCLUDE_DIRS for part in py_file.parts):
                continue
            try:
                rel = str(py_file.relative_to(_PROJECT_ROOT)).replace("\\", "/")
                # Excluir REPLICATOR (no se toca a si mismo)
                if rel.startswith(_PROTECTED_PREFIXES):
                    continue
                if py_file.stat().st_size > self._MAX_FILE_KB * 1024:
                    continue
                metrics = self._metrics.measure_file(str(py_file))
                results.append({
                    "file": rel,
                    "fitness": metrics.get("fitness", 0.0),
                    "complexity": metrics.get("complexity", 0),
                    "loc": metrics.get("loc", 0),
                })
            except Exception:
                continue
        return results

    # ── Errores históricos de DB ──────────────────────────────────────────────

    def _load_error_weights(self) -> dict[str, int]:
        """Lee memoria_errores y devuelve {dominio: num_errores}."""
        if self.db is None:
            return {}
        try:
            with __import__("sqlite3").connect(self.db.db_path) as conn:
                rows = conn.execute(
                    "SELECT dominio, COUNT(*) as n FROM memoria_errores GROUP BY dominio ORDER BY n DESC"
                ).fetchall()
            return {row[0]: row[1] for row in rows}
        except Exception as e:
            print(f"[{self.name}] No se pudo leer memoria_errores: {type(e).__name__}")
            return {}

    def _apply_error_penalty(self, file_scores: list[dict], error_weights: dict[str, int]) -> list[dict]:
        """
        Reduce el fitness de los archivos de parsers cuyo dominio tiene errores en DB.
        Heurística: si 'farmacia' o 'electronica' tiene errores, penaliza parsers/{nombre}.py.
        """
        updated = []
        for f in file_scores:
            path = f["file"].replace("\\", "/").lower()
            penalty = 0
            for dominio, count in error_weights.items():
                # Relaciona dominio con archivo parser si coincide el nombre
                dominio_key = dominio.lower().split(".")[0]  # "promofarma.com" → "promofarma"
                if dominio_key in path:
                    penalty += min(count * 2, 20)  # máx 20 puntos de penalización
            updated.append({**f, "fitness": max(0.0, f["fitness"] - penalty), "error_penalty": penalty})
        return updated

    # ── DDGS research ─────────────────────────────────────────────────────────

    def _ddgs_search(self) -> str:
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text("python scraper optimization refactoring best practices", max_results=3):
                    results.append(r.get("title", ""))
            return " | ".join(results) if results else ""
        except Exception as e:
            print(f"[{self.name}] DDGS no disponible: {type(e).__name__}")
            return ""

    # ── LLM ──────────────────────────────────────────────────────────────────

    async def _ask_llm(self, worst_files: list[dict], ddgs_context: str, error_weights: dict = None) -> list[ImprovementOpportunity]:
        files_str = "\n".join(
            f"- {f['file']} (fitness={f['fitness']}, complexity={f['complexity']}, loc={f['loc']}"
            + (f", errores_produccion={f.get('error_penalty', 0)}" if f.get("error_penalty") else "") + ")"
            for f in worst_files
        )
        ddgs_line = f"\nTendencias externas: {ddgs_context}" if ddgs_context else ""

        top_errors = ""
        if error_weights:
            top = sorted(error_weights.items(), key=lambda x: x[1], reverse=True)[:3]
            top_errors = "\nDominios con más errores reales en producción: " + ", ".join(
                f"{d}({n})" for d, n in top
            )

        prompt = (
            "Eres un experto en calidad de código Python para un buscador de precios web.\n"
            "Analiza estos archivos (fitness 0-100, mayor=mejor; errores_produccion=fallos reales registrados):\n"
            f"{files_str}{ddgs_line}{top_errors}\n\n"
            "Prioriza archivos con errores de produccion altos. "
            "Identifica las 3 funciones con mas deuda tecnica o que causan errores reales. "
            "Responde SOLO con JSON valido, sin texto adicional:\n"
            '[{"target_file":"ruta/archivo.py","func_name":"nombre_funcion","priority":5,"rationale":"motivo breve"}]'
        )

        try:
            client = AsyncClient(host=self.ollama_host)
            r = await client.chat(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                options={"timeout": 60},
            )
            raw = r["message"]["content"].strip()
            # Extraer bloque JSON si viene entre ```
            if "```" in raw:
                raw = raw.split("```")[1].strip()
                if raw.startswith("json"):
                    raw = raw[4:].strip()
            # Aislar solo el array JSON (el LLM a veces añade texto antes/después)
            start = raw.find("[")
            end = raw.rfind("]")
            if start != -1 and end != -1:
                raw = raw[start:end + 1]
            # Limpiar escape sequences inválidas que llama3 suele generar
            # Eliminar TODOS los backslashes que no sean parte de un escape valido
            import re as _re
            # Solo conservar \\, \", \n, \t, \r, \uXXXX. El resto se elimina.
            raw = _re.sub(r'\\(?![\\"/bfnrtu])', '', raw)
            data = json.loads(raw)
            opportunities = []
            for item in data[:_MAX_OPPORTUNITIES]:
                target = (item.get("target_file") or "").replace("\\n", "/").replace("\n", "/").strip()
                target = target.replace("\\", "/")  # normalizar separadores
                func   = (item.get("func_name") or "analizar_archivo").strip()
                # Saltar archivos protegidos (REPLICATOR no se toca a si mismo)
                norm = target.replace("\\", "/")
                if norm.startswith(_PROTECTED_PREFIXES):
                    continue
                if any(norm.endswith(p.replace("\\", "/")) for p in _PROTECTED_FILES):
                    continue
                fitness = self._fitness_for_file(target)
                # priority puede venir como "high"/"low"/int — normalizamos
                raw_prio = item.get("priority") or 3
                try:
                    prio = max(1, min(5, int(str(raw_prio).strip())))
                except (ValueError, TypeError):
                    prio = 3
                opportunities.append(ImprovementOpportunity(
                    target_file=target,
                    func_name=func,
                    priority=prio,
                    rationale=item.get("rationale") or "",
                    metric_current=fitness,
                ))
            return opportunities
        except Exception as e:
            print(f"[{self.name}] Error en LLM/parse: {type(e).__name__}: {e}")
            return []

    def _fitness_for_file(self, relative_path: str) -> float:
        full = _PROJECT_ROOT / relative_path
        if full.is_file():
            return self._metrics.measure_file(str(full)).get("fitness", 0.0)
        return 0.0

    # ── Fallback sin LLM ─────────────────────────────────────────────────────

    def _worst_function_of(self, file_rel: str) -> str | None:
        """
        Por analisis AST, devuelve el nombre de la funcion mas compleja del archivo.
        Determinista, no usa LLM. Si no encuentra ninguna funcion, devuelve None.
        """
        import ast as _ast
        full = _PROJECT_ROOT / file_rel
        if not full.is_file():
            return None
        try:
            source = full.read_text(encoding="utf-8", errors="replace")
            tree = _ast.parse(source)
        except Exception:
            return None

        _MAX_FUNC_LINES = 80  # funciones mas grandes no las puede manejar el LLM en tiempo
        candidates = []
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                # Tamaño en lineas
                size = (getattr(node, "end_lineno", node.lineno) - node.lineno) + 1
                # Saltar funciones gigantes: el LLM siempre hace timeout con ellas
                if size > _MAX_FUNC_LINES:
                    continue
                # Calcular complejidad local: numero de if/for/while/try/with
                complexity = 1
                for sub in _ast.walk(node):
                    if isinstance(sub, (_ast.If, _ast.For, _ast.While, _ast.Try, _ast.With, _ast.ExceptHandler)):
                        complexity += 1
                # Score: complejidad pondera mas, pero tamaño tambien cuenta
                score = complexity * 2 + size * 0.1
                candidates.append((score, node.name))

        if not candidates:
            return None
        candidates.sort(reverse=True)
        # Preferir funciones publicas si las hay
        for score, name in candidates:
            if not name.startswith("_"):
                return name
        return candidates[0][1]

    def _fallback_opportunities(self, worst_files: list[dict], error_weights: dict = None) -> list[ImprovementOpportunity]:
        results = []
        def _is_safe(f):
            norm = f["file"].replace("\\", "/")
            if norm.startswith(_PROTECTED_PREFIXES):
                return False
            return not any(norm.endswith(p.replace("\\", "/")) for p in _PROTECTED_FILES)
        safe_files = [f for f in worst_files if _is_safe(f)]
        for f in safe_files[:_MAX_OPPORTUNITIES]:
            penalty = f.get("error_penalty", 0)
            # Identificar la funcion mas compleja por AST (determinista)
            worst_func = self._worst_function_of(f["file"])
            if worst_func is None:
                continue  # archivo sin funciones; saltar
            rationale = f"Fitness={f['fitness']:.1f}, funcion '{worst_func}' identificada por AST"
            if penalty:
                rationale += f", penalizacion por {penalty} errores de produccion"
            results.append(ImprovementOpportunity(
                target_file=f["file"],
                func_name=worst_func,
                priority=5 if penalty > 0 else 3,
                rationale=rationale,
                metric_current=f["fitness"],
            ))
        return results
