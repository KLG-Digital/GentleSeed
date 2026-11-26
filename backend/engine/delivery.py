# ======================== IMPORTS ========================
import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

from backend.engine import arr_client as arr_client
from backend.engine import journal as journal
from backend.engine import store as store
# =================================================


# ======================== CONFIGURATION ========================
LOCK = threading.RLock()
TRACKER_FILE = None  # résolu à chaque lecture, pour isoler les tests et les dossiers de données
MAX_TRACKED = 200
MAX_AGE_SECONDS = 48 * 3600
MAX_CHECKS_PER_CYCLE = 12  # pas 200 historiques toutes les 20 secondes
MIN_CHECK_INTERVAL = 45
SERVICE_BACKOFF = {}  # horodatages de reprise après un 429
# =================================================


# ======================== FICHIER DE SUIVI ========================

# Chemin du fichier deliveries.json (à côté de state.json)
def tracker_path():
    return TRACKER_FILE or Path(os.environ.get("DELIVERIES_FILE", str(store.STATE_FILE.parent / "deliveries.json")))


# Lit la liste des transmissions
def load():
    with LOCK:
        path = tracker_path()
        if not path.exists():
            return []
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError("Invalid delivery history")
        return value


# Écrit les transmissions (les 200 dernières) dans un fichier temporaire puis le remplace
def save(records):
    with LOCK:
        path = tracker_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(records[-MAX_TRACKED:], ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)


# Enregistre une transmission : la réponse HTTP a été acceptée, sans prétendre que le film est téléchargé
def register(service, media_id, release, source="manuel", *, accepted=True):
    if service not in ("radarr", "sonarr") or type(media_id) is not int or media_id < 1:
        raise ValueError("Invalid media reference")
    if not isinstance(release, dict):
        raise ValueError("Invalid release")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    item = {
        "key": f"{service}:{media_id}", "service": service, "media_id": media_id,
        "release": str(release.get("title") or "Release without title")[:350],
        "indexer_id": release.get("indexerId"), "source": source,
        "indexer": "".join(ch for ch in str(release.get("indexer") or "") if ch.isprintable())[:80],
        "status": "api_accepted" if accepted else "uncertain", "created": now,
        "updated": now, "download_id": None,
    }
    with LOCK:
        records = load()
        for existing in reversed(records):
            if existing.get("key") != item["key"] or normalize_title(existing.get("release")) != normalize_title(item["release"]):
                continue
            try:
                elapsed = (datetime.fromisoformat(now) - datetime.fromisoformat(existing["created"])).total_seconds()
            except (ValueError, TypeError, KeyError):
                continue
            if 0 <= elapsed <= 3600 and existing.get("status") in ("api_accepted", "uncertain", "queued", "grabbed"):
                # Cette transmission a déjà son suivi en cours : pas de doublon
                return existing
            break  # suivi terminé (échec, import, non confirmé) : un renvoi est suivi à nouveau
        # Un ancien suivi encore interrogé (« retiré », vieille mise en file) suivrait aussi le nouveau : on le remplace
        records = [r for r in records
                   if r.get("status") in ("imported", "failed", "unconfirmed") or r.get("key") != item["key"]
                   or normalize_title(r.get("release")) != normalize_title(item["release"])]
        records.append(item)
        save(records)
    journal.log(f"[{item['key']}] Request accepted by the {service.title()} API; queue and history tracking started.")
    return item
# =================================================


# ======================== INTERPRÉTATION DES ÉTATS ========================

# Titre réduit à ses lettres et chiffres, pour comparer deux noms de release
def normalize_title(value):
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


# Historique d'un média (lecture seule)
def history_for(client, media_id):
    if client.name == "radarr":
        records = client.request("GET", "history/movie", params={"movieId": media_id})
    elif hasattr(client, "episode_history"):
        records = client.episode_history(media_id)
    else:
        records = client.request("GET", "history/episode", params={"episodeId": media_id})
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise RuntimeError("Invalid history response")
    return records


# File d'attente complète, paginée (une page manquante n'est jamais prise pour une file vide)
def queue_for(client):
    records, page, size, expected = [], 1, 250, None
    while True:
        data = client.request("GET", "queue", params={"page": page, "pageSize": size})
        if (not isinstance(data, dict) or not isinstance(data.get("records"), list)
                or type(data.get("totalRecords")) is not int or data["totalRecords"] < 0):
            raise RuntimeError("Incomplete queue")
        if expected is None:
            expected = data["totalRecords"]
        elif expected != data["totalRecords"]:
            raise RuntimeError("Queue changed during reading")
        batch = data["records"]
        if not batch and len(records) < expected:
            raise RuntimeError("Missing page in the queue")
        if any(not isinstance(item, dict) for item in batch):
            raise RuntimeError("Invalid queue entry")
        records.extend(batch)
        if len(records) >= expected:
            break
        # Un service ou un proxy peut plafonner la taille de page : une page vide est déjà refusée plus haut
        page += 1
    return records


