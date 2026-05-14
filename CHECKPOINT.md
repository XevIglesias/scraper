# Checkpoint — 2026-05-14
Fitness: 55/100 → sube solo con el worker corriendo (llena historial_precios)
Git hash: 1199539

## Última tarea completada
Worker 24/7 implementado y pusheado. Arranca automáticamente con FastAPI.
Bucle /evolve cerrado: worker descubre errores → /evolve los corrige → fitness sube.

## Estado del servidor (49.12.227.67)
- SSH key: C:\Users\xevi2\.ssh\hetzner_tmp_nopass (tiene passphrase)
- **PENDIENTE**: ejecutar deploy manual (ver comandos en conversación)

## Comandos deploy (ejecutar en PowerShell del usuario)
```bash
ssh -i $HOME\.ssh\hetzner_tmp_nopass root@49.12.227.67
# Dentro del servidor:
cd /opt/scraper && git pull && source venv/bin/activate && pip install -q fastapi uvicorn
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
systemctl daemon-reload && systemctl enable scraper && systemctl restart scraper
(crontab -l 2>/dev/null; echo '0 */6 * * * cd /opt/scraper && source venv/bin/activate && python3 replicator/run_evolution.py >> /var/log/scraper.log 2>&1') | crontab -
```

## Lo que hace el sistema ahora (arquitectura completa)
```
Worker (worker.py) 24/7
  └─ busca 7 productos seed cada 6h
  └─ registra errores en memoria_errores
       ↓
/evolve (cron 0 */6 * * *)
  └─ Scout lee memoria_errores → prioriza parsers rotos
  └─ Optimizer propone fix → Guardian valida → Tester → Benchmark
  └─ Si mejora ≥ 3% → aplica automáticamente (auto_approve=True)
       ↓
Worker tiene parsers mejorados → menos errores → fitness sube
```

## Endpoints disponibles
- GET /                    → UI buscador + barra de estado worker
- GET /buscar?q=...        → búsqueda manual
- GET /worker/status       → estado worker + fitness en vivo
- GET /watchlist           → productos monitorizados
- POST /watchlist          → añadir producto
- DELETE /watchlist/{id}   → desactivar producto
- GET /historial?producto= → historial de precios
- POST /alerta             → crear alerta de precio

## Tareas manuales pendientes
- **Repo a privado**: GitHub → repo scraper → Settings → Change visibility → Private
- **Rotar Gmail password**: myaccount.google.com → Seguridad → Contraseñas de aplicaciones → nueva → actualizar /opt/scraper/.env

## Contexto
- movilines, refurbed, grover, ktronix ya están en BASURA.
- Bug precio europeo 1.299,99 ya corregido.
- _buscar_parser() ya soporta subdominios.
- Python local es Microsoft Store (sin tkinter) → no se puede probar buscador_app.py en local.
