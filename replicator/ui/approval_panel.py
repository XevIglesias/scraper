"""
ApprovalPanel: ventana modal CustomTkinter para revisar y aprobar/rechazar propuestas del engine.
"""
import threading
import customtkinter as ctk

from agents.scout import ImprovementOpportunity
from agents.tester import TestResult
from agents.benchmark import BenchmarkResult


class ApprovalPanel(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        opportunity: ImprovementOpportunity,
        proposed_code: str,
        test_result: TestResult,
        benchmark_result: BenchmarkResult,
        approve_event: threading.Event,
        reject_event: threading.Event,
    ):
        super().__init__(parent)
        self._approve_event = approve_event
        self._reject_event = reject_event
        self._deferred = False

        self.title("Revisión de mejora — REPLICATOR V3")
        self.geometry("900x700")
        self.resizable(True, True)
        ctk.set_appearance_mode("dark")

        self.grab_set()  # modal
        self.focus_set()
        self.protocol("WM_DELETE_WINDOW", self._on_reject)

        self._build_ui(opportunity, proposed_code, test_result, benchmark_result)

    # ── Construcción de la UI ─────────────────────────────────────────────────

    def _build_ui(
        self,
        opp: ImprovementOpportunity,
        code: str,
        tests: TestResult,
        bench: BenchmarkResult,
    ):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.grid_rowconfigure(4, weight=1)

        # ── Header ─────────────────────────────────────────────────────────────
        header_text = (
            f"Archivo: {opp.target_file}   |   Función: {opp.func_name}   |   Prioridad: {opp.priority}/5\n"
            f"Motivo: {opp.rationale}"
        )
        ctk.CTkLabel(
            self, text=header_text, font=("Consolas", 12, "bold"),
            justify="left", wraplength=860,
        ).grid(row=0, column=0, padx=20, pady=(15, 5), sticky="w")

        # ── Benchmark delta ────────────────────────────────────────────────────
        arrow = "↑" if bench.is_improvement else "↓"
        color = "#2ecc71" if bench.is_improvement else "#e74c3c"
        bench_text = (
            f"Fitness:  {bench.fitness_before:.1f}  →  {bench.fitness_after:.1f}  "
            f"({arrow} {bench.delta_pct:+.1f}%)"
        )
        ctk.CTkLabel(
            self, text=bench_text, font=("Consolas", 13, "bold"),
            text_color=color,
        ).grid(row=1, column=0, padx=20, pady=5, sticky="w")

        # ── Código propuesto ───────────────────────────────────────────────────
        ctk.CTkLabel(self, text="Código propuesto:", font=("Consolas", 11)).grid(
            row=2, column=0, padx=20, pady=(10, 0), sticky="w"
        )
        code_box = ctk.CTkTextbox(
            self, font=("Consolas", 11), fg_color="#0d1117", text_color="#c9d1d9",
        )
        code_box.grid(row=2, column=0, padx=20, pady=(25, 5), sticky="nsew")
        code_box.insert("1.0", code)
        code_box.configure(state="disabled")

        # ── Test results ───────────────────────────────────────────────────────
        p, f, e = tests.passed, tests.failed, tests.errors
        test_summary = f"Tests:  ✅ {p} passed   ❌ {f} failed   ⚠️ {e} errors"
        test_color = "#2ecc71" if tests.all_pass else "#e67e22"
        ctk.CTkLabel(
            self, text=test_summary, font=("Consolas", 12, "bold"), text_color=test_color,
        ).grid(row=3, column=0, padx=20, pady=(10, 0), sticky="w")

        test_out_box = ctk.CTkTextbox(self, height=130, font=("Consolas", 10), fg_color="#111")
        test_out_box.grid(row=4, column=0, padx=20, pady=(5, 10), sticky="nsew")
        test_out_box.insert("1.0", tests.output or "(sin output)")
        test_out_box.configure(state="disabled")

        # ── Botones ────────────────────────────────────────────────────────────
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=5, column=0, pady=15)

        ctk.CTkButton(
            btn_frame, text="✅  Aprobar", width=160, height=40,
            fg_color="#27ae60", hover_color="#1e8449",
            font=("Consolas", 13, "bold"),
            command=self._on_approve,
        ).pack(side="left", padx=15)

        ctk.CTkButton(
            btn_frame, text="❌  Rechazar", width=160, height=40,
            fg_color="#c0392b", hover_color="#922b21",
            font=("Consolas", 13, "bold"),
            command=self._on_reject,
        ).pack(side="left", padx=15)

        ctk.CTkButton(
            btn_frame, text="⏸  Diferir", width=160, height=40,
            fg_color="#7f8c8d", hover_color="#616a6b",
            font=("Consolas", 13, "bold"),
            command=self._on_defer,
        ).pack(side="left", padx=15)

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_approve(self):
        print("[ApprovalPanel] Usuario APROBÓ la mejora.")
        self._approve_event.set()
        self.destroy()

    def _on_reject(self):
        print("[ApprovalPanel] Usuario RECHAZÓ la mejora.")
        self._reject_event.set()
        self.destroy()

    def _on_defer(self):
        print("[ApprovalPanel] Usuario DIFIRIÓ la mejora (se trata como rechazo).")
        self._reject_event.set()
        self.destroy()
