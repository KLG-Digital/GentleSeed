# ======================== IMPORTS ========================
import secrets
import threading
import time
import unicodedata
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from backend import settings as Settings
from backend.engine import delivery as DeliveryTracker
from backend.engine import search
from backend.engine import arr_client as arr_client
from backend.engine import diagnostics as SearchDiagnostics
from backend.engine import journal as journal
from backend.engine import ranking as ranking
from backend.engine.monitor import STATUS, STATUS_LOCK
from backend.engine.search import OPERATION_LOCK, choose_search, configure_engine, visible_release
from backend.routes import security
# =================================================


# ======================== MÉDIAS ET RECHERCHE DE RELEASES ========================

router = APIRouter()


# --------------------- INVENTAIRE RADARR / SONARR ---------------------
MAX_MENU_ITEMS = 5000  # garde-fou de taille de réponse, bien au-dessus d'une bibliothèque normale


# Clé de tri alphabétique : insensible à la casse et aux accents
def alpha_key(text):
    decomposed = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


# Entier, sinon 0 (pour le tri)
def _int_or_zero(value):
    return value if type(value) is int else 0


# Clé de tri des épisodes : série, saison, épisode
def episode_sort_key(item):
    series = str(item.get("title", "")).rsplit(" - S", 1)[0]
    return (alpha_key(series), _int_or_zero(item.get("seasonNumber")), _int_or_zero(item.get("episodeNumber")))


# Médias manquants de Radarr/Sonarr (films, séries, saisons ou épisodes) pour les menus
@router.get("/api/items")
def items(request: Request, service: str, scope: str = "episode"):
    # Le scope "season" n'existe que pour Sonarr.
    if scope not in ("episode", "season"):
        raise HTTPException(400, "Invalid search type")
    if scope == "season" and service != "sonarr":
        raise HTTPException(400, "Seasons only apply to Sonarr")
    security.require_login(request)
    if service not in ("radarr", "sonarr"):
        raise HTTPException(400, "Invalid service")
    config = Settings.load_settings()
    if not config[f"{service.upper()}_API_KEY"] or not config[f"{service.upper()}_URL"]:
        raise HTTPException(400, f"Configure {service.title()} first")
    try:
        # Lecture seule : sans verrou, sinon la liste attend la fin d'un cycle automatique
        # (jusqu'à plusieurs minutes) et Cloudflare coupe la requête (HTTP 524).
        arr_client.REQUEST_TIMEOUT = config["REQUEST_TIMEOUT"]
        client = next(c for c in search.clients_for(config) if c.name == service)
        missing = client.missing_items()
        if scope == "season":
            allow_anime = client.supports_anime_season_packs()
            grouped = {}
            for ep in missing:
                sid, sn = ep.get("seriesId"), ep.get("seasonNumber")
                if (type(sid) is int and type(sn) is int and
                        (allow_anime or str(ep.get("seriesType", "standard")).lower() != "anime")):
                    grouped.setdefault((sid, sn), []).append(ep)
            seasons = [{"id": sid, "seasonNumber": sn,
                        "title": f"{rows[0]['title'].rsplit(' - S', 1)[0]} - Season {sn:02d} ({len(rows)} missing episodes)"}
                       for (sid, sn), rows in grouped.items() if len(rows) >= 2]
            seasons.sort(key=lambda row: (alpha_key(row["title"].rsplit(" - Season ", 1)[0]), row["seasonNumber"]))
            return {"total": len(seasons), "items": seasons[:MAX_MENU_ITEMS],
                    "truncated": len(seasons) > MAX_MENU_ITEMS, "scope": "season"}
        if service == "sonarr":
            missing = sorted(missing, key=episode_sort_key)
        else:
            missing = sorted(missing, key=lambda row: alpha_key(row.get("title", "")))
        return {"total": len(missing), "items": missing[:MAX_MENU_ITEMS],
                "truncated": len(missing) > MAX_MENU_ITEMS, "scope": "episode"}
    except (requests.RequestException, ValueError, RuntimeError) as error:
        raise HTTPException(SearchDiagnostics.UPSTREAM_ERROR, SearchDiagnostics.describe_connection_error(error, service)) from error


