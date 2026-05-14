import sys
import threading
import os
from dotenv import load_dotenv
from core.db_manager import ReplicatorDB
from core.governor import ResourceGovernor
from core.alerts import AlertSystem
from core.orchestrator import EvolutionOrchestrator
from ui.interface import ReplicatorUI

from agents.guardian import GuardianAgent
from agents.architect import ArchitectAgent
from agents.optimizer import OptimizerAgent
from agents.designer import DesignerAgent
from agents.innovator import InnovatorAgent

# Cargar variables de entorno (.env)
load_dotenv()

class ReplicatorApp:
    def __init__(self):
        print("[*] Inicializando REPLICATOR V3 - Multi-Agent System")
        
        # 1. Componentes Core
        self.db = ReplicatorDB()
        # Límite de 13.5GB para proteger los 16GB totales
        self.governor = ResourceGovernor(ram_limit_gb=13.5)
        self.alerts = AlertSystem() # Lee directamente del .env
        
        # 2. Inicializar Agentes
        self.agents = {
            "guardian": GuardianAgent(),
            "architect": ArchitectAgent(),
            "optimizer": OptimizerAgent(),
            "designer": DesignerAgent(),
            "innovator": InnovatorAgent()
        }

        self.orchestrator = EvolutionOrchestrator(self.agents, self.db, None)
        
        # 2. Iniciar Monitorización de Recursos (Alertas reales por email)
        print("[*] Iniciando Monitor de Recursos...")
        threading.Thread(target=self.governor.monitor_loop, 
                         args=(self.alerts.send_alert,), 
                         daemon=True).start()
        
        # 3. Lanzar UI
        self.ui = ReplicatorUI(self)
        self.orchestrator.ui = self.ui # Vincular UI al orquestador
        self.ui.mainloop()


if __name__ == "__main__":
    ReplicatorApp()
