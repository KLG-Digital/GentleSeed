#!/usr/bin/env python3
# Lancement local sans Docker : python main.py
#
# Docker n'utilise PAS ce fichier : il lance directement `uvicorn backend.webui:app` (voir Dockerfile),
# avec les données dans /data.

# ======================== IMPORTS ========================
import os
from pathlib import Path
# =================================================


# ======================== CONFIGURATION ========================
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Valeurs par défaut locales ; toute variable déjà définie reste prioritaire
os.environ.setdefault("SETTINGS_FILE", str(DATA_DIR / "settings.json"))
os.environ.setdefault("STATE_FILE", str(DATA_DIR / "state.json"))
os.environ.setdefault("EVENT_LOG_FILE", str(DATA_DIR / "events.jsonl"))
os.environ.setdefault("SESSION_SECRET_FILE", str(DATA_DIR / ".web-secret"))
os.environ.setdefault("AUTH_FILE", str(DATA_DIR / "auth.json"))

# Valeur de départ prudente (modifiable dans l'interface) : surveillance arrêtée tant qu'on ne l'active pas
os.environ.setdefault("AUTO_ENABLED", "false")
# =================================================


# ======================== LANCEMENT ========================

def main():
    import uvicorn
    from backend.routes import service_control
    from backend.webui import app
    # Même règle que Docker. WEB_HOST=0.0.0.0 pour écouter sur le réseau (par défaut : cette machine)
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "1853"))
    print(f"GentleSeed: http://{host}:{port}  (data: {DATA_DIR})")
    # Le serveur est supervisé ici : les boutons « Redémarrer » et « Arrêter » de l'interface agissent dessus
    while True:
        server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, workers=1, access_log=False))
        service_control.attach_local_server(server)
        server.run()
        if service_control.detach_local_server() != "restart":
            break
# =================================================


if __name__ == "__main__":
    main()
