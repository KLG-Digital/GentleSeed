# ======================== IMPORTS ========================
import json
import threading
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from backend import auth as Auth
from backend import settings as Settings
from backend.engine import delivery as DeliveryTracker
from backend.engine import journal as journal
from backend.engine import store as store
from backend.engine.monitor import SCAN_EVENT, STATUS, STATUS_LOCK, inspect_connections
from backend.services import updates as Updates
from backend.version import VERSION
from backend.routes import security
from backend.routes import service_control
# =================================================


# ======================== ÉTAT, RÉGLAGES ET JOURNAUX ========================

router = APIRouter()


# --------------------- ÉTAT GÉNÉRAL ---------------------
# État général : moteur, connexions, dernier passage, version et boutons du menu
@router.get("/api/status")
def status(request: Request):
    security.require_login(request)
    config = Settings.public_settings()
    with STATUS_LOCK:
        result = STATUS.copy()
    result.update({
        "dry_run": config["DRY_RUN"], "auto_enabled": config["AUTO_ENABLED"],
        "radarr_configured": config["RADARR_API_KEY_SET"] and bool(config["RADARR_URL"]),
        "sonarr_configured": config["SONARR_API_KEY_SET"] and bool(config["SONARR_URL"]),
        "csrf": security.csrf_for(request),
        "username": request.session.get("username", "Local"),
        "auth_mode": Auth.load_auth()["mode"],
        "version": VERSION,
        "data_dir": str(Settings.SETTINGS_FILE.parent),
        "service_controls": service_control.service_controls(request),
    })
    known = Updates.cached() if config["UPDATE_CHECK"] and config["UPDATE_REPO"] else None
    result.update({"update_available": bool(known and known["update_available"]),
                   "latest_version": known["latest"] if known else None})
    try:
        state = store.load_state()
        result.update({"tracked": len(state.get("tracked", [])),
                       "known": len(state.get("known", [])),
                       "initialized": bool(state.get("initialized"))})
    except (OSError, ValueError, json.JSONDecodeError):
        result.update({"tracked": None, "known": None, "initialized": False})
    # --------------------- ETAT DU MOTEUR ---------------------
    configured = [name for name in ("radarr", "sonarr") if result[f"{name}_configured"]]
    health = result.get("connections", {})
    if not result["auto_enabled"]:
        engine_state, engine_detail = "paused", "Monitoring disabled"
    elif not configured:
        engine_state, engine_detail = "degraded", "No service connected"
    elif result["last_error"]:
        engine_state, engine_detail = "degraded", "Error during the last analysis"
    elif any(health.get(name) is False for name in configured):
        engine_state, engine_detail = "degraded", "A service is not responding"
    elif result["running"]:
        engine_state, engine_detail = "running", "Analysis in progress"
    elif not result["last_scan"] or any(health.get(name) is None for name in configured):
        engine_state, engine_detail = "starting", "Check pending"
    else:
        engine_state, engine_detail = "operational", "Monitoring and connections active"
    result["engine_state"] = engine_state
    result["engine_detail"] = engine_detail
    result["next_scan"] = (datetime.fromisoformat(result["last_scan"]).timestamp() + config["CHECK_INTERVAL"]
                            if result["auto_enabled"] and result["last_scan"] else None)
    # Une carte « En attente » sans contexte n'apporte pas d'information utile.
    try:
        result["delivery_recent"] = DeliveryTracker.load()[-1:]
    except (OSError, ValueError):
        result["delivery_recent"] = []
    try:
        state = store.load_state()
        result["auto_test_armed"] = bool(float(state.get("auto_test_armed_until", 0)) > time.time())
    except (OSError, ValueError, TypeError):
        result["auto_test_armed"] = False
    return result


# --------------------- PARAMÈTRES ---------------------
# Réglages sans les clés API
@router.get("/api/settings")
def get_settings(request: Request):
    security.require_login(request)
    return Settings.public_settings()


# Enregistre les réglages (validés) et relance la surveillance
@router.post("/api/settings")
async def change_settings(request: Request):
    security.require_write(request)
    data = await security.read_json(request)
    def work():
        with Settings.LOCK:  # lecture, fusion et écriture d'un seul tenant (même verrou que la restauration)
            before = Settings.load_settings()
            config = Settings.validate_settings(data)
            moved = Settings.moved_without_key(before, config, data)
            if moved:
                raise ValueError(f"Enter the {moved[0].title()} API key again to change its address")
            Settings.save_settings(config)
            return before, config
    try:
        before, config = await run_in_threadpool(work)
        journal.LOG_LEVEL = config["LOG_LEVEL"]
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error)) from error
    # Chaque réglage modifié est noté « ancien → nouveau » ; les clés API ne sont jamais écrites dans le journal
    changes = []
    for key, value in config.items():
        if before.get(key) == value:
            continue
        if key in Settings.API_KEYS:
            changes.append(f"{key} changed")
        elif isinstance(value, list):
            old = before.get(key) or []
            added = [f"+{name}" for name in value if name not in old]
            removed = [f"-{name}" for name in old if name not in value]
            changes.append(f"{key} {', '.join((added + removed)[:10])}")
        else:
            shown = lambda item: "(empty)" if item in ("", None) else str(item)[:60]
            changes.append(f"{key} {shown(before.get(key))} → {shown(value)}")
    if changes:
        journal.log(f"Configuration updated from the web interface: {', '.join(changes)}")
    else:
        journal.log("Configuration updated from the web interface", level="DEBUG")  # rien de modifié : pas de bruit
    # Adresse ou clé modifiée : l'ancien état de connexion ne vaut plus, on le remplace par un nouveau contrôle
    changed = [name for name in ("radarr", "sonarr")
               if any(before[f"{name.upper()}_{field}"] != config[f"{name.upper()}_{field}"] for field in ("URL", "API_KEY"))]
    if changed:
        with STATUS_LOCK:
            for name in changed:
                STATUS.setdefault("connections", {})[name] = None
        threading.Thread(target=inspect_connections, name="gs-connections", daemon=True).start()
    SCAN_EVENT.set()  # Application automatique à la prochaine passe.
    return {"ok": True, "settings": Settings.public_settings()}


# --------------------- JOURNAUX ---------------------
# Derniers événements du journal (filtrés par niveau)
@router.get("/api/logs")
def get_logs(request: Request, limit: int = 100, level: str = "ALL"):
    security.require_login(request)
    limit = max(1, min(limit, 300))
    if level not in ("ALL", "INFO", "WARN", "ERROR", "DEBUG"):
        raise HTTPException(400, "Invalid log level")
    try:
        if not journal.EVENT_LOG_FILE.exists():
            return []
        # Fichier plafonné à 2 Mo par le moteur ; lecture de sa fin uniquement.
        with journal.EVENT_LOG_FILE.open("rb") as stream:
            stream.seek(0, 2)
            offset = max(0, stream.tell() - 250_000)
            stream.seek(offset)
            data = stream.read().decode("utf-8", errors="replace")
        lines = data.splitlines()
        if offset and lines:
            lines = lines[1:]  # La première entrée peut être tronquée.
        events = []
        for line in lines[-1000:]:
            try:
                event = json.loads(line)
                if level == "ALL" or event.get("level") == level:
                    events.append(event)
            except (ValueError, TypeError):
                continue
        return events[-limit:]
    except OSError as error:
        raise HTTPException(500, f"Cannot read the logs: {error}") from error
# =================================================
