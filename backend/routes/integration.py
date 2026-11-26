# ======================== IMPORTS ========================
import copy
import json
import os
import threading
import time
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from backend import settings as Settings
from backend.engine import activity as Activity
from backend.engine import delivery as DeliveryTracker
from backend.engine import search
from backend.engine import diagnostics as Diagnostics
from backend.engine import journal as journal
from backend.engine.monitor import SCAN_EVENT, STOP_EVENT, WEBHOOK_LOCK, WEBHOOK_STATE, note_if_busy, schedule_new_demand
from backend.services import integration as Integration
from backend.routes import security
# =================================================


# ======================== INTÉGRATION RADARR / SONARR (WEBHOOK) ========================

router = APIRouter()


# Reçoit les événements de Radarr/Sonarr (Connect → Webhook), sans session : protégé par le jeton de l'adresse
# Ne fait que réveiller la surveillance ; le contenu n'est jamais exécuté ni stocké
@router.post("/api/webhook/{token}")
async def receive_webhook(token: str, request: Request):
    if not Integration.valid_token(token):
        raise HTTPException(404, "Not found")
    body = await security.read_body(request, Integration.MAX_BODY, "Message too large")
    try:
        payload = json.loads(body or b"{}")
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "Invalid JSON")
    if not isinstance(payload, dict):
        raise HTTPException(400, "Invalid message")
    event = payload.get("eventType")
    if not isinstance(event, str):
        event = None  # une valeur qui n'est pas du texte ne correspond à aucun événement
    instance = payload.get("instanceName")
    # Texte imprimable seulement : un retour à la ligne ne peut pas fabriquer de fausses lignes de journal
    origin = ("".join(ch for ch in instance if ch.isprintable())[:40].strip() if isinstance(instance, str) else "") or "Radarr/Sonarr"
    now = time.time()
    with WEBHOOK_LOCK:
        quiet = now - WEBHOOK_STATE["last_log"] < 2  # un import en masse ne remplit pas le journal
        if event == "Test" or event in Integration.EVENT_TYPES:
            WEBHOOK_STATE["last"] = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                     "event": "Test" if event == "Test" else event, "source": origin}
            if not quiet:
                WEBHOOK_STATE["last_log"] = now
    if event == "Test":
        journal.log(f"Test webhook received from {origin}: link operational")
        return {"ok": True, "test": True}
    service = Integration.EVENT_TYPES.get(event)
    if service is None:
        return {"ok": True, "ignored": True}
    media = payload.get("movie") if service == "radarr" else payload.get("series")
    title = media.get("title") if isinstance(media, dict) else None
    title = "".join(ch for ch in str(title or "") if ch.isprintable())[:80].strip()
    try:
        delay = Settings.load_settings()["NEW_DEMAND_DELAY"]
    except (OSError, ValueError, KeyError):
        delay = 0
    schedule_new_demand(delay)
    Activity.received(service, title)
    if not quiet:
        when = f"analysis in {delay} s" if delay > 0 else "immediate check"
        journal.log(f"Webhook received from {origin} ({Integration.SERVICE_LABELS[service]}: \"{title}\" added): {when}" if title
                     else f"Webhook received from {origin} ({Integration.SERVICE_LABELS[service]}: media added): {when}")
        note_if_busy(title)
    return {"ok": True}


# Client Radarr/Sonarr pour l'intégration (erreur claire si le service n'est pas configuré)
def integration_client(config, service):
    if not isinstance(service, str) or service not in Integration.EVENT_FLAGS:
        raise HTTPException(400, "Invalid service")
    client = next((c for c in search.clients_for(config) if c.name == service), None)
    if client is None:
        raise HTTPException(409, f"Configure {Integration.SERVICE_LABELS[service]} first in Settings → Connections")
    return client


