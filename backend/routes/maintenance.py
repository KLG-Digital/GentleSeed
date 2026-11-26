# ======================== IMPORTS ========================
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from backend import settings as Settings
from backend.engine import journal as journal
from backend.engine import store as store
from backend.engine.monitor import SCAN_EVENT, STOP_EVENT
from backend.engine.search import OPERATION_LOCK, configure_engine
from backend.services import backup as Backup
from backend.services import updates as Updates
from backend.routes import security
# =================================================


# ======================== MISES À JOUR ET SAUVEGARDES ========================

router = APIRouter()


# --------------------- MISES À JOUR ---------------------

# Historique des versions du dépôt : informe seulement, rien n'est installé automatiquement
@router.get("/api/updates")
def updates(request: Request, refresh: bool = False):
    security.require_login(request)
    cfg = Settings.load_settings()
    base = {"current": Updates.CURRENT, "enabled": cfg["UPDATE_CHECK"], "repo": cfg["UPDATE_REPO"],
            "docker_image": Updates.DOCKER_IMAGE, "docker_url": Updates.DOCKER_URL}
    if not cfg["UPDATE_CHECK"]:
        return {**base, "state": "disabled"}
    if not cfg["UPDATE_REPO"]:
        return {**base, "state": "no_repo"}
    try:
        return {**base, "state": "ok", **Updates.check(cfg["UPDATE_REPO"], force=refresh)}
    except RuntimeError as error:
        return {**base, "state": "error", "error": str(error), **(Updates.cached() or {})}


# Vérifie une fois peu après le démarrage puis toutes les 12 h (silencieux en cas d'échec)
def update_worker():
    if STOP_EVENT.wait(30):
        return
    while not STOP_EVENT.is_set():
        try:
            cfg = Settings.load_settings()
            if cfg["UPDATE_CHECK"] and cfg["UPDATE_REPO"]:
                Updates.check(cfg["UPDATE_REPO"], force=True)
        except (RuntimeError, OSError, ValueError):
            pass
        if STOP_EVENT.wait(12 * 3600):
            return


# --------------------- SAUVEGARDES ---------------------

# Traduit une erreur de sauvegarde en réponse HTTP
def backup_error(error):
    return HTTPException(400 if isinstance(error, Backup.BackupError) else 500, str(error) if isinstance(error, Backup.BackupError) else "Backup failed")


# Liste des sauvegardes
@router.get("/api/backups")
def backups_list(request: Request):
    security.require_login(request)
    return {"items": Backup.listing(), "keep": Backup.KEEP, "keep_safety": Backup.KEEP_SAFETY}


# Crée une sauvegarde des réglages (clés API seulement si demandé)
@router.post("/api/backups")
async def backups_create(request: Request):
    security.require_write(request)
    payload = await security.read_integration_payload(request)
    include_keys = payload.get("include_keys") is True
    try:
        name = await run_in_threadpool(lambda: Backup.create(Settings.load_settings(), include_keys))
    except (OSError, ValueError) as error:
        raise backup_error(error) from error
    journal.log(f"Backup created: {name}" + (" (API keys included)" if include_keys else ""))
    return {"ok": True, "name": name}


# Télécharge une sauvegarde
@router.get("/api/backups/{name}")
def backups_download(request: Request, name: str):
    security.require_login(request)
    try:
        path = Backup.path_for(name)
    except Backup.BackupError as error:
        raise HTTPException(404, "Backup not found") from error
    return FileResponse(path, filename=name, media_type="application/json")


# Supprime une sauvegarde
@router.post("/api/backups/{name}/delete")
def backups_delete(request: Request, name: str):
    security.require_write(request)
    try:
        Backup.delete(name)
    except Backup.BackupError as error:
        raise HTTPException(404, "Backup not found") from error
    journal.log(f"Backup deleted: {name}")
    return {"ok": True}


# Restaure depuis une sauvegarde de la liste ou un fichier importé ; copie de sécurité faite avant
@router.post("/api/backups/restore")
async def backups_restore(request: Request):
    security.require_write(request)
    payload = await security.read_integration_payload(request, Backup.MAX_BYTES + 4096, "Backup too large")
    try:
        document = Backup.load_file(payload["name"]) if "name" in payload else payload.get("content")
        Backup.parse(document)  # refus immédiat d'un fichier invalide
        def work():
            with OPERATION_LOCK, Settings.LOCK:
                # Fusion avec les réglages actuels sous le verrou : rien d'enregistré entre-temps n'est perdu
                config, state_part = Backup.parse(document)
                current = Settings.load_settings()
                safety = Backup.create(current, include_keys=True, tag="pre-restore")
                # parse() a déjà validé le document ; la clé actuelle ne suit pas vers une autre adresse
                cleared = Settings.moved_without_key(current, config, document.get("settings", {}))
                for service in cleared:
                    config[f"{service}_API_KEY"] = ""
                    journal.log(f"[{service.lower()}] The backup changes the address without a key: "
                                "enter the API key again", level="WARN")
                Settings.save_settings(config)
                if state_part:  # seulement dans les anciennes sauvegardes, qui contenaient l'état du moteur
                    state = store.load_state()
                    state.update(state_part)
                    store.save_state(state)
                configure_engine(config)
                return safety, [service.title() for service in cleared]
        safety, cleared = await run_in_threadpool(work)
    except (Backup.BackupError, OSError, ValueError) as error:
        raise backup_error(error) from error
    journal.log("Settings restored from a backup (safety copy: " + safety + ")")
    SCAN_EVENT.set()
    return {"ok": True, "safety": safety, "cleared": cleared}
# =================================================