# Vrai si cette entrée de la file est la release choisie par GentleSeed
def queue_matches(record, item):
    if item["service"] == "radarr":
        same_media = record.get("movieId") == item["media_id"]
    else:
        ids = record.get("episodeIds") or []
        if not isinstance(ids, list):
            return False
        same_media = (item["media_id"] in ids or record.get("episodeId") == item["media_id"] or
                      any(isinstance(e, dict) and e.get("id") == item["media_id"] for e in record.get("episodes", [])))
    if not same_media:
        return False
    # L'identifiant du téléchargement (connu par l'historique) reconnaît la release même si le client l'a renommée
    known, found_id = str(item.get("download_id") or "").lower(), str(record.get("downloadId") or "").lower()
    if known and found_id and known == found_id:
        return True
    # Une autre release du même film a pu être ajoutée entre-temps : on ne confirme que le titre choisi
    title = record.get("title") or record.get("sourceTitle")
    if title:
        found, expected = normalize_title(title), normalize_title(item["release"])
        return bool(found and expected and (found == expected or found.startswith(expected)))
    # Sans titre, l'identité du média ne prouve pas la release
    return False


# Avancement du téléchargement, lu dans la file de Radarr/Sonarr (pourcentage et temps restant)
def note_progress(item, record):
    size, left = record.get("size"), record.get("sizeleft")
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (size, left)) and size > 0:
        item["progress"] = max(0, min(100, round(100 * (size - left) / size)))
    left_time = record.get("timeleft")
    if isinstance(left_time, str) and left_time:
        item["timeleft"] = left_time[:16]
    # Problème signalé par Radarr/Sonarr (client bloqué, tracker qui refuse, téléchargement à l'arrêt…)
    status = str(record.get("trackedDownloadStatus") or "").lower()
    if status in ("warning", "error"):
        messages = [text for entry in (record.get("statusMessages") or []) if isinstance(entry, dict)
                    for text in (entry.get("messages") or []) if isinstance(text, str)]
        item["problem"] = str(record.get("errorMessage") or (messages[0] if messages else "") or status)[:160]
    else:
        item.pop("problem", None)


# Radarr/Sonarr laissent parfois dans leur file une ligne en avertissement « already imported » : le fichier est déjà
# importé (import manuel, ou épisodes d'un pack déjà présents). Ce n'est pas un échec du téléchargement.
def already_imported(record):
    texts = [str(record.get("errorMessage") or "")]
    for entry in record.get("statusMessages") or []:
        if isinstance(entry, dict):
            texts += [text for text in (entry.get("messages") or []) if isinstance(text, str)]
    return any("already imported" in text.lower() for text in texts)


# Vrai si l'événement de l'historique concerne la release de GentleSeed (pas une autre du même film)
def history_matches(item, event):
    date = event.get("date")
    try:
        event_time = datetime.fromisoformat(date.replace("Z", "+00:00"))
        started = datetime.fromisoformat(item["created"])
        if event_time < started - timedelta(seconds=5):
            return False
    except (TypeError, ValueError, AttributeError):
        return False
    if item["service"] == "radarr" and event.get("movieId") not in (None, item["media_id"]):
        return False
    if item["service"] == "sonarr" and event.get("episodeId") not in (None, item["media_id"]):
        return False
    dlid = event.get("downloadId")
    if item.get("download_id") and dlid and str(dlid).lower() == str(item["download_id"]).lower():
        return True
    src = normalize_title(event.get("sourceTitle"))
    intended = normalize_title(item.get("release"))
    return bool(src and intended and src == intended)


# Type d'événement reconnu : grabbed, imported, failed (ou None)
def event_kind(event):
    typ = event.get("eventType")
    if typ in (1, "grabbed", "Grabbed"):
        return "grabbed"
    if typ in (3, "downloadFolderImported", "DownloadFolderImported", "imported"):
        return "imported"
    if typ in (4, "downloadFailed", "DownloadFailed", "failed"):
        return "failed"
    return None