# Traduit une erreur Radarr/Sonarr en réponse HTTP compréhensible
def integration_error(error, service):
    label = Integration.SERVICE_LABELS[service]
    if isinstance(error, requests.HTTPError):
        code = getattr(getattr(error, "response", None), "status_code", "unknown")
        if code in (401, 403):
            return HTTPException(424, Diagnostics.describe_connection_error(error, service))
        detail = ""
        try:
            rows = error.response.json()
            if isinstance(rows, list):
                detail = " ; ".join(str(r.get("errorMessage", ""))[:200] for r in rows if isinstance(r, dict))[:400]
        except (ValueError, AttributeError):
            pass
        if not detail:
            # Sans message de Radarr/Sonarr : la requête qui échoue (méthode et chemin, jamais la clé API)
            request = getattr(getattr(error, "response", None), "request", None)
            path = str(getattr(request, "path_url", "") or "").split("?")[0]
            if request is not None and path:
                detail = f"{request.method} {path}"[:200]
        return HTTPException(424, (f"{label} refused the request (HTTP {code}): {detail}" if detail else f"{label} refused the request (HTTP {code})"))
    if isinstance(error, requests.RequestException):
        return HTTPException(424, f"{label} unreachable ({type(error).__name__})")
    if isinstance(error, OSError):
        return HTTPException(503, "Settings could not be saved: check that the data folder is writable")
    return HTTPException(400, str(error)[:300] or "Operation failed")


# Port de GentleSeed sur cette machine (variable WEB_PORT, 1853 par défaut)
def web_port():
    try:
        return int(os.environ.get("WEB_PORT", "1853"))
    except ValueError:
        return 1853


# Adresse de GentleSeed pour Radarr/Sonarr : celle du navigateur s'il est sur le réseau local,
# sinon l'adresse mémorisée, sinon l'hôte de Radarr/Sonarr + port. Jamais un domaine public
def resolve_base_url(hint, config):
    if hint:
        return Integration.clean_base_url(hint)          # adresse donnée explicitement : invalide = erreur claire
    if config["INTEGRATION_BASE_URL"]:
        try:
            return Integration.clean_base_url(config["INTEGRATION_BASE_URL"])
        except ValueError:
            pass
    suggested = Integration.suggest_base_url([config["RADARR_URL"], config["SONARR_URL"]], web_port())
    if not suggested:
        raise ValueError("GentleSeed's local address not found: open GentleSeed from its address on the local network (for example http://192.168.1.10:1853)")
    return suggested


# État du webhook dans Radarr et Sonarr, dernier message reçu et réglages mémorisés
@router.get("/api/integration")
async def get_integration(request: Request, base_url: str = ""):
    security.require_login(request)
    config = Settings.load_settings()
    try:
        base_url = resolve_base_url(base_url or None, config)
    except ValueError:
        base_url = ""
    services = {}
    for service in Integration.EVENT_FLAGS:
        configured = bool(config[f"{service.upper()}_API_KEY"] and config[f"{service.upper()}_URL"])
        if not configured:
            services[service] = {"state": "unconfigured", "message": "Connection not configured"}
            continue
        try:
            client = integration_client(config, service)
            items = await run_in_threadpool(client.notification_list)
            services[service] = Integration.describe(service, items, base_url or None)
        except HTTPException:
            raise
        except (requests.RequestException, RuntimeError, ValueError) as error:
            services[service] = {"state": "error", "message": integration_error(error, service).detail}
    try:
        manual = Integration.webhook_url(base_url) if base_url else None
    except ValueError:
        manual = None
    return {"services": services, "webhook_url": manual, "last_webhook": WEBHOOK_STATE["last"],
            "config": {"base_url": config["INTEGRATION_BASE_URL"], "cleanup": config["INTEGRATION_CLEANUP"],
                       "radarr": config["INTEGRATION_RADARR"], "sonarr": config["INTEGRATION_SONARR"]}}


# Installe ou met à jour la notification GentleSeed dans Radarr/Sonarr (bloquant : à lancer dans un thread)
def install_service_integration(config, service, base_url, cancelled=lambda: False):
    client = integration_client(config, service)
    url = Integration.webhook_url(base_url)
    items = client.notification_list()  # d'abord une lecture : fixe aussi la version d'API
    existing = Integration.find_ours(items)
    body = Integration.build_body(service, [] if existing else client.notification_schema(), url, existing)
    if cancelled():  # arrêt demandé pendant les lectures : rien à écrire
        return None
    client.notification_save(body)
    return Integration.describe(service, client.notification_list(), base_url)


