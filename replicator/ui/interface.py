import asyncio
import json
import os
import sys
import threading

import customtkinter as ctk


class ReplicatorUI(ctk.CTk):
    def __init__(self, app_core):
        super().__init__()
        self.core = app_core
        self.title("🛡️ REPLICATOR V3 — Sistema Multi-Agente Autónomo")
        self.geometry("1100x900")
        ctk.set_appearance_mode("dark")

        self.is_paused = False
        self.stop_ev_flag = False

        self.load_styles()
        self.setup_ui()
        self.apply_dynamic_styles()

    def load_styles(self):
        try:
            with open("styles.json", "r") as f:
                self.styles = json.load(f)
        except Exception:
            self.styles = {
                "bg_color": "#1a1a1a",
                "accent_color": "#8E44AD",
                "text_color": "#ffffff",
                "button_radius": 8,
            }

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=2)   # consola
        self.grid_rowconfigure(5, weight=1)   # historial

        # Header
        ctk.CTkLabel(
            self, text="🛡️ REPLICATOR V3 — Sistema Multi-Agente Autónomo",
            font=("Consolas", 18, "bold"),
        ).grid(row=0, column=0, pady=(20, 5))

        # Estado
        self.lbl_status = ctk.CTkLabel(
            self, text="Estado: Inicializando Colmena...", font=("Consolas", 12)
        )
        self.lbl_status.grid(row=1, column=0, pady=5)

        # Botones de control
        frm = ctk.CTkFrame(self)
        frm.grid(row=2, column=0, padx=20, pady=8, sticky="ew")
        frm.grid_columnconfigure((0, 1, 2), weight=1)

        self.btn_evolucionar = ctk.CTkButton(
            frm, text="🚀 Evolucionar", command=self.start_evolution,
            font=("Consolas", 12, "bold"),
        )
        self.btn_evolucionar.grid(row=0, column=0, padx=10, pady=8)

        ctk.CTkButton(
            frm, text="⏸ Pausar", command=self.toggle_pause,
            fg_color="#7f8c8d", hover_color="#616a6b",
        ).grid(row=0, column=1, padx=10, pady=8)

        ctk.CTkButton(
            frm, text="⏹ Apagar", command=self.shutdown_total,
            fg_color="#c0392b", hover_color="#922b21",
        ).grid(row=0, column=2, padx=10, pady=8)

        # Consola de log
        ctk.CTkLabel(self, text="Log:", font=("Consolas", 10)).grid(
            row=3, column=0, padx=20, sticky="w"
        )
        self.consola = ctk.CTkTextbox(self, font=("Consolas", 11), fg_color="#0d1117")
        self.consola.grid(row=3, column=0, padx=20, pady=(18, 5), sticky="nsew")

        # Historial de generaciones
        ctk.CTkLabel(self, text="Historial de generaciones:", font=("Consolas", 10)).grid(
            row=4, column=0, padx=20, sticky="w"
        )
        self.tbl_historial = ctk.CTkTextbox(self, height=160, font=("Consolas", 10), fg_color="#111")
        self.tbl_historial.grid(row=5, column=0, padx=20, pady=(18, 10), sticky="nsew")

        btn_refresh = ctk.CTkButton(
            self, text="↻ Refrescar historial", width=180,
            fg_color="#2c3e50", hover_color="#1a252f",
            command=self.refresh_historial,
        )
        btn_refresh.grid(row=6, column=0, pady=(0, 15))

    def apply_dynamic_styles(self):
        self.configure(fg_color=self.styles.get("bg_color", "#1a1a1a"))
        print("[INFO] UI Refrescada.")

    # ── Evolución ─────────────────────────────────────────────────────────────

    def start_evolution(self):
        print("[*] Iniciando Ciclo Evolutivo...")
        self.btn_evolucionar.configure(state="disabled", text="🚀 Evolucionando...")

        def run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.core.orchestrator.run_cycle())
            except Exception as e:
                print(f"[!] Error en ciclo evolutivo: {e}")
            finally:
                self.after(0, lambda: self.btn_evolucionar.configure(
                    state="normal", text="🚀 Evolucionar"
                ))
                self.after(500, self.refresh_historial)
                loop.close()

        threading.Thread(target=run, daemon=True).start()

    # ── Historial ─────────────────────────────────────────────────────────────

    def refresh_historial(self):
        """Recarga el historial de generaciones desde la DB y lo muestra."""
        try:
            rows = self.core.db.get_generation_history(limit=20)
        except Exception:
            return

        self.tbl_historial.configure(state="normal")
        self.tbl_historial.delete("1.0", "end")

        if not rows:
            self.tbl_historial.insert("1.0", "(sin generaciones registradas)")
        else:
            header = f"{'ID':>4}  {'Archivo':<30}  {'Func':<22}  {'ΔFitness':>9}  {'Estado':<12}  Timestamp\n"
            self.tbl_historial.insert("end", header)
            self.tbl_historial.insert("end", "─" * 110 + "\n")
            for r in rows:
                estado = "✅ aprobado" if r.get("approved") else f"  {r.get('phase','?')}"
                delta = f"{r.get('delta_pct', 0):+.1f}%"
                line = (
                    f"{r['id']:>4}  {str(r.get('target_file','')):<30}  "
                    f"{str(r.get('func_name','')):<22}  {delta:>9}  {estado:<12}  "
                    f"{str(r.get('timestamp',''))[:19]}\n"
                )
                self.tbl_historial.insert("end", line)

        self.tbl_historial.configure(state="disabled")

    # ── Controles ─────────────────────────────────────────────────────────────

    def toggle_pause(self):
        self.is_paused = not self.is_paused
        state = "PAUSADO" if self.is_paused else "REANUDADO"
        print(f"[UI] {state}")

    def shutdown_total(self):
        os._exit(0)
