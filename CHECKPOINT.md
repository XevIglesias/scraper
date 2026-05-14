# Checkpoint — 2026-05-14
Fitness: 55/100 (DB vacía, sube con búsquedas reales)
Git hash: edbdaa46eb80ee9dc89ff5efff5faad8303f104b

## Última tarea completada
FastAPI creado (api.py) y pusheado a GitHub. Falta arrancarlo en el servidor.

## Estado del servidor (49.12.227.67)
- Ubuntu 24.04, Ollama + llama3 instalados
- /opt/scraper clonado, venv activado, .env configurado
- **PENDIENTE**: git pull + pip install fastapi uvicorn + arrancar uvicorn
- SSH key: C:\Users\xevi2\.ssh\hetzner_tmp_nopass

## Próxima sesión — hacer en orden

### 1. Arrancar la API en el servidor
```bash
cd /opt/scraper && git pull && source venv/bin/activate && pip install fastapi uvicorn pydantic && uvicorn api:app --host 0.0.0.0 --port 8000
```
Abrir en navegador: http://49.12.227.67:8000

### 2. Crear servicio systemd (para que arranque solo al reiniciar)
```bash
cat > /etc/systemd/system/scraper.service << 'EOF'
[Unit]
Description=Comparador de precios
After=network.target ollama.service
[Service]
Type=simple
User=root
WorkingDirectory=/opt/scraper
Environment=PATH=/opt/scraper/venv/bin
ExecStart=/opt/scraper/venv/bin/uvicorn api:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl enable scraper && systemctl start scraper
```

### 3. Añadir scraper programado cada 6h
Añadir a crontab:
```bash
0 */6 * * * cd /opt/scraper && source venv/bin/activate && python3 replicator/run_evolution.py >> /var/log/scraper.log 2>&1
```

### 4. Volver el repo a privado
GitHub → repo scraper → Settings → Change visibility → Private

### 5. Rotar el Gmail app password
La contraseña actual quedó expuesta en la conversación. Generar nueva en:
myaccount.google.com → Seguridad → Contraseñas de aplicaciones
Actualizar /opt/scraper/.env en el servidor.

## Contexto importante
- El fitness 55/100 es neutro (historial_precios vacío). Sube solo con búsquedas reales desde la UI web.
- movilines, refurbed, grover, ktronix ya están en BASURA.
- Bug precio europeo 1.299,99 ya corregido.
- _buscar_parser() ya soporta subdominios.
- Python local es Microsoft Store (sin tkinter) → no se puede probar buscador_app.py en local.
