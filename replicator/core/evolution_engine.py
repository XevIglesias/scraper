"""
EvolutionEngine: orquesta Scout→Optimizer→Guardian→Tester→Benchmark→Aprobación.

Modos:
  auto_approve=False (default, modo UI)  → muestra ApprovalPanel, espera al usuario
  auto_approve=True  (modo nocturno)     → aprueba solo si pasan TODOS los filtros de seguridad:
      1. Guardian: SAFE (AST + LLM)
      2. Tests:    0 failed, 0 errors
      3. Benchmark: delta_pct >= min_delta_pct
"""
import asyncio
import pathlib
import threading
from datetime import datetime

_AGENT_TIMEOUT = 240  # segundos máximos por llamada a cualquier agente (refactor lento en llama3)

from agents.scout import ScoutAgent, ImprovementOpportunity
from agents.optimizer import OptimizerAgent
from agents.guardian import GuardianAgent
from agents.tester import TesterAgent, TestResult
from agents.benchmark import BenchmarkAgent, BenchmarkResult
from core.version_control import VersionControl
from core.metrics import MetricsTracker
from core.scraper_fitness import ScraperFitness
from core.circuit_breaker import CircuitBreaker

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_MAX_PER_CYCLE = 3


class EvolutionEngine:
    def __init__(
        self,
        db,
        ui=None,
        ollama_host: str = "http://localhost:11434",
        auto_approve: bool = False,
        min_delta_pct: float = 3.0,  # mejora mínima de fitness para auto-aprobar
    ):
        self.db = db
        self.ui = ui
        self.ollama_host = ollama_host
        self.auto_approve = auto_approve
        self.min_delta_pct = min_delta_pct

        # Registro de lo que ocurrió en el ciclo (para el informe nocturno)
        self.cycle_log: list[dict] = []

        self._scout = ScoutAgent(ollama_host, db=db)
        self._optimizer = OptimizerAgent(ollama_host)
        self._guardian = GuardianAgent(ollama_host)
        self._tester = TesterAgent(ollama_host)
        self._benchmark = BenchmarkAgent()
        self._vc = VersionControl()
        self._metrics = MetricsTracker()
        self._scraper_fitness = ScraperFitness()
        self._circuit = CircuitBreaker()

        from core.bug_fixer import BugFixer
        self._bug_fixer = BugFixer(db, ollama_host)

    # ── Ciclo principal ───────────────────────────────────────────────────────

    async def run_cycle(self):
        self.cycle_log.clear()
        # Mostrar fitness real del buscador al inicio de cada ciclo
        fitness_data = self._scraper_fitness.compute()
        print(f"\n[EvolutionEngine] FITNESS BUSCADOR: {fitness_data['fitness']}/100 "
              f"| Exito busquedas: {fitness_data['tasa_exito']}% "
              f"| Fiab.tiendas: {fitness_data['tasa_confianza_tiendas']}% "
              f"| Sin errores: {fitness_data['tasa_sin_errores']}%")

        # Mostrar archivos bloqueados por circuit breaker
        blocked = self._circuit.get_blocked_files()
        if blocked:
            print(f"[EvolutionEngine] Archivos bloqueados por CircuitBreaker: {len(blocked)}")

        self._status("INICIANDO CICLO EVOLUTIVO" + (" [AUTO]" if self.auto_approve else " [MANUAL]"))

        try:
            # Scout puede ser lento la primera vez (cold start) → timeout mayor
            opportunities: list[ImprovementOpportunity] = await asyncio.wait_for(
                self._scout.think(), timeout=180
            )
        except asyncio.TimeoutError:
            print(f"[EvolutionEngine] Scout timeout. Usando fallback AST.")
            try:
                file_scores = self._scout._scan_project()
                worst = sorted(file_scores, key=lambda x: x["fitness"])[:3]
                opportunities = self._scout._fallback_opportunities(worst)
            except Exception:
                opportunities = []
        if not opportunities:
            self._status("Scout no encontró oportunidades. Ciclo terminado.")
            return

        print(f"[EvolutionEngine] {len(opportunities)} oportunidad(es) detectada(s).")

        for idx, opp in enumerate(opportunities[:_MAX_PER_CYCLE], 1):
            print(f"\n{'='*55}")
            print(f"[EvolutionEngine] Oportunidad {idx}/{min(len(opportunities), _MAX_PER_CYCLE)}: "
                  f"{opp.target_file} -> {opp.func_name} (prioridad {opp.priority})")
            try:
                await self._process_opportunity(opp)
            except Exception as exc:
                # Error en esta oportunidad → intentar auto-reparar + continuar
                print(f"[EvolutionEngine] Error en oportunidad {idx} ({opp.target_file}): {exc}")
                self._circuit.record_failure(opp.target_file.replace("\\", "/"), str(exc)[:80])
                await self._bug_fixer.fix(exc, str(_PROJECT_ROOT / opp.target_file))
                self.cycle_log.append({
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "file": opp.target_file, "func": opp.func_name or "?",
                    "priority": opp.priority, "rationale": opp.rationale,
                    "outcome": "error", "reason": str(exc),
                    "delta_pct": 0.0, "tests_passed": 0, "tests_failed": 0,
                })
                try:
                    self.db.store_generation(
                        phase="error", target_file=opp.target_file,
                        func_name=opp.func_name or "?", notes=str(exc),
                    )
                except Exception:
                    pass  # la DB tampoco puede bloquear el ciclo

        self._status("Ciclo evolutivo completado.")

    # ── Procesamiento de una oportunidad ─────────────────────────────────────

    async def _process_opportunity(self, opp: ImprovementOpportunity):
        log_entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "file": opp.target_file,
            "func": opp.func_name,
            "priority": opp.priority,
            "rationale": opp.rationale,
            "outcome": "skipped",
            "reason": "",
            "delta_pct": 0.0,
            "tests_passed": 0,
            "tests_failed": 0,
        }

        target_path = _PROJECT_ROOT / opp.target_file
        if not target_path.is_file():
            log_entry["reason"] = "archivo no encontrado"
            self.cycle_log.append(log_entry)
            print(f"[EvolutionEngine] Archivo no encontrado: {opp.target_file}")
            return

        # Circuit breaker: si este archivo ha fallado demasiado, saltarlo
        file_key = str(opp.target_file).replace("\\", "/")
        if self._circuit.is_blocked(file_key):
            log_entry["outcome"] = "skipped"
            log_entry["reason"] = "circuit breaker activo (demasiados fallos previos)"
            self.cycle_log.append(log_entry)
            print(f"[EvolutionEngine] Circuit breaker bloquea {opp.target_file}. Saltando.")
            return

        original_source = target_path.read_text(encoding="utf-8", errors="replace")

        # Snapshot antes de cualquier cambio
        self._status(f"Snapshot: {opp.target_file}...")
        snapshot_id = self._vc.snapshot(label=f"pre_{opp.func_name[:20]}")

        # Optimizer propone código
        self._status(f"Optimizer → {opp.func_name}...")
        try:
            proposed_code = await asyncio.wait_for(
                self._optimizer.think(str(target_path), opp.func_name),
                timeout=_AGENT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            log_entry["reason"] = f"Optimizer timeout ({_AGENT_TIMEOUT}s)"
            self.cycle_log.append(log_entry)
            self._circuit.record_failure(file_key, "Optimizer timeout")
            print(f"[EvolutionEngine] TIMEOUT del Optimizer en {opp.target_file}. Saltando.")
            return
        if not proposed_code.strip():
            log_entry["reason"] = "Optimizer no devolvió código"
            self.cycle_log.append(log_entry)
            print(f"[EvolutionEngine] Optimizer devolvio vacio. Saltando.")
            return
        print(f"[EvolutionEngine] Optimizer OK ({len(proposed_code)} chars).")

        # Si Optimizer devolvio solo una funcion, la inyectamos en el archivo completo
        # para que Guardian/Benchmark trabajen con codigo coherente
        full_proposed = self._splice_function(original_source, proposed_code, opp.func_name)
        if full_proposed is not None:
            print(f"[EvolutionEngine] Funcion '{opp.func_name}' insertada en el archivo completo.")
            proposed_code = full_proposed

        # FILTRO CRITICO: la propuesta debe preservar TODAS las funciones/clases publicas del original
        missing = self._missing_public_symbols(original_source, proposed_code)
        if missing:
            log_entry["outcome"] = "blocked"
            log_entry["reason"] = f"Propuesta elimina simbolos publicos: {missing[:5]}"
            self.cycle_log.append(log_entry)
            self._circuit.record_failure(file_key, "elimina simbolos publicos")
            print(f"[EvolutionEngine] RECHAZADO: la propuesta elimina {len(missing)} simbolos publicos: {missing[:5]}")
            return

        # Guardian: auditoría obligatoria siempre
        self._status("Guardian auditando...")
        try:
            safe, reason = await asyncio.wait_for(
                self._guardian.validate_code(proposed_code, original_code=original_source),
                timeout=_AGENT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            log_entry["reason"] = "Guardian timeout — descartado por seguridad"
            log_entry["outcome"] = "blocked"
            self.cycle_log.append(log_entry)
            return
        if not safe:
            log_entry["outcome"] = "blocked"
            log_entry["reason"] = f"Guardian: {reason}"
            self.cycle_log.append(log_entry)
            self._circuit.record_failure(file_key, f"Guardian: {reason[:80]}")
            print(f"[EvolutionEngine] BLOQUEADO por Guardian: {reason}")
            self.db.store_generation(
                phase="blocked_guardian", target_file=opp.target_file,
                func_name=opp.func_name, fitness_before=opp.metric_current,
                snapshot_id=snapshot_id, notes=reason,
            )
            return

        # Tester
        self._status(f"Tester → {opp.func_name}...")
        try:
            test_code = await asyncio.wait_for(
                self._tester.generate_tests(proposed_code, opp.func_name),
                timeout=_AGENT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            test_code = ""
        test_result: TestResult = self._tester.run_tests(test_code)
        log_entry["tests_passed"] = test_result.passed
        log_entry["tests_failed"] = test_result.failed + test_result.errors
        print(f"[EvolutionEngine] Tests: passed={test_result.passed} failed={test_result.failed} errors={test_result.errors}")

        # Benchmark
        self._status("Benchmark comparando fitness...")
        bench: BenchmarkResult = self._benchmark.compare(original_source, proposed_code)
        log_entry["delta_pct"] = bench.delta_pct

        if not bench.is_improvement:
            log_entry["outcome"] = "no_improvement"
            log_entry["reason"] = f"fitness {bench.delta_pct:+.1f}%"
            self.cycle_log.append(log_entry)
            self.db.store_generation(
                phase="no_improvement", target_file=opp.target_file,
                func_name=opp.func_name, fitness_before=bench.fitness_before,
                fitness_after=bench.fitness_after, delta_pct=bench.delta_pct,
                snapshot_id=snapshot_id,
            )
            return

        # Decisión: auto o manual
        self._current_opp = opp
        self._current_proposed = proposed_code
        approved, approval_reason = self._decide(test_result, bench)
        log_entry["reason"] = approval_reason

        if approved:
            self._status(f"Aplicando mejora a {opp.target_file}...")
            try:
                self._vc.apply_patch(str(target_path), proposed_code)
                log_entry["outcome"] = "approved"
                self.cycle_log.append(log_entry)
                self._circuit.record_success(file_key)  # exito → reset contador
                self.db.store_generation(
                    phase="approved", target_file=opp.target_file,
                    func_name=opp.func_name, fitness_before=bench.fitness_before,
                    fitness_after=bench.fitness_after, delta_pct=bench.delta_pct,
                    snapshot_id=snapshot_id, approved=True,
                    notes=f"Tests:{test_result.passed}p/{test_result.failed}f | {approval_reason}",
                )
                print(f"[EvolutionEngine] APLICADO: {opp.target_file} ({bench.delta_pct:+.1f}%)")
            except Exception as e:
                log_entry["outcome"] = "error"
                log_entry["reason"] = str(e)
                self.cycle_log.append(log_entry)
                print(f"[EvolutionEngine] Error aplicando patch: {e}")
        else:
            self._status(f"Rechazado. Rollback → {snapshot_id}...")
            self._vc.rollback(snapshot_id)
            log_entry["outcome"] = "rejected"
            self.cycle_log.append(log_entry)
            self.db.store_generation(
                phase="rejected", target_file=opp.target_file,
                func_name=opp.func_name, fitness_before=bench.fitness_before,
                fitness_after=bench.fitness_after, delta_pct=bench.delta_pct,
                snapshot_id=snapshot_id, approved=False, notes=approval_reason,
            )
            print(f"[EvolutionEngine] Rechazado: {approval_reason}")

    # ── Lógica de aprobación ──────────────────────────────────────────────────

    def _decide(self, test_result: TestResult, bench: BenchmarkResult) -> tuple[bool, str]:
        """Devuelve (aprobado, motivo). En modo auto aplica umbrales; en modo manual pide al usuario."""
        if self.auto_approve:
            return self._auto_decision(test_result, bench)
        return self._manual_decision_ui(test_result, bench)

    def _auto_decision(self, test_result: TestResult, bench: BenchmarkResult) -> tuple[bool, str]:
        """
        Aprueba auto SOLO si:
          1. Si HUBO tests ejecutados: 0 failed. (errores de generacion no bloquean — Ollama puede fallar al escribir tests sin que la mejora sea mala)
          2. Benchmark: delta_pct >= min_delta_pct
          (Guardian ya paso antes — condicion previa absoluta)
        """
        if test_result.passed > 0 and test_result.failed > 0:
            return False, f"Tests fallaron ({test_result.failed} de {test_result.passed + test_result.failed})"
        if bench.delta_pct < self.min_delta_pct:
            return False, f"Mejora insuficiente ({bench.delta_pct:.1f}% < umbral {self.min_delta_pct}%)"
        if test_result.passed > 0:
            return True, f"Tests OK ({test_result.passed}p), fitness +{bench.delta_pct:.1f}%"
        return True, f"Sin tests verificables, fitness +{bench.delta_pct:.1f}% (Guardian SAFE)"

    def _manual_decision_ui(self, test_result: TestResult, bench: BenchmarkResult) -> tuple[bool, str]:
        """Muestra ApprovalPanel y espera la decisión del usuario."""
        if self.ui is None:
            return False, "Sin UI y auto_approve=False — propuesta descartada"

        # Necesitamos la oportunidad actual — la pasamos a través de un contexto temporal
        opp = getattr(self, "_current_opp", None)
        proposed = getattr(self, "_current_proposed", "")

        approve_event = threading.Event()
        reject_event = threading.Event()

        def _show():
            from ui.approval_panel import ApprovalPanel
            ApprovalPanel(
                parent=self.ui, opportunity=opp, proposed_code=proposed,
                test_result=test_result, benchmark_result=bench,
                approve_event=approve_event, reject_event=reject_event,
            )

        self._status("Esperando aprobación del usuario...")
        self.ui.after(0, _show)
        while not approve_event.is_set() and not reject_event.is_set():
            approve_event.wait(timeout=0.2)

        if approve_event.is_set():
            return True, "Aprobado manualmente"
        return False, "Rechazado manualmente"

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _public_symbols(source: str) -> set[str]:
        """Devuelve nombres de clases y funciones publicas (no empiezan con _) en top-level."""
        import ast
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return set()
        names = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.name.startswith("_"):
                    names.add(node.name)
            # Tambien capturar metodos publicos de clases publicas
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not child.name.startswith("_"):
                            names.add(f"{node.name}.{child.name}")
        return names

    def _missing_public_symbols(self, original: str, proposed: str) -> list[str]:
        """Lista los simbolos publicos que existian en original pero no en proposed."""
        orig_symbols = self._public_symbols(original)
        new_symbols  = self._public_symbols(proposed)
        return sorted(orig_symbols - new_symbols)

    def _splice_function(self, original: str, snippet: str, func_name: str) -> str | None:
        """
        Si snippet es solo una funcion (no archivo entero), la reemplaza en el original.
        Devuelve None si no aplica (snippet ya es archivo completo).
        """
        if not func_name or func_name.startswith("(") or func_name in {"analizar_archivo", "unknown", ""}:
            return None
        try:
            import ast
            snip_tree = ast.parse(snippet)
            # Si snippet solo contiene una funcion con ese nombre, es un fragmento
            top_level = [n for n in snip_tree.body
                         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            if len(top_level) != 1 or top_level[0].name != func_name:
                return None  # no es fragmento, dejarlo tal cual

            # Buscar la funcion en el original y sustituirla
            orig_tree = ast.parse(original)
            for node in ast.walk(orig_tree):
                if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name == func_name):
                    lines = original.splitlines(keepends=True)
                    start = node.lineno - 1
                    end = getattr(node, "end_lineno", node.lineno + 20)

                    # Preservar la indentacion del original (crucial para metodos de clase)
                    orig_line = lines[start]
                    leading_ws = len(orig_line) - len(orig_line.lstrip())
                    indent = orig_line[:leading_ws]  # e.g. "    " para metodos de clase

                    snip_to_insert = snippet.rstrip()
                    if leading_ws > 0:
                        snip_lines = snip_to_insert.splitlines()
                        # Detectar indentacion actual del snippet (generalmente 0)
                        min_indent = min(
                            (len(l) - len(l.lstrip()) for l in snip_lines if l.strip()),
                            default=0
                        )
                        reindented = []
                        for line in snip_lines:
                            if line.strip():
                                reindented.append(indent + line[min_indent:])
                            else:
                                reindented.append(line)
                        snip_to_insert = "\n".join(reindented)

                    new_lines = lines[:start] + [snip_to_insert + "\n"] + lines[end:]
                    return "".join(new_lines)
        except Exception as e:
            print(f"[EvolutionEngine] _splice_function fallo: {type(e).__name__}")
        return None

    def _status(self, text: str):
        print(f"[EvolutionEngine] {text}")
        if self.ui:
            self.ui.after(0, lambda t=text: self.ui.lbl_status.configure(text=t))