# --------------------- SIMULATION D'UNE RECHERCHE ---------------------
# Contrôle les paramètres d'une demande de simulation
def parse_preview_request(payload):
    service = payload.get("service") if isinstance(payload, dict) else None
    media_id = payload.get("id") if isinstance(payload, dict) else None
    scope = payload.get("scope", "episode") if isinstance(payload, dict) else "episode"
    season_number = payload.get("seasonNumber") if isinstance(payload, dict) else None
    if (service not in ("radarr", "sonarr") or type(media_id) is not int or media_id <= 0
            or scope not in ("episode", "season") or
            (scope == "season" and (service != "sonarr" or type(season_number) is not int or season_number < 0))):
        raise HTTPException(400, "Choose a valid movie, episode or season")
    config = Settings.load_settings()
    if not config[f"{service.upper()}_API_KEY"] or not config[f"{service.upper()}_URL"]:
        raise HTTPException(400, "Service not configured")
    return config, service, media_id, scope, season_number


# Simulation d'une recherche, réponse après la fin
@router.post("/api/preview")
async def preview(request: Request):
    security.require_write(request)
    config, service, media_id, scope, season_number = parse_preview_request(await security.read_json(request))
    # La recherche réseau est placée dans un thread, sans bloquer l'interface.
    return await run_in_threadpool(preview_search, config, service, media_id, scope, season_number)