# Change l'état d'une transmission et le journalise (seulement s'il change, pas à chaque lecture)
def transition(item, next_status, *, download_id=None):
    # L'identifiant est mémorisé dès qu'il est connu, même sans changement d'état
    if download_id and not item.get("download_id"):
        item["download_id"] = download_id
    if item["status"] == next_status:
        return False
    item["status"] = next_status
    if next_status != "queued":
        for field in ("progress", "timeleft", "problem"):
            item.pop(field, None)
    item["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if download_id:
        item["download_id"] = download_id
    label = {
        "queued": "Release is in the queue",
        "grabbed": "Release confirmed by the Radarr/Sonarr history",
        "imported": "Import confirmed by the Radarr/Sonarr history",
        "failed": "Failure reported by the Radarr/Sonarr history",
        "unconfirmed": "Hand-off not confirmed after 48 h; check Radarr/Sonarr",
        "removed": "Left the queue without being imported (removed from the download client?)",
    }.get(next_status, next_status)
    release = f"{item['release']} [indexer: {item['indexer']}]" if item.get("indexer") else item["release"]
    journal.log(f"[{item['key']}] {label}: {release}", level="WARN" if next_status in ("failed", "unconfirmed", "removed") else "INFO")
    return True


# Date du dernier contrôle, 0 si la valeur est absente ou invalide (fichier modifié à la main)
def checked_at(item):
    value = item.get("last_checked", 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


# Suivi terminé (48 h) ; une date illisible ne compte pas comme expirée
def older_than_tracking(item):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(item["created"])).total_seconds() > MAX_AGE_SECONDS
    except (KeyError, TypeError, ValueError):
        return False


# Identité d'une transmission, pour retrouver la même entrée après les appels réseau
def identity(item):
    return (item.get("key"), item.get("created"), item.get("release"))


# Observe l'état des transmissions (file puis historique), sans jamais envoyer ni relancer.
# Les appels réseau se font hors du verrou : seuls la relecture et l'écriture du fichier le prennent
def poll(clients):
    records = load()
    worked = []
    unresolved = [r for r in records if r.get("status") not in ("imported", "failed", "unconfirmed")
                  and not (r.get("status") == "removed" and older_than_tracking(r))]
    if not unresolved:
        return 0
    by_service = {c.name: c for c in clients}
    queue_cache = {}
    failed_services = set()
    changes = 0
    inspected = 0
    now = datetime.now(timezone.utc)
    # Les moins récemment contrôlés d'abord
    unresolved.sort(key=checked_at)
    for item in unresolved:
        if inspected >= MAX_CHECKS_PER_CYCLE:
            break
        if time.time() - checked_at(item) < MIN_CHECK_INTERVAL:
            continue
        if item["service"] in failed_services or SERVICE_BACKOFF.get(item["service"], 0) > time.time():
            continue
        if item["service"] not in by_service:
            continue
        inspected += 1
        worked.append(item)
        item["last_checked"] = time.time()
        try:
            expired = (now - datetime.fromisoformat(item["created"])).total_seconds() > MAX_AGE_SECONDS
            client = by_service.get(item["service"])
            if client is None or not callable(getattr(client, "request", None)):
                continue
            if item["service"] not in queue_cache:
                queue_cache[item["service"]] = queue_for(client)
            matching = next((q for q in queue_cache[item["service"]] if queue_matches(q, item)), None)
            if matching is not None:
                item["missed"] = 0
                if already_imported(matching):
                    changes += transition(item, "imported", download_id=matching.get("downloadId"))
                    continue
                changes += transition(item, "queued", download_id=matching.get("downloadId"))
                note_progress(item, matching)
                continue
            history = history_for(client, item["media_id"])
            events = [e for e in history if history_matches(item, e)]
            events.sort(key=lambda e: str(e.get("date", "")), reverse=True)
            # Debug : pourquoi une transmission ne change pas d'état (rien dans la file, événements trouvés dans l'historique)
            kinds = ", ".join(sorted({str(event_kind(e) or e.get("eventType")) for e in events})) or "-"
            journal.log(f"[{item['key']}] Tracking {item['status']}: {len(history)} history events, {len(events)} matching ({kinds})", level="DEBUG")
            if events:
                status = next((event_kind(e) for e in events if event_kind(e)), None)
                # « grabbed » ancien, absent de la file et jamais importé (téléchargement supprimé dans le client) :
                # le suivi s'arrête à 48 h au lieu de rester « envoyé » pour toujours
                if status == "grabbed" and not expired and item["status"] in ("queued", "removed"):
                    # Vu dans la file, puis disparu sans import ni échec : deux contrôles de suite avant de le dire
                    # (un client de téléchargement injoignable peut vider la file un instant)
                    item["missed"] = int(item.get("missed", 0)) + 1
                    if item["missed"] >= 2:
                        changes += transition(item, "removed")
                    continue
                if status and not (status == "grabbed" and expired):
                    changes += transition(item, status, download_id=events[0].get("downloadId"))
                    continue
            # Le délai de 48 h ne s'applique que si ni la file ni l'historique ne confirment rien
            if expired:
                changes += transition(item, "unconfirmed")
        except arr_client.RateLimitedError as error:
            failed_services.add(item["service"])
            SERVICE_BACKOFF[item["service"]] = time.time() + error.retry_after
            journal.log(f"[{item['service']}] Tracking suspended on HTTP 429 for {error.retry_after}s", level="WARN")
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, requests.RequestException) as error:
            # Impossible de confirmer ne veut pas dire raté : nouvel essai au cycle suivant
            failed_services.add(item["service"])
            journal.log(f"[{item['key']}] Tracking temporarily unavailable: {type(error).__name__}", level="DEBUG")
    if inspected:
        journal.log(f"Tracking: {inspected} checked, {changes} changed", level="DEBUG")
    if changes or inspected:
        with LOCK:
            fresh = load()
            index = {identity(record): record for record in fresh}
            for item in worked:
                target = index.get(identity(item))
                if target is not None:
                    for field in ("status", "updated", "download_id", "last_checked", "progress", "timeleft", "problem", "missed"):
                        if field in item:
                            target[field] = item[field]
                        elif field in ("progress", "timeleft", "problem"):
                            target.pop(field, None)
            save(fresh)
    return changes
# =================================================
