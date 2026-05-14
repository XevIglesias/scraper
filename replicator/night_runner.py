"""
REPLICATOR V3 - Runner autonomo (sirve para dia o noche).

Seguridad:
  - Comprueba que Ollama esta vivo antes de empezar
  - Timeout 120s por operacion (nunca se congela)
  - BugFixer no toca archivos de seguridad ni el propio runner
  - Snapshot antes de cada cambio (rollback siempre disponible)
  - CircuitBreaker: archivos con 3+ fallos quedan bloqueados
  - Si BugFixer repara un bug, el proceso se relanza solo
  - Log completo en replicator/reports/night_YYYY-MM-DD.log
  - Informe legible en replicator/reports/YYYY-MM-DD_HH-MM.md

Uso:
    Prueba rapida (1 ciclo, no aplica nada):
        python replicator/night_runner.py --test

    Dia (1-2 ciclos, supervisado):
        python replicator/night_runner.py --cycles 1

    Noche (mas ciclos, autonomo):
        python replicator/night_runner.py --cycles 5 --delta 3.0
"""
import argparse
import asyncio
import os
import pathlib
import sys
import time
from datetime import datetime

# ── Setup de paths ────────────────────────────────────────────────────────────
_HERE = pathlib.Path(__file__).resolve().parent   # replicator/
_ROOT = _HERE.parent                               # scraper/
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

_REPORTS_DIR  = _HERE / "reports"
_RESTART_FLAG = _HERE / ".restart_needed"
_REPORTS_DIR.mkdir(exist_ok=True)

DEFAULT_CYCLES    = 3
DEFAULT_DELTA     = 3.0
DEFAULT_HOST      = "http://localhost:11434"
MAX_RUNTIME_HOURS = 6


# ── Logger dual (consola + fichero) ──────────────────────────────────────────

class _DualLogger:
    """Redirige stdout a consola Y a fichero simultáneamente."""
    def __init__(self, log_path: pathlib.Path):
        self._file   = open(log_path, "a", encoding="utf-8", buffering=1)
        self._stdout = sys.__stdout__

    def write(self, msg):
        try:
            self._stdout.write(msg)
        except UnicodeEncodeError:
            self._stdout.write(msg.encode("ascii", errors="replace").decode("ascii"))
        self._file.write(msg)

    def flush(self):
        self._stdout.flush()
        self._file.flush()

    def close(self):
        self._file.close()


# ── Preflight: comprobar que Ollama responde ──────────────────────────────────

async def _check_ollama(host: str) -> bool:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{host}/api/tags")
            return r.status_code == 200
    except Exception:
        pass
    try:
        import urllib.request
        urllib.request.urlopen(f"{host}/api/tags", timeout=10)
        return True
    except Exception:
        return False


async def _warm_up_ollama(host: str) -> bool:
    """Carga el modelo en memoria con un prompt corto. Evita cold-start posterior."""
    from core.llm_config import MODEL
    print(f"[Preflight] Calentando modelo '{MODEL}' (puede tardar 30-60s la primera vez)...")
    try:
        from ollama import AsyncClient
        import asyncio
        client = AsyncClient(host=host)
        await asyncio.wait_for(
            client.chat(model=MODEL, messages=[{"role": "user", "content": "OK"}]),
            timeout=180,
        )
        print(f"[Preflight] OK: {MODEL} cargado.\n")
        return True
    except Exception as e:
        print(f"[Preflight] WARNING: warm-up fallo ({type(e).__name__}: {e}).\n")
        return False


# ── Runner principal ──────────────────────────────────────────────────────────

