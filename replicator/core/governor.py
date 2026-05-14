import psutil
import time
import logging

class ResourceGovernor:
    def __init__(self, ram_limit_gb=5.0):

        self.ram_limit = ram_limit_gb * 1024 * 1024 * 1024
        self.is_critical = False

    def check_resources(self):
        ram = psutil.virtual_memory()
        usage_gb = ram.used / (1024**3)
        
        if ram.used > self.ram_limit:
            self.is_critical = True
            return False, f"CRITICAL: RAM usage at {usage_gb:.2f}GB"
        
        self.is_critical = False
        return True, f"OK: RAM usage at {usage_gb:.2f}GB"

    def monitor_loop(self, alert_callback):
        """
        Bucle de monitorización continua. NUNCA detiene el proceso principal.
        Si la RAM es crítica: avisa y espera — cuando baje, continúa solo.
        """
        alert_sent = False
        while True:
            try:
                ok, msg = self.check_resources()
                if not ok:
                    if not alert_sent:
                        print(f"[Governor] ⚠️ ALERTA RAM: {msg}")
                        try:
                            alert_callback("ALERTA DE HARDWARE", msg)
                        except Exception:
                            pass  # el fallo del email no puede parar nada
                        alert_sent = True
                else:
                    if alert_sent:
                        print(f"[Governor] ✅ RAM normalizada: {msg}")
                        alert_sent = False
            except Exception as e:
                print(f"[Governor] Error en monitorización (ignorado): {type(e).__name__}")
            time.sleep(30)  # cada 30s es suficiente


