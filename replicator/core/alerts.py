import ctypes
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

class AlertSystem:
    def __init__(self, target_email=None):
        self.target_email = target_email or os.getenv("EMAIL_RECEIVER", "")
        self.sender = os.getenv("EMAIL_SENDER")
        self.password = os.getenv("EMAIL_PASSWORD")
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))

    def send_alert(self, subject, message):
        """Envía una alerta por email y muestra un MessageBox en Windows."""
        print(f"[!] ALERTA - {subject}: {message}")

        # 1. Alerta Local (MessageBox)
        try:
            ctypes.windll.user32.MessageBoxW(0, message, f"Alerta: {subject}", 0x30 | 0x1000)
        except Exception as e:
            # No logear el error original (puede contener rutas o detalles internos)
            print(f"[!] Error en MessageBox: {type(e).__name__}")

        # 2. Alerta por Email
        if self.sender and self.password:
            server = None
            try:
                msg = MIMEMultipart()
                msg['From'] = self.sender
                msg['To'] = self.target_email
                msg['Subject'] = f"REPLICATOR V3: {subject}"

                body = (
                    "SISTEMA: REPLICATOR V3 - ORGANISMO AUTÓNOMO\n\n"
                    f"ALERTA: {subject}\n\n"
                    f"DETALLE:\n{message}\n\n"
                    "---\nEnviado automáticamente por el Gobernador de Recursos."
                )
                msg.attach(MIMEText(body, 'plain'))

                server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10)
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(self.sender, self.password)
                server.send_message(msg)
                print(f"[OK] Email de alerta enviado a {self.target_email}")

            except smtplib.SMTPAuthenticationError:
                print("[!] Error enviando email: Fallo de autenticacion SMTP. Verifica EMAIL_PASSWORD en .env")
            except smtplib.SMTPException as e:
                # Loguear solo el tipo, no el mensaje (puede echar credenciales en algunos servidores)
                print(f"[!] Error enviando email: {type(e).__name__}")
            except OSError:
                print("[!] Error enviando email: No se pudo conectar al servidor SMTP.")
            except Exception:
                print("[!] Error enviando email: Error desconocido.")
            finally:
                if server is not None:
                    try:
                        server.quit()
                    except Exception:
                        pass
        else:
            print("[!] Alerta de email omitida: Faltan credenciales en .env")
