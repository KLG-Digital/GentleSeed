# ======================== IMPORTS ========================
import itertools
import threading
import time
from collections import deque
# =================================================


# ======================== CONFIGURATION ========================
MAX_QUEUE = 60
MAX_INBOX = 20
MAX_RECENT = 40

# Tout est en mémoire : l'historique complet reste dans les journaux
_LOCK = threading.Lock()
_IDS = itertools.count(1)
_RUNNING = {}
_QUEUE = {}          # service -> liste d'entrées prévues
_INBOX = []          # demandes reçues, pas encore analysées
_RECENT = deque(maxlen=MAX_RECENT)

RESULT_LABELS = {
    "grabbed": "Sent to Sonarr/Radarr",
    "simulated": "Simulation: choice verified, nothing sent",
    "queued": "Already in the queue or already grabbed",
    "empty": "No eligible release",
    "none": "No eligible release",
    "stale": "Skipped: the media changed in the meantime",
    "timeout": "Timed out: will be retried later",
    "error": "Error: will be retried later",
}
# =================================================


# ======================== OUTILS ========================

# Vide toute l'activité (utilisé par les tests)
def reset():
    with _LOCK:
        _RUNNING.clear()
        _QUEUE.clear()
        _INBOX.clear()
        _RECENT.clear()


# Garde le texte affichable et le coupe à la taille voulue
def _clean(text, limit=120):
    return "".join(ch for ch in str(text or "") if ch.isprintable())[:limit].strip()
# =================================================


# ======================== DEMANDES REÇUES ========================

# Une demande vient d'arriver (webhook) : elle attend la prochaine analyse
def received(service, title):
    entry = {"service": service, "title": _clean(title, 80) or "New request", "at": time.time()}
    with _LOCK:
        _INBOX.append(entry)
        del _INBOX[:-MAX_INBOX]


# Un passage démarre : les demandes reçues sont prises en charge
def clear_inbox():
    with _LOCK:
        _INBOX.clear()
# =================================================


# ======================== FILE PRÉVUE ========================

# Remplace la file prévue d'un service (chaque entrée : key, title, kind, fresh)
def set_queue(service, entries):
    cleaned = [{"key": e["key"], "title": _clean(e["title"]), "kind": e["kind"], "fresh": bool(e.get("fresh"))}
               for e in entries]
    with _LOCK:
        _QUEUE[service] = cleaned


# Retire de la file les médias déjà traités
def drop_from_queue(service, keys):
    keys = set(keys)
    with _LOCK:
        if service in _QUEUE:
            _QUEUE[service] = [e for e in _QUEUE[service] if e["key"] not in keys]
# =================================================


# ======================== RECHERCHES EN COURS ========================

# Début de passage : plus rien ne tourne (écarte une recherche restée affichée après un incident)
def clear_running():
    with _LOCK:
        _RUNNING.clear()


# Une recherche commence : renvoie son identifiant (pour phase() et finish())
def start(service, kind, key, title, fresh=False, phase="Searching releases"):
    ident = next(_IDS)
    entry = {"id": ident, "service": service, "kind": kind, "key": key, "title": _clean(title),
             "fresh": bool(fresh), "phase": phase, "started": time.time()}
    with _LOCK:
        _RUNNING[ident] = entry
        if service in _QUEUE:
            _QUEUE[service] = [e for e in _QUEUE[service] if e["key"] != key]
    return ident


# Change l'étape affichée d'une recherche
def phase(ident, text):
    with _LOCK:
        if ident in _RUNNING:
            _RUNNING[ident]["phase"] = text


# Termine une recherche et la range dans les événements récents
def finish(ident, result, detail=""):
    with _LOCK:
        entry = _RUNNING.pop(ident, None)
        if entry is None:
            return
        _RECENT.appendleft({
            "service": entry["service"], "kind": entry["kind"], "title": entry["title"],
            "fresh": entry["fresh"], "result": result,
            "label": RESULT_LABELS.get(result, result), "detail": _clean(detail, 160),
            "at": time.time(), "seconds": round(time.time() - entry["started"], 1)})
# =================================================


# ======================== AFFICHAGE ========================

# Copie de l'activité pour la page « En cours »
def snapshot():
    with _LOCK:
        queue = [dict(e, service=service) for service, rows in _QUEUE.items() for e in rows]
        queue.sort(key=lambda e: (not e["fresh"], e["service"]))
        return {"now": time.time(),
                "running": sorted((dict(e) for e in _RUNNING.values()), key=lambda e: e["started"]),
                "queue": queue[:MAX_QUEUE], "queue_total": len(queue),
                "inbox": [dict(e) for e in _INBOX],
                "recent": [dict(e) for e in _RECENT]}
# =================================================
