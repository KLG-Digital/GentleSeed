# ======================== IMPORTS ========================
import os
import platform
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from backend import auth as Auth
from backend import i18n
from backend import settings as Settings
from backend.engine import activity as Activity
from backend.engine import search
from backend.engine import arr_client as arr_client
from backend.engine import journal as journal
from backend.engine import store as store
from backend.engine.monitor import CHECK_EVERY, SCAN_EVENT, STATUS, STATUS_LOCK, inspect_connections
from backend.version import VERSION
from backend.routes import security
# =================================================


# ======================== PAGE SYSTÈME : ÉTAT, ACTIVITÉ, TÂCHES ET FICHIERS JOURNAUX ========================

router = APIRouter()


# --------------------- VUE D'ENSEMBLE ET ACTIVITÉ ---------------------

STARTED_AT = time.time()


# Texte court et imprimable pour l'affichage
def _short(value, limit=80):
    return "".join(ch for ch in str(value if value is not None else "") if ch.isprintable())[:limit]


# Santé et informations d'un service (lecture seule, comme la page Système de Sonarr)
def service_overview(client):
    info = {"ok": False, "health": []}
    try:
        status = client.request("GET", "system/status", timeout=15)
        info.update(ok=True, version=_short(status.get("version"), 32), branch=_short(status.get("branch"), 32),
                    os=_short(status.get("osName"), 40), docker=bool(status.get("isDocker")),
                    start_time=_short(status.get("startTime"), 40), runtime=_short(status.get("runtimeVersion"), 32),
                    app_data=_short(status.get("appData"), 120))
    except (requests.RequestException, ValueError, RuntimeError, AttributeError) as error:
        info["error"] = type(error).__name__
        return info
    try:
        for row in (client.request("GET", "health", timeout=15) or [])[:30]:
            if isinstance(row, dict):
                wiki = str(row.get("wikiUrl") or "")
                info["health"].append({"type": _short(row.get("type"), 12).lower(), "message": _short(row.get("message"), 300),
                                       "wiki": wiki if wiki.startswith("https://") and len(wiki) < 300 else ""})
    except (requests.RequestException, ValueError, RuntimeError, AttributeError):
        info["health_error"] = True
    return info


# Page Système → État : GentleSeed lui-même, puis Radarr et Sonarr
@router.get("/api/overview")
def overview(request: Request):
    security.require_login(request)
    cfg = Settings.load_settings()
    arr_client.REQUEST_TIMEOUT = cfg["REQUEST_TIMEOUT"]
    services = {client.name: service_overview(client) for client in search.clients_for(cfg)}
    with STATUS_LOCK:
        current = STATUS.copy()
    try:
        state = store.load_state()
        tracked = len(state.get("tracked", []))
    except (OSError, ValueError, TypeError):
        tracked = 0
    document = Auth.load_auth() or {}
    return {"gentleseed": {"version": VERSION, "uptime": int(time.time() - STARTED_AT), "python": platform.python_version(),
                           "data_dir": str(store.STATE_FILE.parent), "last_scan": current["last_scan"],
                           "auth_mode": document.get("mode", "?"), "tracked": tracked,
                           "auto_enabled": bool(cfg["AUTO_ENABLED"])},
            "services": services}


# Ce que le moteur fait maintenant, ce qui attend, ce qui vient de se terminer (lecture seule)
@router.get("/api/activity")
def activity(request: Request):
    security.require_login(request)
    cfg = Settings.load_settings()
    data = Activity.snapshot()
    with STATUS_LOCK:
        current = STATUS.copy()
    waiting, next_retry = 0, None
    try:
        state = store.load_state()
        attempts = state.get("last_attempt", {})
        due = [float(attempts[key]) + cfg["RETRY_INTERVAL"] for key in state.get("tracked", [])
               if key in attempts and float(attempts[key]) > 0]
        waiting = len(due)
        next_retry = min(due) if due else None
    except (OSError, ValueError, TypeError, KeyError):
        pass
    data.update({"auto_enabled": bool(cfg["AUTO_ENABLED"]), "cycle_running": bool(current["running"]),
                 "last_scan": current["last_scan"], "check_interval": cfg["CHECK_INTERVAL"],
                 "waiting_retry": waiting, "next_retry": next_retry, "dry_run": bool(cfg["DRY_RUN"])})
    return data


# Informations système et liste des tâches
@router.get("/api/system")
def system(request: Request):
    security.require_login(request)
    cfg = Settings.public_settings()
    with STATUS_LOCK:
        current = STATUS.copy()
    scheduled = None
    if cfg["AUTO_ENABLED"] and current["last_scan"]:
        scheduled = datetime.fromtimestamp(datetime.fromisoformat(current["last_scan"]).timestamp() + cfg["CHECK_INTERVAL"], timezone.utc).isoformat(timespec="seconds")
    try:
        state = store.load_state()
        tracked = set(state.get("tracked", []))
        attempts = state.get("last_attempt", {})
        due = [float(attempts[key]) + cfg["RETRY_INTERVAL"] for key in tracked if key in attempts and float(attempts[key]) > 0]
        next_retry = datetime.fromtimestamp(min(due),timezone.utc).isoformat(timespec="seconds") if due else None
        waiting = len(due)
    except (OSError, ValueError, TypeError, KeyError):
        next_retry, waiting = None, 0
    tasks = [
        {"id": "scan", "name": "Automatic monitoring", "interval": cfg["CHECK_INTERVAL"],
         "last_run": current["last_scan"], "next_run": scheduled,
         "status": "Running" if current["running"] else ("Active" if cfg["AUTO_ENABLED"] else "Paused"),
         "can_run": bool(cfg["AUTO_ENABLED"]), "log_filter": ""},
        {"id": "connections", "name": "Connection check", "interval": CHECK_EVERY,
         "last_run": current["last_connection_check"],
         "next_run": (datetime.fromtimestamp(datetime.fromisoformat(current["last_connection_check"]).timestamp()+CHECK_EVERY,timezone.utc).isoformat(timespec="seconds")
                      if current["last_connection_check"] else None),
         "status": "Running" if current["connection_check_running"] else "Available", "can_run": True,
         "log_filter": "connection"},
        {"id": "retry", "name": "Resume pending analyses", "interval": cfg["RETRY_INTERVAL"],
         "last_run": None, "next_run": next_retry,
         "status": (f"{waiting} media waiting for a new attempt" if waiting else "Nothing waiting")
                   if cfg["AUTO_ENABLED"] else "Paused",
         "can_run": bool(cfg["AUTO_ENABLED"]), "log_filter": ""},
        {"id": "manual", "name": "Manual search", "interval": None,
         "last_run": None, "next_run": None, "status": "Available", "can_run": True,
         "log_filter": ""},
    ]
    return {"version": VERSION, "platform": os.name,
            "dry_run": cfg["DRY_RUN"], "tasks": tasks}