# Appelle la simulation du moteur ; une erreur de recherche devient une réponse HTTP
def preview_search(config, service, media_id, scope="episode", season_number=None, progress=None):
    try:
        result = search.preview_search(config, service, media_id, scope, season_number, progress)
    except search.SearchFailed as error:
        raise HTTPException(error.code, error.message) from error
    with STATUS_LOCK:
        STATUS["last_preview"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return result


# --------------------- RECHERCHE EN ARRIÈRE-PLAN (SUIVI PAR INTERROGATION) ---------------------

# Une recherche de saison peut durer plusieurs minutes (indexeurs lents). Une requête HTTP
# aussi longue est coupée par les proxys (Cloudflare : ~100 s, erreur 524). Ici le navigateur
# lance la recherche, reçoit un identifiant tout de suite, puis interroge l'état par courtes
# requêtes. La recherche reste en LECTURE SEULE : aucun envoi n'est jamais déclenché.
PREVIEW_JOBS = {}
PREVIEW_JOBS_LOCK = threading.Lock()
PREVIEW_JOB_TTL = 1800      # secondes de conservation d'un résultat terminé
PREVIEW_JOB_MAX_RUNNING = 4


# Supprime les anciennes recherches terminées
def _purge_preview_jobs(now):
    for job_id in [j for j, row in PREVIEW_JOBS.items()
                   if row["state"] != "running" and now - row["finished"] > PREVIEW_JOB_TTL]:
        del PREVIEW_JOBS[job_id]


# Exécute une recherche en arrière-plan et garde son résultat
def _run_preview_job(job_id, config, service, media_id, scope, season_number):
    job = PREVIEW_JOBS[job_id]
    try:
        result = preview_search(config, service, media_id, scope, season_number, progress=job["progress"])
        outcome = {"state": "done", "result": result}
    except HTTPException as error:
        outcome = {"state": "error", "code": error.status_code, "message": str(error.detail)}
    except Exception as error:  # noqa: BLE001 - ne jamais laisser un thread mourir sans réponse
        journal.log(f"Search {service}:{media_id}: internal error {type(error).__name__}", level="ERROR")
        outcome = {"state": "error", "code": 500, "message": "Internal error during the search. Check the logs."}
    with PREVIEW_JOBS_LOCK:
        job.update(outcome)
        job["finished"] = time.monotonic()


# Démarre une recherche en arrière-plan et renvoie son identifiant
@router.post("/api/preview/start")
async def preview_start(request: Request):
    security.require_write(request)
    config, service, media_id, scope, season_number = parse_preview_request(await security.read_json(request))
    now = time.monotonic()
    with PREVIEW_JOBS_LOCK:
        _purge_preview_jobs(now)
        if sum(1 for row in PREVIEW_JOBS.values() if row["state"] == "running") >= PREVIEW_JOB_MAX_RUNNING:
            raise HTTPException(429, "Too many searches in progress. Wait for one of them to finish.")
        job_id = secrets.token_urlsafe(16)
        PREVIEW_JOBS[job_id] = {"state": "running", "started": now, "progress": {"phase": "starting"}}
    threading.Thread(target=_run_preview_job, args=(job_id, config, service, media_id, scope, season_number),
                     name=f"preview-{job_id[:6]}", daemon=True).start()
    return {"job": job_id}


# Avancement ou résultat d'une recherche en arrière-plan
@router.get("/api/preview/status")
def preview_status(request: Request, job: str):
    security.require_login(request)
    with PREVIEW_JOBS_LOCK:
        row = PREVIEW_JOBS.get(job)
        if row is None:
            raise HTTPException(404, "Unknown or expired search. Run it again.")
        end = row.get("finished", time.monotonic())
        reply = {"state": row["state"], "elapsed": round(end - row["started"], 1),
                 "phase": row["progress"].get("phase")}
        if row["state"] == "done":
            reply["result"] = row["result"]
        elif row["state"] == "error":
            reply.update(code=row["code"], message=row["message"])
    return reply


# --------------------- VÉRIFICATION EN LECTURE SEULE APRÈS ENVOI ---------------------

# Vérifie si *arr affiche le média dans sa file (lecture seule) ; une absence n'est PAS une preuve d'échec
# (téléchargement instantané, historique ou délai de synchronisation possibles)
@router.get("/api/verify-choice")
async def verify_choice(request: Request, service: str, media_id: int):
    security.require_login(request)
    if service not in ("radarr", "sonarr") or media_id < 1:
        raise HTTPException(400, "Invalid media or service")
    config = Settings.load_settings()
    if not config.get(f"{service.upper()}_URL") or not config.get(f"{service.upper()}_API_KEY"):
        raise HTTPException(400, "Service not configured")
    try:
        def inspect_queue():
            client = next((c for c in search.clients_for(config) if c.name == service), None)
            if client is None:
                raise RuntimeError("Service unavailable")
            return media_id in client.queued_ids()
        queued = await run_in_threadpool(inspect_queue)
    except (requests.RequestException, RuntimeError, ValueError) as error:
        raise HTTPException(503, f"Verification impossible: {error}") from error
    try:
        matching = next((r for r in reversed(DeliveryTracker.load())
                         if r.get("key") == f"{service}:{media_id}"), None)
    except (OSError, ValueError):
        matching = None
    status = (matching or {}).get("status")
    confirmed = bool(queued or status in ("queued", "grabbed", "imported"))
    return {
        "confirmed": confirmed,
        "state": "queue" if queued else (status or "not_observed"),
        "message": ("Present in the " + service + " queue" if queued
                    else "GentleSeed tracking: " + status if status else
                    "Not visible in the queue; check the application's history."),
    }


# --------------------- CHOIX EXPLICITE D'UNE RELEASE ---------------------

# Transmet à *arr, jamais à Prowlarr/qBittorrent ; le GUID n'est pas une autorisation :
# on refait la recherche et on vérifie qu'il appartient toujours aux releases admissibles du média
@router.post("/api/choose")
async def choose_release(request: Request):
    security.require_write(request)
    data = await security.read_json(request)
    if not isinstance(data, dict):
        raise HTTPException(400, "Invalid request")
    service, media_id = data.get("service"), data.get("id")
    guid, indexer_id = data.get("guid"), data.get("indexerId")
    scope, season_number = data.get("scope", "episode"), data.get("seasonNumber")
    override_language = data.get("overrideLanguage", False)
    if not isinstance(override_language, bool):
        raise HTTPException(400, "Invalid release reference")
    if (service not in ("radarr", "sonarr") or type(media_id) is not int or media_id < 1
            or not isinstance(guid, str) or not guid or len(guid) > 500
            or type(indexer_id) is not int or indexer_id < 1
            or scope not in ("episode", "season")
            or (scope == "season" and (service != "sonarr" or type(season_number) is not int or season_number < 0))):
        raise HTTPException(400, "Invalid release reference")
    config = Settings.load_settings()
    # Choix manuel : simulation tant que DRY_RUN est actif, envoi réel sinon.
    manual_test = False
    try:
        return await run_in_threadpool(choose_search, config, service, media_id, guid, indexer_id, manual_test, scope, season_number,
                                       override_language)
    except (requests.RequestException, ValueError, RuntimeError) as error:
        scope_label = f"season pack S{season_number:02d}" if scope == "season" else "movie or episode"
        if isinstance(error, requests.HTTPError):
            http_status = getattr(getattr(error, "response", None), "status_code", "unknown")
            detail = ""
            try:
                body = error.response.json()
                if isinstance(body, dict):
                    detail = str(body.get("message") or body.get("errorMessage") or "").strip()[:200]
            except (ValueError, AttributeError):
                pass
            reason = f"API {service.title()}: HTTP response {http_status}: {detail}" if detail else f"API {service.title()}: HTTP response {http_status}"
        elif isinstance(error, requests.RequestException):
            reason = f"Communication with {service.title()} impossible ({type(error).__name__})"
        else:
            reason = str(error).strip() or "Verification impossible (details unavailable)"
        reason = reason[:350]
        skip = isinstance(error, RuntimeError) and reason.startswith((
            "Already handled:", "No pack to send:", "Media not missing or not monitored"))
        journal.log(f"[{service}:{media_id}] Send not performed ({scope_label}): {reason}",
                     level="INFO" if skip else "WARN")
        if skip:
            return {"ok": True, "skipped": True, "accepted_by_api": False,
                    "message": reason}
        raise HTTPException(409, f"Selection failed: {reason}") from error


# --------------------- APERÇU DÉMONSTRATION ---------------------

# Montre l'algorithme sans service distant ni téléchargement
@router.get("/api/demo")
def demo(request: Request):
    security.require_login(request)
    releases = [
        {"title": "Film.Exemple.2026.1080p.BluRay.MULTI.H265", "seeders": 4, "leechers": 9, "size": 8_589_934_592, "indexer": "Torrent Alpha",
         "rejections": [], "indexerId": 1, "guid": "demo-1", "protocol": "torrent",
         "quality": {"quality": {"name": "Bluray-1080p"}}},
        {"title": "Film.Exemple.2026.1080p.WEB-DL.VFF.H264", "seeders": 69, "leechers": 18, "size": 3_221_225_472, "indexer": "Torrent Beta",
         "rejections": [], "indexerId": 1, "guid": "demo-2", "protocol": "torrent",
         "quality": {"quality": {"name": "WEBDL-1080p"}}},
        {"title": "Film.Exemple.2026.1080p.WEBRip.FRENCH", "seeders": 1, "leechers": 2, "size": 1_717_986_918, "indexer": "Torrent Gamma",
         "rejections": [], "indexerId": 1, "guid": "demo-3", "protocol": "torrent",
         "quality": {"quality": {"name": "WEBRip-1080p"}}},
        {"title": "Film.Exemple.2026.2160p.VO", "seeders": 250, "leechers": 35, "size": 16_106_127_360, "indexer": "Torrent Beta",
         "rejections": ["Language not allowed by the profile"],
         "indexerId": 1, "guid": "demo-4", "protocol": "torrent",
         "quality": {"quality": {"name": "Bluray-2160p"}}},
    ]
    current = Settings.load_settings()
    # Une analyse en cours peut garder le verrou des minutes : on n'attend pas indéfiniment
    if not OPERATION_LOCK.acquire(timeout=5):
        raise HTTPException(409, "An analysis is in progress, try again in a moment")
    try:
        configure_engine(current)
        accepted = ranking.eligible_releases(releases)
        accepted.sort(key=ranking.release_rank_key, reverse=True)
    finally:
        OPERATION_LOCK.release()
    journal.log("DEMO: ranking example viewed from the browser")
    return {"demo": True, "simulation": True, "total": len(releases),
            "accepted": len(accepted), "queued": False,
            "selected": visible_release(accepted[0]) if accepted else None,
            "approved": [visible_release(item) for item in accepted],
            "rejected": [visible_release(item) for item in releases if item not in accepted]}


# --------------------- INDEXEURS DE RADARR ET DE SONARR ---------------------
# Liste (lecture seule) des indexeurs torrent de chaque service : ceux des deux, et ceux d'un seul.
# Sert à choisir les indexeurs à ignorer ; les noms sont ceux que portent les releases
@router.get("/api/indexers")
def list_indexers(request: Request):
    security.require_login(request)
    config = Settings.load_settings()
    found, errors = {}, {}
    for client in search.clients_for(config):
        try:
            rows = client.request("GET", "indexer")
            if not isinstance(rows, list):
                raise RuntimeError("Unexpected response")
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("name"), str) and row["name"].strip() \
                        and str(row.get("protocol", "torrent")).lower() == "torrent":
                    found.setdefault(row["name"].strip(), set()).add(client.name)
        except (requests.RequestException, ValueError, RuntimeError) as error:
            errors[client.name] = SearchDiagnostics.describe_connection_error(error, client.name)
    return {"indexers": [{"name": name, "services": sorted(services)}
                         for name, services in sorted(found.items(), key=lambda pair: pair[0].lower())],
            "errors": errors}