# Mémorise ce que GentleSeed doit maintenir dans Radarr/Sonarr (nettoyage et restauration au démarrage)
# Sous le verrou des réglages : une modification faite au même moment n'est pas écrasée
def remember_integration(service, installed, base_url=None):
    with Settings.LOCK:
        config = Settings.load_settings()
        config[f"INTEGRATION_{service.upper()}"] = bool(installed)
        if base_url:
            config["INTEGRATION_BASE_URL"] = Integration.clean_base_url(base_url)
        Settings.save_settings(config)


# Installe ou met à jour le webhook GentleSeed dans Radarr/Sonarr
@router.post("/api/integration/install")
async def install_integration(request: Request):
    security.require_write(request)
    payload = await security.read_integration_payload(request)
    service = payload.get("service")
    config = Settings.load_settings()
    integration_client(config, service)
    try:
        base = resolve_base_url(payload.get("base_url"), config)
        result = await run_in_threadpool(install_service_integration, config, service, base)
        remember_integration(service, True, base)
    except (requests.RequestException, RuntimeError, ValueError, OSError) as error:
        journal.log(f"Integration {service.title()}: installation impossible ({Diagnostics.error_text(error, service)})", level="WARN")
        raise integration_error(error, service) from error
    journal.log(f"Integration {service.title()}: GentleSeed webhook installed in {Integration.SERVICE_LABELS[service]}")
    return {"ok": True, **result}


# Retire le webhook GentleSeed de Radarr/Sonarr
@router.post("/api/integration/remove")
async def remove_integration(request: Request):
    security.require_write(request)
    payload = await security.read_integration_payload(request)
    service = payload.get("service")
    client = integration_client(Settings.load_settings(), service)
    try:
        def work():
            ours = Integration.find_ours(client.notification_list())
            if ours is None:
                return False
            try:
                client.notification_delete(ours["id"])
            except requests.HTTPError as error:
                # 404 : la notification a déjà été supprimée côté Radarr/Sonarr, le résultat voulu est atteint
                if error.response is None or error.response.status_code != 404:
                    raise
                return False
            return True
        removed = await run_in_threadpool(work)
        remember_integration(service, False)
    except (requests.RequestException, RuntimeError, ValueError, KeyError, OSError) as error:
        raise integration_error(error, service) from error
    if removed:
        journal.log(f"Integration {service.title()}: GentleSeed webhook removed from {Integration.SERVICE_LABELS[service]}")
    return {"ok": True, "removed": removed}


# Demande à Radarr/Sonarr d'envoyer un message de test : vérifie la liaison de bout en bout
@router.post("/api/integration/test")
async def test_integration(request: Request):
    security.require_write(request)
    payload = await security.read_integration_payload(request)
    service = payload.get("service")
    client = integration_client(Settings.load_settings(), service)
    try:
        def work():
            ours = Integration.find_ours(client.notification_list())
            if ours is None:
                raise ValueError("The webhook is not installed: click Install first")
            client.notification_test(ours)
        await run_in_threadpool(work)
    except (requests.RequestException, RuntimeError, ValueError) as error:
        raise integration_error(error, service) from error
    return {"ok": True, "message": f"{Integration.SERVICE_LABELS[service]} can reach GentleSeed"}


# Régénère le jeton secret du webhook (les webhooks installés doivent être réinstallés)
@router.post("/api/integration/token")
async def regenerate_integration_token(request: Request):
    security.require_write(request)
    Integration.regenerate_token()
    journal.log("Integration: webhook token regenerated (reinstall the webhook in Radarr/Sonarr)", level="WARN")
    return {"ok": True}


# --------------------- RETRAIT À L'ARRÊT ET REMISE EN PLACE AU DÉMARRAGE ---------------------

# Temps total du retrait à l'arrêt, nettement sous les 30 s laissées par Docker
REMOVAL_SECONDS = 15