async def run_night(cycles: int, min_delta: float, ollama_host: str) -> list[dict]:
    from core.db_manager import ReplicatorDB
    from core.evolution_engine import EvolutionEngine
    from core.scraper_fitness import ScraperFitness

    print(f"\n{'='*62}")
    print(f"  REPLICATOR V3 - MODO NOCTURNO AUTONOMO")
    print(f"  Inicio: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"  Ciclos: {cycles}  |  Delta minimo para aprobar: {min_delta}%")
    print(f"  Ollama: {ollama_host}")
    print(f"{'='*62}\n")

    # 1. Comprobar Ollama
    print("[Preflight] Comprobando Ollama...")
    if not await _check_ollama(ollama_host):
        print("[Preflight] ERROR: Ollama no responde. Ejecuta: ollama serve")
        sys.exit(1)
    print("[Preflight] OK: Ollama activo.")

    # 1b. Calentar el modelo
    await _warm_up_ollama(ollama_host)

    # 2. Limpiar flags de sesión anterior
    for flag in (_RESTART_FLAG, _HERE / ".fix_count"):
        if flag.exists():
            flag.unlink(missing_ok=True)

    # 3. Fitness inicial
    fitness_inicial = ScraperFitness().compute()
    print(f"[Preflight] FITNESS INICIAL: {fitness_inicial['fitness']}/100")
    print(f"            Exito busquedas:      {fitness_inicial['tasa_exito']}%")
    print(f"            Fiabilidad tiendas:   {fitness_inicial['tasa_confianza_tiendas']}%")
    print(f"            Dominios sin errores: {fitness_inicial['tasa_sin_errores']}%\n")

    db     = ReplicatorDB(str(_ROOT / "replicator.db"))
    engine = EvolutionEngine(
        db=db, ui=None, ollama_host=ollama_host,
        auto_approve=True, min_delta_pct=min_delta,
    )

    all_logs   = []
    start_time = time.time()

    for cycle_num in range(1, cycles + 1):
        # Parada de emergencia por tiempo
        elapsed_h = (time.time() - start_time) / 3600
        if elapsed_h >= MAX_RUNTIME_HOURS:
            print(f"\n[NightRunner] Parada de seguridad: {elapsed_h:.1f}h transcurridas.")
            break

        print(f"\n{'-'*62}")
        print(f"[NightRunner] >> CICLO {cycle_num}/{cycles}   {datetime.now():%H:%M:%S}")
        print(f"{'-'*62}")

        try:
            await engine.run_cycle()
            all_logs.extend(engine.cycle_log)
        except Exception as e:
            print(f"[NightRunner] Error en ciclo {cycle_num}: {type(e).__name__}: {e}")
            try:
                await engine._bug_fixer.fix(e)
            except Exception:
                pass
            all_logs.append({
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "file": "ciclo", "func": "—", "outcome": "error",
                "reason": f"{type(e).__name__}: {e}",
                "delta_pct": 0, "tests_passed": 0, "tests_failed": 0,
            })

        # Si BugFixer aplicó un fix → relanzar el proceso para cargar el código nuevo
        if _RESTART_FLAG.exists():
            fix_info = _RESTART_FLAG.read_text(encoding="utf-8").strip()
            print(f"\n[NightRunner] Bug reparado ({fix_info}). Relanzando proceso...")
            _generate_report(all_logs, cycle_num, min_delta, fitness_inicial, partial=True)
            # Relanzar con los mismos argumentos pero ciclos restantes
            remaining = cycles - cycle_num
            new_args = [sys.executable, str(_HERE / "night_runner.py"),
                        "--cycles", str(remaining),
                        "--delta", str(min_delta),
                        "--host", ollama_host]
            _RESTART_FLAG.unlink()
            os.execv(sys.executable, new_args)
            # os.execv reemplaza el proceso — el código de aquí no se ejecuta

        # Pausa entre ciclos
        if cycle_num < cycles:
            wait = 45
            print(f"[NightRunner] Pausa {wait}s antes del siguiente ciclo...")
            await asyncio.sleep(wait)

    # Fitness final
    fitness_final = ScraperFitness().compute()
    report_path = _generate_report(all_logs, cycles, min_delta, fitness_inicial,
                                   fitness_final=fitness_final)
    _print_summary(all_logs, fitness_inicial, fitness_final, report_path)
    return all_logs


def _print_summary(logs, fitness_inicial, fitness_final, report_path):
    """Resumen claro y corto en terminal: que cambio en el buscador."""
    approved  = [l for l in logs if l["outcome"] == "approved"]
    blocked   = [l for l in logs if l["outcome"] == "blocked"]
    rejected  = [l for l in logs if l["outcome"] == "rejected"]
    errors    = [l for l in logs if l["outcome"] == "error"]

    fi, ff = fitness_inicial["fitness"], fitness_final["fitness"]
    delta  = ff - fi

    print(f"\n{'='*62}")
    print(f"  RESUMEN DE LA SESION")
    print(f"{'='*62}")

    if approved:
        print(f"\n  Tu buscador mejoro en {len(approved)} sitio(s):\n")
        for l in approved:
            file_short = l['file'].split("/")[-1].split("\\")[-1]
            print(f"    [OK] {file_short}  ->  funcion '{l['func']}'")
            print(f"         Mejora de calidad: {l['delta_pct']:+.1f}%")
            if l.get('rationale'):
                print(f"         Motivo: {l['rationale'][:80]}")
            print()
    else:
        print(f"\n  Esta sesion no aplico cambios al buscador.")
        if blocked:
            print(f"  ({len(blocked)} propuesta(s) bloqueadas por seguridad — codigo peligroso)")
        if rejected:
            print(f"  ({len(rejected)} propuesta(s) descartadas por no mejorar lo suficiente)")
        print()

    # Tabla de fitness
    print(f"  FITNESS DEL BUSCADOR:")
    print(f"    Antes:    {fi}/100")
    print(f"    Despues:  {ff}/100  ({'+' if delta >= 0 else ''}{delta:.1f})")
    print()
    print(f"    Exito en busquedas:  {fitness_inicial['tasa_exito']}% -> {fitness_final['tasa_exito']}%")
    print(f"    Fiab. tiendas:       {fitness_inicial['tasa_confianza_tiendas']}% -> {fitness_final['tasa_confianza_tiendas']}%")
    print(f"    Sin errores:         {fitness_inicial['tasa_sin_errores']}% -> {fitness_final['tasa_sin_errores']}%")

    if errors:
        print(f"\n  Hubo {len(errors)} error(es) durante la ejecucion (auto-reparados o ignorados).")

    print(f"\n  Informe detallado: {report_path}")
    print(f"{'='*62}\n")


# ── Informe legible ───────────────────────────────────────────────────────────

def _generate_report(
    logs: list[dict],
    cycles_done: int,
    min_delta: float,
    fitness_inicial: dict,
    fitness_final: dict | None = None,
    partial: bool = False,
) -> pathlib.Path:
    now   = datetime.now()
    fname = _REPORTS_DIR / f"{now:%Y-%m-%d_%H-%M}.md"

    approved  = [l for l in logs if l["outcome"] == "approved"]
    rejected  = [l for l in logs if l["outcome"] == "rejected"]
    blocked   = [l for l in logs if l["outcome"] == "blocked"]
    no_improv = [l for l in logs if l["outcome"] == "no_improvement"]
    errors    = [l for l in logs if l["outcome"] == "error"]

    fi = fitness_inicial["fitness"]
    ff = fitness_final["fitness"] if fitness_final else "—"
    delta_fitness = f"{ff - fi:+.1f}" if fitness_final else "—"

    lines = [
        f"# Informe nocturno{'(parcial)' if partial else ''} — {now:%Y-%m-%d %H:%M}",
        "",
        "## ¿Qué pasó esta noche?",
        "",
    ]

    # Resumen en lenguaje humano
    if approved:
        lines.append(
            f"El sistema aplicó **{len(approved)} mejora(s)** al código del buscador. "
            "Cada una pasó revisión de seguridad automática, tests y verificación de calidad."
        )
    else:
        lines.append(
            "El sistema no aplicó cambios esta noche "
            "(ninguna propuesta superó todos los filtros de seguridad)."
        )
    if blocked:
        lines.append(
            f"Se bloquearon **{len(blocked)} propuesta(s)** por el sistema de seguridad "
            "(el código generado tenía instrucciones peligrosas)."
        )
    lines += [""]

    # Fitness
    lines += [
        "## Evolución del buscador",
        "",
        f"| Métrica | Antes | Después | Cambio |",
        f"|---------|-------|---------|--------|",
        f"| Fitness global (0-100) | {fi} | {ff} | {delta_fitness} |",
        f"| Éxito en búsquedas | {fitness_inicial['tasa_exito']}% | "
        f"{fitness_final['tasa_exito'] if fitness_final else '—'}% | — |",
        f"| Fiabilidad de tiendas | {fitness_inicial['tasa_confianza_tiendas']}% | "
        f"{fitness_final['tasa_confianza_tiendas'] if fitness_final else '—'}% | — |",
        f"| Dominios sin errores | {fitness_inicial['tasa_sin_errores']}% | "
        f"{fitness_final['tasa_sin_errores'] if fitness_final else '—'}% | — |",
        "",
        f"**Ciclos completados:** {cycles_done}  |  **Umbral aplicado:** Δ ≥ {min_delta}%",
        "",
    ]

    # Detalle de mejoras aplicadas
    if approved:
        lines += ["## ✅ Mejoras aplicadas al código", ""]
        for l in approved:
            lines += [
                f"### {l['file']} → `{l['func']}`",
                f"- **Mejora de calidad:** {l['delta_pct']:+.1f}%",
                f"- **Tests:** {l['tests_passed']} correctos, {l['tests_failed']} fallidos",
                f"- **Motivo:** {l.get('rationale', '—')}",
                f"- **Hora:** {l['timestamp']}",
                "",
            ]

    # Rechazados con motivo
    if rejected:
        lines += ["## ❌ Propuestas que no superaron los filtros", ""]
        for l in rejected:
            lines.append(f"- `{l['file']}` → `{l['func']}`: {l['reason']}")
        lines.append("")

    # Bloqueados por Guardian
    if blocked:
        lines += ["## 🛡️ Bloqueados por seguridad (Guardian)", ""]
        lines.append("Estas propuestas contenían código potencialmente peligroso y fueron descartadas sin tocar nada:")
        for l in blocked:
            lines.append(f"- `{l['file']}` → `{l['func']}`: {l['reason']}")
        lines.append("")

    # Errores
    if errors:
        lines += ["## ⚠️ Errores durante la ejecución", ""]
        lines.append("Estos errores ocurrieron pero el sistema continuó funcionando:")
        for l in errors:
            lines.append(f"- {l['timestamp']}: {l['reason']}")
        lines.append("")

    lines += [
        "---",
        f"_REPLICATOR V3 — Informe generado el {now:%Y-%m-%d a las %H:%M}_",
    ]

    fname.write_text("\n".join(lines), encoding="utf-8")
    return fname


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="REPLICATOR V3 — Modo nocturno")
    parser.add_argument("--cycles", type=int,   default=DEFAULT_CYCLES)
    parser.add_argument("--delta",  type=float, default=DEFAULT_DELTA)
    parser.add_argument("--host",   type=str,   default=DEFAULT_HOST)
    parser.add_argument("--test",   action="store_true",
                        help="Modo prueba: 1 ciclo, sin aplicar cambios, solo verifica que todo funciona")
    args = parser.parse_args()

    if args.test:
        print("\n[TEST] Modo prueba: 1 ciclo, delta=999 (no aplica nada, solo verifica pipeline)")
        args.cycles = 1
        args.delta  = 999.0   # umbral imposible → nunca aprueba, solo recorre el pipeline

    # Fix asyncio+subprocess en Windows (debe ir antes de asyncio.run)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Log dual: consola + fichero
    log_path = _REPORTS_DIR / f"night_{datetime.now():%Y-%m-%d}.log"
    logger   = _DualLogger(log_path)
    sys.stdout = logger

    try:
        asyncio.run(run_night(args.cycles, args.delta, args.host))
    except KeyboardInterrupt:
        print("\n[NightRunner] Interrumpido por el usuario.")
    finally:
        sys.stdout = sys.__stdout__
        logger.close()
        if args.test:
            print(f"\n[TEST] Pipeline verificado. Log: {log_path}")
            print("[TEST] Si no hubo errores, lanza la noche con:")
            print("         python replicator/night_runner.py --cycles 3")


if __name__ == "__main__":
    main()