# --------------------- TEST DE CONNEXION API ---------------------
# Teste un service en lecture seule avec l'adresse et la clé données. Le résultat n'alimente le tableau de bord
# que si ce sont celles déjà enregistrées ; sinon rien n'est modifié
def run_connection_test(service, url, key):
    saved = Settings.load_settings()
    same = (url, key) == (saved[f"{service.upper()}_URL"], saved[f"{service.upper()}_API_KEY"])
    if not url or not key:
        return {"ok": False, "message": "API key not provided" if url else "Address not provided", "saved": same}
    try:
        client = arr_client.ArrClient(service, url, key)
        # L'endpoint system/status est en lecture seule.
        response = client.request("GET", "system/status")
        if same:
            with STATUS_LOCK:
                STATUS.setdefault("connections", {})[service] = True
        return {"ok": True, "message": "Connection established", "saved": same,
                "version": str(response.get("version", "unknown"))[:64]}
    except (requests.RequestException, ValueError, RuntimeError) as error:
        journal.log(f"[{service}] Connection test failed: {SearchDiagnostics.error_text(error, service)}", level="WARN")
        if same:
            with STATUS_LOCK:
                STATUS.setdefault("connections", {})[service] = False
        return {"ok": False, "message": SearchDiagnostics.describe_connection_error(error, service), "saved": same}