# Réinstallation au démarrage et retrait à l'arrêt ne se croisent jamais pour un même service
RESTORE_LOCKS = {service: threading.Lock() for service in Integration.EVENT_FLAGS}


# Option « Retirer l'intégration à l'arrêt » : rien ne reste dans Radarr/Sonarr si GentleSeed est supprimé
# Rapide et sans danger : délai court, en parallèle, toute erreur est ignorée
def integration_remove_on_stop():
    config = Settings.load_settings()
    if not config["INTEGRATION_CLEANUP"]:
        return

    def one(service):
        # Attend la fin d'une réinstallation en cours (4), sans bloquer l'arrêt indéfiniment
        locked = RESTORE_LOCKS[service].acquire(timeout=5)
        try:
            # Copie : le client d'origine est partagé avec le moteur, qui doit garder son délai normal
            client = copy.copy(integration_client(config, service))
            client.timeout = 5
            ours = Integration.find_ours(client.notification_list())
            if ours is not None:
                client.notification_delete(ours["id"])
                journal.log(f"Integration {service.title()}: GentleSeed webhook removed at shutdown")
        except (HTTPException, requests.RequestException, RuntimeError, ValueError, KeyError) as error:
            journal.log(f"Integration {service.title()}: removal at shutdown impossible ({Diagnostics.error_text(error, service)})", level="WARN")
        finally:
            if locked:
                RESTORE_LOCKS[service].release()
    threads = [threading.Thread(target=one, args=(service,), daemon=True)
               for service in Integration.EVENT_FLAGS if config[f"INTEGRATION_{service.upper()}"]]
    deadline = time.monotonic() + REMOVAL_SECONDS
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=max(0, deadline - time.monotonic()))


# Remet en place ce que le nettoyage à l'arrêt a retiré (seulement si l'option est activée)
def integration_restore_on_start():
    for _ in range(6):                                  # Radarr/Sonarr peuvent démarrer après GentleSeed
        config = Settings.load_settings()
        if not (config["INTEGRATION_CLEANUP"] and config["INTEGRATION_BASE_URL"]):
            return
        pending = False
        for service in Integration.EVENT_FLAGS:
            if not config[f"INTEGRATION_{service.upper()}"]:
                continue
            try:
                with RESTORE_LOCKS[service]:
                    client = integration_client(config, service)
                    state = Integration.describe(service, client.notification_list(), config["INTEGRATION_BASE_URL"])["state"]
                    if STOP_EVENT.is_set():
                        return  # arrêt demandé : ne rien réinstaller
                    if state != "active":
                        install_service_integration(config, service, config["INTEGRATION_BASE_URL"], STOP_EVENT.is_set)
                        if STOP_EVENT.is_set():
                            # L'enregistrement était peut-être déjà parti quand l'arrêt a été demandé : on le retire
                            ours = Integration.find_ours(client.notification_list())
                            if ours is not None:
                                client.notification_delete(ours["id"])
                            return
                        journal.log(f"Integration {service.title()}: GentleSeed webhook reinstalled at startup")
            except (HTTPException, requests.RequestException, RuntimeError, ValueError, KeyError):
                pending = True
        if not pending or STOP_EVENT.wait(20):
            return


# Derniers envois à Radarr/Sonarr et leur suivi
@router.get("/api/deliveries")
def get_deliveries(request: Request):
    security.require_login(request)
    try:
        entries = DeliveryTracker.load()
    except (OSError, ValueError):
        raise HTTPException(503, "Delivery history unavailable")
    return entries[-50:][::-1]


# --------------------- RECHERCHE AUTOMATIQUE MANUELLE ---------------------
# Lance tout de suite une vérification complète
@router.post("/api/scan")
def scan(request: Request):
    security.require_write(request)
    if not Settings.load_settings()["AUTO_ENABLED"]:
        raise HTTPException(409, "Enable automatic monitoring first")
    SCAN_EVENT.set()
    return {"ok": True, "message": "Monitoring cycle requested"}
# =================================================
