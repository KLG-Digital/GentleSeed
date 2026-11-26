# ======================== IMPORTS ========================
import threading
import time
from datetime import datetime, timezone

import requests

from backend import settings as Settings
from backend.engine import delivery as DeliveryTracker
from backend.engine import search
from backend.engine import selector as selector
from backend.engine import arr_client as arr_client
from backend.engine import journal as journal
from backend.engine import store as store
from backend.engine.search import OPERATION_LOCK, configure_engine
from backend.version import VERSION
# =================================================


# ======================== ÉTAT PARTAGÉ ========================

# Événements qui réveillent ou arrêtent la boucle de surveillance
SCAN_EVENT = threading.Event()
STOP_EVENT = threading.Event()
STATUS_LOCK = threading.RLock()

# État affiché par l'interface (dernier passage, connexions, erreurs)
STATUS = {"last_scan": None, "last_error": None, "running": False, "last_preview": None,
          "connections": {}, "last_connection_check": None, "last_connection_error": None,
          "connection_check_running": False, "scan_cycles": 0}
CONNECTION_CHECK_LOCK = threading.Lock()
CHECK_EVERY = 300

# Webhook : dernier message reçu et réveil programmé (partagé avec la route de réception)
WEBHOOK_STATE = {"last": None, "last_log": 0.0, "wake_at": None}
WEBHOOK_LOCK = threading.Lock()
# =================================================


# ======================== DIAGNOSTIC DES CONNEXIONS ========================

