# ======================== IMPORTS ========================
import threading
import time
from urllib.parse import urlsplit

import requests

from backend.engine import delivery as DeliveryTracker
from backend.engine import diagnostics as SearchDiagnostics
from backend.engine import selector as selector
from backend.engine import arr_client as arr_client
from backend.engine import journal as journal
from backend.engine import ranking as ranking
from backend.engine import store as store
# =================================================


# ======================== ÉTAT PARTAGÉ ========================

# Noms d'étapes (identifiants internes) tels qu'écrits dans le journal
STEP_LABELS = {
    "configuration": "configuration", "recherche": "search", "version_sonarr": "sonarr_version",
    "inventaire_episodes": "episode_inventory", "file_attente": "queue", "release_saison": "season_releases",
    "release": "releases", "classement": "ranking", "fin": "end", "failure": "failure",
}

# Une seule opération à la fois sur le moteur (recherche, choix, cycle automatique, restauration)
OPERATION_LOCK = threading.RLock()


# Erreur de recherche avec le code HTTP et le message à montrer (l'interface web la traduit)
class SearchFailed(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message
# =================================================


# ======================== APPLICATION DES RÉGLAGES ========================

# Applique les réglages enregistrés au moteur
def configure_engine(config):
    for field in ("DRY_RUN", "ONLY_NEW", "CHECK_INTERVAL", "RETRY_INTERVAL", "MAX_SEARCHES_PER_CYCLE"):
        setattr(selector, field, config[field])
    for field in ("MIN_SEEDERS", "ALLOW_UNKNOWN_SEEDERS", "PREFERRED_CODEC", "CODEC_PRIORITY", "TEAM_PREFERENCE"):
        setattr(ranking, field, config[field])
    ranking.IGNORED_INDEXERS = {service: frozenset(str(name).strip().lower() for name in config.get(f"IGNORED_INDEXERS_{service.upper()}", []))
                                for service in ("radarr", "sonarr")}
    selector.LANGUAGE_FALLBACK_AFTER = config.get("LANGUAGE_FALLBACK_AFTER", 0)
    arr_client.REQUEST_TIMEOUT = config["REQUEST_TIMEOUT"]
    journal.LOG_LEVEL = config["LOG_LEVEL"]


# Crée un client pour chaque service configuré (adresse et clé API renseignées)
def clients_for(config):
    clients = []
    for name in ("radarr", "sonarr"):
        key = config[f"{name.upper()}_API_KEY"]
        url = config[f"{name.upper()}_URL"]
        if key and url:
            clients.append(cached_client(name, url, key))
    return clients


# Un client par service et par réglage : la connexion et la version de l'API sont réutilisées entre les sondages.
# Un réglage modifié remplace l'ancien client, qui est fermé
CLIENTS = {}
CLIENTS_LOCK = threading.Lock()


def cached_client(name, url, key):
    signature = (arr_client.ArrClient, url, key)
    with CLIENTS_LOCK:
        known = CLIENTS.get(name)
        if known is not None and known[0] == signature:
            return known[1]
        client = arr_client.ArrClient(name, url, key)
        CLIENTS[name] = (signature, client)
    if known is not None:
        session = getattr(known[1], "session", None)
        if hasattr(session, "close"):
            session.close()
    return client
# =================================================


# ======================== AFFICHAGE DES RELEASES ========================

# URL de la fiche publique donnée par Radarr/Sonarr (jamais une URL de téléchargement) ; schémas scriptés et identifiants refusés
def release_info_url(release):
    if not isinstance(release, dict):
        return None
    url = release.get("infoUrl") or release.get("detailsUrl")
    if not isinstance(url, str) or len(url) > 2048:
        return None
    url = url.strip()
    if any(ord(ch) < 32 for ch in url):
        return None
    try:
        parsed = urlsplit(url)
        if (parsed.scheme.lower() not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            return None
    except ValueError:
        return None
    return url


# Normalise les métadonnées renvoyées par Radarr ou Sonarr (taille en octets, inconnue si absente)
def visible_release(release):
    quality = release.get("quality") or {}
    if isinstance(quality, dict):
        quality = quality.get("quality", quality)
        if isinstance(quality, dict):
            quality = quality.get("name", "?")
    quality = str(quality or "?")[:120]
    indexer = release.get("indexer") or release.get("indexerName")
    if not isinstance(indexer, str) or not indexer.strip():
        indexer_id = release.get("indexerId")
        indexer = f"Indexer #{indexer_id}" if indexer_id is not None else "Unknown"

    seeders = ranking.number_of_seeders(release)
    leechers_raw = release.get("leechers")
    leechers = leechers_raw if isinstance(leechers_raw, int) and not isinstance(leechers_raw, bool) and leechers_raw >= 0 else None
    size_raw = release.get("size")
    size_bytes = size_raw if isinstance(size_raw, int) and not isinstance(size_raw, bool) and size_raw >= 0 else None

    q = quality.lower()
    source = next((label for term, label in (("webdl", "WEB-DL"), ("web-dl", "WEB-DL"),
        ("webrip", "WEBRip"), ("bluray", "BluRay"), ("br-disk", "BluRay Disc"),
        ("hdtv", "HDTV"), ("dvd", "DVD"), ("remux", "Remux")) if term in q), "Unknown")
    return {"title": str(release.get("title", "?"))[:350], "seeders": seeders,
            "size": size_bytes, "leechers": leechers, "indexer": str(indexer)[:120],
            "source": source, "quality": quality, "codec": ranking.video_codec(release),
            "languageRefused": bool(ranking.language_reasons(release)),
            "infoUrl": release_info_url(release),
            "reasons": ranking.rejection_details(release)[:6],
            # Refusée pour sa seule langue : peut être envoyée à la main, après confirmation
            "overridable": ranking.language_only_rejected(release)}
# =================================================


# ======================== CHOIX EXPLICITE D'UNE RELEASE ========================

# Vérifie que le choix est toujours admissible puis le transmet à Radarr/Sonarr (jamais à Prowlarr/qBittorrent)
def choose_search(config, service, media_id, guid, indexer_id, manual_test=False, scope="episode", season_number=None,
                  override_language=False):
    with OPERATION_LOCK:
        configure_engine(config)
        client = next((c for c in clients_for(config) if c.name == service), None)
        if client is None:
            raise RuntimeError("Service not configured")
        # Une saison vérifie tous ses épisodes manquants et la file d'attente
        missing = client.missing_items()
        allow_anime = (client.supports_anime_season_packs() if scope == "season" else False)
        episode_ids = ({media_id} if scope != "season" else
            {e["id"] for e in ranking.season_episodes(
                missing, media_id, season_number, allow_anime=allow_anime)})
        if not episode_ids:
            raise RuntimeError("No pack to send: the season must have at least two missing, monitored episodes compatible with this Sonarr version")
        if episode_ids & client.queued_ids():
            raise RuntimeError("Already handled: an episode of this media is in the Sonarr/Radarr queue; no new send performed")
        if scope != "season" and media_id not in {item["id"] for item in missing}:
            raise RuntimeError("Media not missing or not monitored; no new send performed")
        releases = client.season_releases(media_id, season_number) if scope == "season" else client.releases(media_id)
        if override_language and scope == "season":
            raise RuntimeError("A language override is not available for a season pack")
        admitted = (ranking.eligible_season_packs(releases, media_id, season_number)
                    if scope == "season" else
                    ranking.language_fallback_candidates(releases) if override_language else ranking.eligible_releases(releases))
        matches = [r for r in admitted
                   if r.get("guid") == guid and r.get("indexerId") == indexer_id]
        if len(matches) != 1:
            raise RuntimeError("Release missing or now rejected by the profile")
        if override_language:
            journal.log(f"[{service}:{media_id}] MANUAL override of the language rules: "
                        f"{'; '.join(ranking.language_reasons(matches[0]))[:300]}", level="WARN")
        if config["DRY_RUN"] and not manual_test:
            journal.log(f"[{service}:{media_id}] SIMULATION: manual choice verified, nothing sent")
            return {"ok": True, "simulation": True, "message": "Choice validated in simulation; nothing sent to Radarr/Sonarr"}
        # Nouvelle vérification juste avant l'envoi
        if episode_ids & client.queued_ids():
            raise RuntimeError("New entry detected in the queue")
        refreshed = client.missing_items()
        still = ({e["id"] for e in ranking.season_episodes(
                    refreshed, media_id, season_number, allow_anime=allow_anime)}
                 if scope == "season" else {item["id"] for item in refreshed})
        if not episode_ids.issubset(still):
            raise RuntimeError("Media/episodes no longer eligible for a request")
        # Réservation enregistrée pour ce média : pas de renvoi immédiat après un timeout
        state = store.load_state()
        store.reserve_handoff(state, f"sonarr:season:{media_id}:{season_number}" if scope == "season" else f"{service}:{media_id}")
        journal.log(f"[{service}:{media_id}] MANUAL selection: "
                     f"'{matches[0].get('title', '?')}' "
                     f"(codec {ranking.video_codec(matches[0])}, "
                     f"{ranking.number_of_seeders(matches[0])} seeders, "
                     f"indexer: {str(matches[0].get('indexer') or matches[0].get('indexerName') or 'unknown')[:120]}); "
                     "hand-off requested from Radarr/Sonarr")
        if manual_test:
            # L'exception de test ne vaut que pour CET appel
            response = client.grab(matches[0], manual_test=True)
        else:
            response = client.grab(matches[0])
        # Certains services répondent 2xx avant l'apparition en file : un refus explicite dans le JSON reste un échec
        if isinstance(response, dict) and (response.get("success") is False or response.get("error")):
            raise RuntimeError(f"{service.title()} refused the release: {str(response.get('error') or response)[:200]}")
        if scope == "season" and config.get("TEAM_PREFERENCE", "off") != "off" and ranking.release_group(matches[0]):
            # Le choix manuel d'un pack devient l'équipe préférée de la série
            state.setdefault("series_teams", {})[str(media_id)] = ranking.release_group(matches[0])
            store.save_state(state)
        try:
            DeliveryTracker.register(service, min(episode_ids), matches[0], source="saison-manuel-test" if scope == "season" and manual_test else "manuel-test" if manual_test else "manuel")
            if scope == "season":
                journal.log(f"[sonarr:season:{media_id}:{season_number}] Season handed to Sonarr; tracking the send through episode sonarr:{min(episode_ids)}")
        except (OSError, ValueError, RuntimeError) as error:
            journal.log(f"[{service}:{media_id}] API response accepted, tracking unavailable: {type(error).__name__}", level="WARN")
        return {
            "ok": True, "simulation": False, "accepted_by_api": True,
            "confirmed_in_queue": False, "verifyMediaId": min(episode_ids),
            "message": f"Request accepted by the {service.title()} API. Checking the queue…",
        }
# =================================================


# ======================== SIMULATION D'UNE RECHERCHE ========================

# Série d'un épisode, sans relire tout l'inventaire ; en cas d'échec, pas de préférence d'équipe
def episode_series_id(client, episode_id):
    if not callable(getattr(client, "request", None)):
        return None
    try:
        episode = client.request("GET", f"episode/{episode_id}")
    except (requests.RequestException, ValueError, RuntimeError):
        return None
    return episode.get("seriesId") if isinstance(episode, dict) else None


# Montre ce que GentleSeed choisirait, sans rien envoyer (jamais de POST /release)
def preview_search(config, service, media_id, scope="episode", season_number=None, progress=None):
    # Chronométrage par étape : montre QUEL appel est lent ou expire.
    # progress (dict facultatif) reçoit l'étape en cours, pour le suivi dans le navigateur
    phase, last, timings = ["waiting for the lock"], [time.monotonic()], {}
    if progress is not None:
        progress["phase"] = phase[0]

    def step(name):
        now = time.monotonic()
        timings[phase[0]] = round(now - last[0], 2)
        phase[0], last[0] = name, now
        if progress is not None:
            progress["phase"] = name

    def timing_text():
        return ", ".join(f"{STEP_LABELS.get(k, k)}={v}s" for k, v in timings.items())

    try:
        # La simulation n'envoie JAMAIS de release, même hors DRY_RUN
        with OPERATION_LOCK:
            step("configuration")
            configure_engine(config)
            step("recherche")
            client = next(c for c in clients_for(config) if c.name == service)
            if scope == "season":
                if service != "sonarr" or type(season_number) is not int or season_number < 0:
                    raise RuntimeError("Invalid season search")
                step("version_sonarr")
                allow_anime = client.supports_anime_season_packs()
                step("inventaire_episodes")
                episodes = ranking.season_episodes(client.missing_items(), media_id, season_number,
                                                    allow_anime=allow_anime)
                if not episodes:
                    raise RuntimeError("The season must contain at least two missing, monitored episodes compatible with this Sonarr version")
                step("file_attente")
                queued = bool({ep["id"] for ep in episodes} & client.queued_ids())
                step("release_saison")
                releases = client.season_releases(media_id, season_number)
                step("classement")
                accepted = ranking.eligible_season_packs(releases, media_id, season_number)
            else:
                step("file_attente")
                queued = media_id in client.queued_ids()
                step("release")
                releases = client.releases(media_id)
                step("classement")
                accepted = ranking.eligible_releases(releases)
            # Même préférence d'équipe que l'automatique (sans chercher d'autres saisons : la simulation reste rapide)
            series_id = media_id if scope == "season" else None
            if service == "sonarr" and scope != "season" and ranking.TEAM_PREFERENCE != "off":
                series_id = episode_series_id(client, media_id)
            team = (selector.known_team(client, store.load_state().get("series_teams"), series_id)[0]
                    if series_id is not None else None)
            accepted.sort(key=lambda release: ranking.release_rank_key(release, team), reverse=True)
            chosen = accepted[0] if accepted else None

            approved = [{**visible_release(release), "guid": release["guid"],
                         "indexerId": release["indexerId"]} for release in accepted[:150]]
            rejected = []
            for r in releases:
                if r in accepted:
                    continue
                visible = visible_release(r)
                if scope == "season":
                    visible["reasons"] = ranking.season_pack_rejection_details(r, media_id, season_number)[:6]
                    visible["overridable"] = False  # pas de levée de refus de langue pour un pack de saison
                elif visible["overridable"]:
                    visible.update(guid=r["guid"], indexerId=r["indexerId"])  # nécessaire à l'envoi manuel
                rejected.append(visible)
                if len(rejected) >= 150:
                    break
        step("fin")
        journal.log(f"[TEST {service}:{media_id}] durations per step: {timing_text()}")
        codec_part = (f" [codec {ranking.video_codec(chosen)} ; {config.get('PREFERRED_CODEC', 'auto')} "
                      f"({config.get('CODEC_PRIORITY', 'equilibree')})]" if chosen else "")
        if chosen:
            journal.log(f"TEST {service}:{media_id}: {len(releases)} releases, "
                         f"{len(accepted)} eligible, simulated automatic recommendation: "
                         f"{chosen.get('title', '?')}{codec_part}")
        else:  # phrase complète : « none » collé au détail codec ne pouvait pas être traduit
            journal.log(f"TEST {service}:{media_id}: {len(releases)} releases, "
                         f"{len(accepted)} eligible, simulated automatic recommendation: no candidate")
        if not releases:
            journal.log(f"[TEST {service}:{media_id}] No release returned by {service.title()} for "
                         f"{'season ' + str(season_number) if scope == 'season' else 'this media'}. "
                         "Check the indexers and the media recognition in Radarr/Sonarr.", level="WARN")
        if not accepted and releases:
            diagnostic = (ranking.rejection_summary(releases,
                reasons_for=lambda row: ranking.season_pack_rejection_details(row, media_id, season_number))
                if scope == "season" else ranking.rejection_summary(releases))
            journal.log(f"[TEST {service}:{media_id}] {diagnostic}", level="WARN")
        state_name = 'empty' if not releases else ('rejected' if not accepted else 'results')
        return {"total": len(releases), "accepted": len(accepted), "queued": queued,
                "resultState": state_name,
                "selected": visible_release(chosen) if chosen else None,
                "service": service, "mediaId": media_id, "scope": scope,
                "seasonNumber": season_number, "verifyMediaId": min(ep["id"] for ep in episodes) if scope == "season" else media_id,
                "approved": approved, "rejected": rejected, "simulation": True}
    except (requests.RequestException, ValueError, RuntimeError) as error:
        code, message = SearchDiagnostics.describe_search_error(error, service, scope)
        step("failure")
        journal.log(f"Search {service}:{media_id} interrupted at step \"{list(timings)[-1]}\" "
                     f"(durations: {timing_text()}): {type(error).__name__}: {error}", level="ERROR")
        raise SearchFailed(code, message) from error
# =================================================
