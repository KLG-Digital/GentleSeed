# ======================== IMPORTS ========================
import os
import signal
import threading
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from backend.engine import journal as journal
from backend.routes import security
# =================================================


# ======================== COMMANDES DU SERVICE (ARRÊT ET REDÉMARRAGE) ========================

router = APIRouter()


# Lancement sans Docker : main.py supervise Uvicorn (arrêt, redémarrage). L'interface ne commande jamais Docker ni le PC
LOCAL_SERVER_LOCK = threading.Lock()
LOCAL_SERVER = None
LOCAL_ACTION = None


# Associe le serveur Uvicorn à sa commande de contrôle locale
def attach_local_server(server):
    global LOCAL_SERVER, LOCAL_ACTION
    with LOCAL_SERVER_LOCK:
        LOCAL_SERVER = server
        LOCAL_ACTION = None


# Renvoie le dernier ordre reçu une fois le serveur complètement arrêté
def detach_local_server():
    global LOCAL_SERVER, LOCAL_ACTION
    with LOCAL_SERVER_LOCK:
        action = LOCAL_ACTION
        LOCAL_SERVER = None
        LOCAL_ACTION = None
    return action


# Vrai dans l'image Docker : l'arrêt du processus fait relancer le conteneur (restart: unless-stopped)
def in_container():
    return os.environ.get("GENTLESEED_CONTAINER") == "1"


# Docker : se termine proprement (SIGTERM) pour que le conteneur soit relancé
def restart_by_exit():
    time.sleep(0.6)
    os.kill(os.getpid(), signal.SIGTERM)


# Boutons du menu, pour tout utilisateur connecté (aussi derrière un proxy, comme Radarr/Sonarr).
# Docker : seul « Redémarrer » existe, « Arrêter » serait annulé par la politique de redémarrage
def service_controls(request):
    with LOCAL_SERVER_LOCK:
        supervised = LOCAL_SERVER is not None
    return {"restart": supervised or in_container(), "stop": supervised}


# Demande un arrêt gracieux après l'envoi de la réponse HTTP
def terminate_local_server(server):
    time.sleep(0.4)
    server.should_exit = True


# Arrête ou redémarre GentleSeed (seulement cette instance)
@router.post("/api/service/{action}")
def control_service(action: str, request: Request, background: BackgroundTasks):
    security.require_write(request)
    if action not in ("restart", "stop"):
        raise HTTPException(400, "Unknown command")
    global LOCAL_ACTION
    with LOCAL_SERVER_LOCK:
        supervised = LOCAL_SERVER is not None
        if LOCAL_ACTION is not None or (not supervised and not (in_container() and action == "restart")):
            raise HTTPException(409, "Service control is not available")
        server = LOCAL_SERVER
        LOCAL_ACTION = action
    journal.log("Service restart requested from the interface" if action == "restart"
                 else "Service shutdown requested from the interface")
    if server is None:
        background.add_task(restart_by_exit)
    else:
        background.add_task(terminate_local_server, server)
    return {"ok": True, "action": action,
            "message": "Restart requested" if action == "restart" else "Shutdown requested"}
# =================================================