# Contrôle en lecture seule : jamais de commande de téléchargement
def inspect_connections():
    if not CONNECTION_CHECK_LOCK.acquire(blocking=False):
        return False
    with STATUS_LOCK:
        STATUS["connection_check_running"] = True
    try:
        config = Settings.load_settings()
        results = {}
        for service in ("radarr", "sonarr"):
            url = config[f"{service.upper()}_URL"]
            key = config[f"{service.upper()}_API_KEY"]
            if not url or not key:
                results[service] = None  # non configuré, pas une panne
                continue
            try:
                client = arr_client.ArrClient(service, url, key)
                data = client.request("GET", "system/status")
                if not isinstance(data, dict) or not data.get("version"):
                    raise RuntimeError("Invalid status response")
                results[service] = True
            except (requests.RequestException, ValueError, RuntimeError, KeyError, TypeError):
                results[service] = False
        with STATUS_LOCK:
            previous_connections = STATUS.get("connections", {}).copy()
            STATUS["connections"] = results
            STATUS["last_connection_check"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            STATUS["last_connection_error"] = None
        # Pas d'événement identique toutes les 5 minutes : on ne note que les changements
        if previous_connections != results:
            labels = {True: "connected", False: "unreachable", None: "not configured"}
            for name, state in results.items():
                if previous_connections.get(name) != state:
                    journal.log(f"{name.capitalize()} connection state changed: {labels[state]}")
        return True
    except (OSError, ValueError, RuntimeError) as error:
        with STATUS_LOCK:
            STATUS["last_connection_error"] = type(error).__name__
        journal.log(f"Connection check unavailable: {type(error).__name__}", level="WARN")
        return False
    finally:
        with STATUS_LOCK:
            STATUS["connection_check_running"] = False
        CONNECTION_CHECK_LOCK.release()
# =================================================


# ======================== SONDAGE DES NOUVELLES DEMANDES ========================

# Met à jour baseline ({service: nombre de manquants}) et renvoie les hausses {service: (avant, après)}.
# Une requête minuscule par service ; toute erreur est ignorée (le cycle complet prend le relais)
def probe_demand(baseline):
    risen = {}
    try:
        config = Settings.load_settings()
        if not config["AUTO_ENABLED"]:
            return {}
        clients = search.clients_for(config)
    except (OSError, ValueError, KeyError):
        return {}
    for client in clients:
        try:
            count = client.demand_count()
        except (requests.RequestException, RuntimeError, ValueError) as error:
            journal.log(f"[{client.name}] Poll unavailable: {type(error).__name__}", level="DEBUG")
            continue
        previous = baseline.get(client.name)
        baseline[client.name] = count
        if previous is not None and count != previous:
            journal.log(f"[{client.name}] Missing count: {previous} → {count}", level="DEBUG")
        if previous is not None and count > previous:
            risen[client.name] = (previous, count)
    return risen


# Une recherche tourne déjà : la demande attend sa fin, puis sera traitée en premier
def note_if_busy(title=""):
    with STATUS_LOCK:
        busy = bool(STATUS.get("running"))
    if busy:
        if title:
            journal.log(f"Request \"{title}\" added to the GentleSeed queue: it will be searched first "
                        "as soon as the current search is finished")
        else:
            journal.log("Request added to the GentleSeed queue: it will be searched first "
                        "as soon as the current search is finished")


# Programme la vérification dans delay secondes (0 = tout de suite) ; un rappel déjà prévu est conservé
def schedule_new_demand(delay):
    if delay <= 0:
        SCAN_EVENT.set()
        return
    with WEBHOOK_LOCK:
        if WEBHOOK_STATE.get("wake_at") is None:
            WEBHOOK_STATE["wake_at"] = time.monotonic() + delay


# Attend le prochain cycle complet :
# - sondage léger toutes les PROBE_INTERVAL s (une hausse programme la vérification)
# - webhook Radarr/Sonarr : même programmation
# - NEW_DEMAND_DELAY s avant d'analyser un nouveau média (évite de doubler la recherche de Radarr/Sonarr)
# - demande manuelle (SCAN_EVENT) : immédiat ; sinon cycle complet après CHECK_INTERVAL s
def wait_for_next_cycle(baseline):
    started = time.monotonic()
    next_probe = started
    while not STOP_EVENT.is_set():
        try:
            config = Settings.load_settings()
            full, probe, delay = config["CHECK_INTERVAL"], config["PROBE_INTERVAL"], config["NEW_DEMAND_DELAY"]
        except (OSError, ValueError, KeyError):
            full, probe, delay = 300, 15, 0
        now = time.monotonic()
        if now - started >= full:
            return
        with WEBHOOK_LOCK:
            due = WEBHOOK_STATE.get("wake_at")
            if due is not None and now >= due:
                WEBHOOK_STATE["wake_at"] = None
                return
        if now >= next_probe:
            next_probe = now + probe
            risen = probe_demand(baseline)
            if risen:
                detail = ", ".join(f"{name}: {before} → {after}" for name, (before, after) in risen.items())
                journal.log(f"New request detected ({detail}): analysis in {delay} s" if delay > 0
                             else f"New request detected ({detail}): immediate check")
                schedule_new_demand(delay)
                note_if_busy()
        wait = max(0.02, min(1.0, next_probe - time.monotonic(), full - (time.monotonic() - started)))
        if SCAN_EVENT.wait(wait):
            SCAN_EVENT.clear()
            return
# =================================================


# ======================== BOUCLE PRINCIPALE ========================

UNCONFIGURED_WARNED = {"done": False}

# Un seul moteur de recherche : un passage à chaque cycle
def worker():
    journal.log("─" * 20 + " Startup " + "─" * 20)  # sépare les sessions dans les journaux
    journal.log(f"GentleSeed v{VERSION}: web interface and engine started")
    # L'état est relu à chaque cycle ; s'il est illisible, le cycle échoue et sera réessayé : on ne l'efface jamais

    while not STOP_EVENT.is_set():
        # Référence du sondage prise AVANT le cycle : une demande arrivée pendant le cycle
        # la dépasse et déclenche aussitôt le suivant
        baseline = {}
        probe_demand(baseline)
        try:
            config = Settings.load_settings()
            if config["AUTO_ENABLED"]:
                with OPERATION_LOCK:
                    configure_engine(config)
                    clients = search.clients_for(config)
                    if clients:
                        UNCONFIGURED_WARNED["done"] = False
                        with STATUS_LOCK:
                            STATUS["running"] = True
                        # L'état est rechargé avant chaque cycle : un choix manuel fait entre deux
                        # cycles ne perd pas sa réservation anti-doublon
                        state = store.load_state()
                        selector.check_once(
                            clients, state, local_auto_test=False,
                            # Une nouvelle demande (webhook ou sondage) interrompt l'arriéré
                            interrupt=lambda: SCAN_EVENT.is_set() or WEBHOOK_STATE.get("wake_at") is not None)
                        with STATUS_LOCK:
                            STATUS["last_scan"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                            STATUS["scan_cycles"] += 1
                            STATUS["last_error"] = None
                    elif not UNCONFIGURED_WARNED["done"]:
                        # Une seule fois, pour ne pas remplir le journal toutes les 5 minutes
                        UNCONFIGURED_WARNED["done"] = True
                        journal.log("Configure Radarr or Sonarr from the web interface", level="WARN")
            with STATUS_LOCK:
                last_check = STATUS["last_connection_check"]
            try:
                due = not last_check or (datetime.now(timezone.utc) - datetime.fromisoformat(last_check)).total_seconds() >= CHECK_EVERY
            except ValueError:
                due = True
            if due:
                inspect_connections()
        except Exception as error:  # le moteur ne doit jamais s'arrêter sur une erreur imprévue
            journal.log(f"Monitoring error: {error}", level="ERROR")
            with STATUS_LOCK:
                STATUS["last_error"] = str(error)
        finally:
            with STATUS_LOCK:
                STATUS["running"] = False
        wait_for_next_cycle(baseline)
# =================================================


# ======================== SUIVI DES TRANSMISSIONS ========================

# Observe la file et l'historique de Radarr/Sonarr, sans relancer de téléchargement
def track_deliveries_worker():
    while not STOP_EVENT.wait(20):
        try:
            current = Settings.load_settings()
            DeliveryTracker.poll(search.clients_for(current))
        except (OSError, ValueError, RuntimeError, requests.RequestException) as error:
            journal.log(f"Delivery tracking unavailable: {type(error).__name__}", level="DEBUG")
# =================================================
