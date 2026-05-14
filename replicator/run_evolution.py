"""Runner headless: ejecuta un ciclo evolutivo completo sin UI."""
import asyncio
import sys
import io
import pathlib

# Forzar UTF-8 en stdout/stderr para que los caracteres Unicode de los agentes no fallen en Windows
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from core.db_manager import ReplicatorDB
from core.evolution_engine import EvolutionEngine
from core.circuit_breaker import CircuitBreaker


async def main():
    if "--reset-cb" in sys.argv:
        CircuitBreaker().reset_all()
        print("[run_evolution] Circuit breaker reseteado.")

    db = ReplicatorDB()
    engine = EvolutionEngine(db=db, ui=None, auto_approve=True, min_delta_pct=3.0)
    await engine.run_cycle()

    print("\n-- CYCLE LOG ------------------------------------------")
    for entry in engine.cycle_log:
        print(f"  [{entry['outcome'].upper():12}] {entry['file']} -> {entry['func']} "
              f"| delta={entry['delta_pct']:+.1f}% "
              f"| tests={entry['tests_passed']}p/{entry['tests_failed']}f "
              f"| {entry['reason']}")
    print("-------------------------------------------------------")


if __name__ == "__main__":
    asyncio.run(main())