# Test avec les réglages enregistrés
@router.get("/api/connection")
def test_connection(request: Request, service: str):
    security.require_login(request)
    if service not in ("radarr", "sonarr"):
        raise HTTPException(400, "Invalid service")
    config = Settings.load_settings()
    return run_connection_test(service, config[f"{service.upper()}_URL"], config[f"{service.upper()}_API_KEY"])


# Test avec l'adresse et la clé saisies dans le formulaire (non enregistrées) ; vide = valeur enregistrée
@router.post("/api/connection")
async def test_connection_typed(request: Request):
    security.require_write(request)
    payload = await security.read_integration_payload(request)
    service = payload.get("service")
    if service not in ("radarr", "sonarr"):
        raise HTTPException(400, "Invalid service")
    config = Settings.load_settings()
    url, key = payload.get("url"), payload.get("api_key")
    key_name = f"{service.upper()}_API_KEY"
    if isinstance(url, str) and url.strip():
        try:
            url = Settings.validate_settings({f"{service.upper()}_URL": url})[f"{service.upper()}_URL"]
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
    else:
        url = config[f"{service.upper()}_URL"]
    if isinstance(key, str) and key.strip():
        if len(key) > 250:
            raise HTTPException(400, f"Invalid key for {key_name}")
        key = key.strip()
    else:
        # La clé enregistrée ne part que vers l'adresse enregistrée : sinon n'importe quelle adresse pourrait la recevoir
        if url.rstrip("/") != str(config[f"{service.upper()}_URL"]).rstrip("/"):
            raise HTTPException(400, "Enter the API key to test a different address")
        key = config[f"{service.upper()}_API_KEY"]
    return await run_in_threadpool(run_connection_test, service, url, key)
# =================================================