# Déclenche un travail existant, sans forcer les transferts ni les délais de reprise
@router.post("/api/tasks/{task_id}/run")
def execute_task(task_id: str, request: Request, background: BackgroundTasks):
    security.require_write(request)
    if task_id == "connections":
        background.add_task(inspect_connections)
        return {"ok": True, "message": "Connection check requested"}
    if task_id in ("scan", "retry"):
        if not Settings.load_settings()["AUTO_ENABLED"]:
            raise HTTPException(409, "Enable automatic monitoring first")
        SCAN_EVENT.set()
        return {"ok": True, "message": "Check requested; safety delays kept"}
    raise HTTPException(400, "Task cannot be run")


# --------------------- FICHIERS JOURNAUX PERSISTANTS ---------------------
_DAILY_LOG_NAME = re.compile(r"gentleseed-\d{4}-\d{2}-\d{2}(?:\.\d+)?\.log\Z")


# Noms générés uniquement par GentleSeed, jamais des fichiers arbitraires
def available_log_files():
    folder = journal.EVENT_LOG_FILE.parent
    historical = [journal.EVENT_LOG_FILE, journal.EVENT_LOG_FILE.with_suffix(".previous.jsonl")]
    daily = folder / "logs"
    if daily.is_dir():
        historical.extend(file for file in daily.iterdir()
                          if file.is_file() and not file.is_symlink() and _DAILY_LOG_NAME.fullmatch(file.name))
    return {item.name: item for item in historical if item.is_file()}


# Liste des fichiers journaux disponibles
@router.get("/api/logfiles")
def logfiles(request: Request):
    security.require_login(request)
    files = available_log_files()
    entries = []
    for name, file in files.items():
        try:
            stats = file.stat()
        except FileNotFoundError:  # Rotation éventuelle pendant l'actualisation.
            continue
        entries.append({"name": name, "size": stats.st_size,
                        "modified": datetime.fromtimestamp(stats.st_mtime, timezone.utc).isoformat(timespec="seconds")})
    return sorted(entries, key=lambda entry: (entry["modified"], entry["name"]), reverse=True)


# --------------------- PRÉVISUALISATION SÉCURISÉE DES JOURNAUX ---------------------

# Lit la fin d'un fichier autorisé, sans téléchargement ; gros journaux tronqués, heures converties par le navigateur
@router.get("/api/logfiles/{name}/content")
def view_log_file(request: Request, name: str, lang: str = "en"):
    security.require_login(request)
    if not name or Path(name).name != name or "/" in name or "\\" in name:
        raise HTTPException(404, "File not found")
    file = available_log_files().get(name)
    if file is None:
        raise HTTPException(404, "File not found")
    maximum = 750_000
    try:
        with file.open("rb") as stream:
            stream.seek(0, 2)
            length = stream.tell()
            truncated = length > maximum
            stream.seek(max(0, length - maximum))
            if truncated:
                stream.readline()  # Ne pas afficher une ligne partiellement coupée.
            raw = stream.read(maximum)
    except OSError:
        raise HTTPException(404, "File unavailable")
    content = raw.decode("utf-8", errors="replace")
    lines = content.splitlines(keepends=True)
    # Couleur de chaque ligne, calculée sur le texte d'origine (avant traduction)
    kinds = [i18n.classify_log_line(line) for line in lines]
    content = "".join(i18n.translate_log_line(line, lang) for line in lines)
    return {"name": name, "content": content, "kinds": kinds, "truncated": truncated, "size": length}


# Télécharge un fichier journal (traduit à la volée si lang est une autre langue que l'anglais ;
# le fichier stocké reste en anglais)
@router.get("/api/logfiles/{name}")
def download_logs(request: Request, name: str, lang: str = "en"):
    security.require_login(request)
    # Pas de chemin, de sous-dossier ni de séquence ../ autorisés.
    if not name or Path(name).name != name or "/" in name or "\\" in name:
        raise HTTPException(404, "File not found")
    file = available_log_files().get(name)
    if file is None:
        raise HTTPException(404, "File not found")
    mime = "text/plain" if file.suffix == ".log" else "application/jsonl"
    if lang == "en" or lang not in i18n.SUPPORTED:
        return FileResponse(file, filename=name, media_type=mime)

    def translated():
        with file.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                yield i18n.translate_log_line(line, lang).encode("utf-8")
    return StreamingResponse(translated(), media_type=mime,
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})
# =================================================
