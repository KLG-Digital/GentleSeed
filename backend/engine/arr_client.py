# ======================== IMPORTS ========================
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from backend.engine import journal as journal
# =================================================


# ======================== CONFIGURATION ========================
REQUEST_TIMEOUT = 60  # remplacé par le réglage de l'interface
# La recherche d'une saison Sonarr interroge les indexeurs épisode par épisode :
# 25 à 130 s constatées. Délai dédié, sans toucher au délai des autres appels
SEASON_SEARCH_TIMEOUT = 240
# Recherche d'un film ou d'un épisode : interroge tous les indexeurs (Prowlarr), parfois plus de 60 s
RELEASE_SEARCH_TIMEOUT = 120
# =================================================


# ======================== ERREUR DE LIMITATION ========================

# Radarr/Sonarr a répondu 429 : on attend avant de réessayer
class RateLimitedError(RuntimeError):
    def __init__(self, retry_after):
        self.retry_after = retry_after
        super().__init__(f"HTTP 429: pausing for {retry_after} seconds")
# =================================================


# ======================== CLIENT RADARR / SONARR ========================

# Client HTTP commun à Radarr et Sonarr (API v3, et v5 pour Sonarr)
class ArrClient:

    def __init__(self, name, url, api_key):
        self.name = name
        self.url = url
        self.session = requests.Session()
        self.session.headers.update({"X-Api-Key": api_key, "Accept": "application/json"})

    # --------------------- REQUÊTES ---------------------

    # Envoie une requête. Sonarr v5 expose /api/v5, les anciennes versions /api/v3 :
    # la version est choisie lors d'un premier GET (jamais d'essai automatique d'un POST en double)
    def request(self, method, path, **kwargs):
        version = getattr(self, "api_version", "v3")
        timeout = kwargs.pop("timeout", None) or getattr(self, "timeout", None) or REQUEST_TIMEOUT
        started = time.monotonic()
        response = self.session.request(
            method, f"{self.url}/api/{version}/{path.lstrip('/')}", timeout=timeout, **kwargs
        )
        # Un chemin de lecture absent de /api/v3 (history/episode, par exemple) est lu sur v5, pour cette requête seulement.
        # Le client ne passe durablement sur v5 que si /api/v3 ne répond plus du tout : sinon les écritures suivantes
        # (notification…) partiraient sur une API qui ne les propose pas
        if (self.name == "sonarr" and method.upper() == "GET" and version == "v3"
                and response.status_code in (404, 405)):
            second = self.session.request(
                method, f"{self.url}/api/v5/{path.lstrip('/')}", timeout=timeout, **kwargs
            )
            if second.ok:
                response = second
                if (path.lstrip("/") == "system/status"
                        or self.session.request("GET", f"{self.url}/api/v3/system/status",
                                                timeout=timeout).status_code in (404, 405)):
                    self.api_version = "v5"
        # Niveau Debug : chaque requête (méthode, service, chemin, code, durée), jamais la clé API ; le sondage léger est exclu
        if path.lstrip("/") != "wanted/missing":
            journal.log(f"{method.upper()} {self.name} /{path.lstrip('/')} → {response.status_code} "
                        f"({time.monotonic() - started:.2f} s)", level="DEBUG")
        # 429 : pas de nouvel essai immédiat, on lit le délai demandé (entre 1 min et 24 h)
        if response.status_code == 429:
            delay = 900
            raw = response.headers.get("Retry-After", "")
            try:
                delay = int(raw)
            except (TypeError, ValueError):
                try:
                    delay = (parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    pass
            raise RateLimitedError(max(60, min(int(delay), 86400)))
        response.raise_for_status()
        return response.json() if response.content else {}

    # --------------------- CATALOGUE ---------------------

    # Identifiants de TOUS les films/séries, même déjà téléchargés : un fichier disparu
    # ou un nouvel épisode d'une ancienne série ne doit pas passer pour une nouvelle entrée
    # rows : liste déjà lue (une seule lecture du catalogue par cycle, voir inventory)
    def catalog_ids(self, rows=None):
        endpoint = "movie" if self.name == "radarr" else "series"
        rows = rows if rows is not None else self.request("GET", endpoint)
        if not isinstance(rows, list):
            raise RuntimeError(f"[{self.name}] Incomplete catalog: analysis interrupted")
        ids = set()
        for row in rows:
            if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] < 1:
                raise RuntimeError(f"[{self.name}] Invalid catalog entry: analysis interrupted")
            ids.add(row["id"])
        return ids

    # --------------------- MÉDIAS MANQUANTS ---------------------

    # Manquants et catalogue d'un coup : la liste complète des films ou séries n'est téléchargée qu'une fois
    def inventory(self):
        rows = self.request("GET", "movie" if self.name == "radarr" else "series")
        return self.missing_items(rows), self.catalog_ids(rows)

    # Films ou épisodes manquants et surveillés (library : liste des films ou séries déjà lue)
    def missing_items(self, library=None):
        if self.name == "radarr":
            movies = library if library is not None else self.request("GET", "movie")
            if not isinstance(movies, list) or any(not isinstance(m, dict) or type(m.get("id")) is not int for m in movies):
                raise RuntimeError("[radarr] Invalid inventory: analysis interrupted")
            return [
                {"key": f"radarr:{m['id']}", "id": m["id"], "title": m.get("title", str(m["id"]))}
                for m in movies
                if m.get("monitored") and not m.get("hasFile") and m.get("isAvailable", False)
            ]

        # Sonarr : les épisodes déjà diffusés viennent de wanted/missing.
        # Pagination complète, pour ne pas prendre de vieux épisodes pour des nouveautés
        all_series = library if library is not None else self.request("GET", "series")
        if not isinstance(all_series, list) or any(not isinstance(s, dict) or type(s.get("id")) is not int for s in all_series):
            raise RuntimeError("[sonarr] Invalid series catalog: analysis interrupted")
        series = {s["id"]: s for s in all_series}
        page, page_size, result = 1, 250, []
        while True:
            data = self.request("GET", "wanted/missing", params={
                "page": page, "pageSize": page_size, "monitored": "true",
                "sortKey": "airDateUtc", "sortDirection": "descending"
            })
            if (not isinstance(data, dict) or
                    type(data.get("totalRecords")) is not int or data["totalRecords"] < 0 or
                    not isinstance(data.get("records"), list)):
                raise RuntimeError("[sonarr] Invalid inventory pagination: analysis interrupted")
            records = data["records"]
            if (not records and (page - 1) * page_size < data["totalRecords"] or
                    any(not isinstance(e, dict) or type(e.get("id")) is not int for e in records)):
                raise RuntimeError("[sonarr] Incomplete inventory: analysis interrupted")
            for e in records:
                s = series.get(e.get("seriesId"), {})
                if not e.get("monitored") or not s.get("monitored"):
                    continue
                result.append({
                    "key": f"sonarr:{e['id']}", "id": e["id"], "seriesId": e.get("seriesId"),
                    "title": f"{s.get('title', 'Series')} - S{e.get('seasonNumber', 0):02d}E{e.get('episodeNumber', 0):02d}",
                    "seasonNumber": e.get("seasonNumber"), "episodeNumber": e.get("episodeNumber"),
                    "seriesType": s.get("seriesType", "standard"),
                })
            if not records or page * page_size >= data.get("totalRecords", 0):
                break
            page += 1
        return result

    # --------------------- NOTIFICATIONS (WEBHOOK) ---------------------

    # Liste des notifications configurées
    def notification_list(self):
        data = self.request("GET", "notification")
        if not isinstance(data, list):
            raise RuntimeError(f"[{self.name}] Invalid notification list")
        return data

    # Modèles de notification disponibles (dont Webhook)
    def notification_schema(self):
        data = self.request("GET", "notification/schema")
        if not isinstance(data, list):
            raise RuntimeError(f"[{self.name}] Invalid notification templates")
        return data

    # Crée la notification, ou la met à jour si elle a déjà un identifiant
    def notification_save(self, body):
        if body.get("id"):
            return self.request("PUT", f"notification/{int(body['id'])}", json=body)
        return self.request("POST", "notification", json=body)

    # Supprime une notification
    def notification_delete(self, notification_id):
        return self.request("DELETE", f"notification/{int(notification_id)}")

    # Demande à Radarr/Sonarr d'envoyer une notification de test
    def notification_test(self, body):
        return self.request("POST", "notification/test", json=body)

    # --------------------- HISTORIQUE ---------------------

    # Historique d'un épisode Sonarr. « history/episode » n'existe pas partout : à défaut, l'historique général filtré
    def episode_history(self, episode_id):
        try:
            return self.request("GET", "history/episode", params={"episodeId": episode_id})
        except requests.HTTPError as error:
            if getattr(error.response, "status_code", None) not in (404, 405):
                raise
        data = self.request("GET", "history", params={"episodeId": episode_id, "page": 1, "pageSize": 100,
                                                       "sortKey": "date", "sortDirection": "descending"})
        if not isinstance(data, dict) or not isinstance(data.get("records"), list):
            raise RuntimeError(f"[{self.name}] Invalid history response")
        return [row for row in data["records"]
                if not isinstance(row, dict) or row.get("episodeId") in (None, episode_id)]

    # Vrai si Radarr/Sonarr a déjà pris une release pour ce média dans les dernières secondes.
    # L'historique est à jour tout de suite, la file d'attente seulement après quelques secondes
    # (cas d'une recherche automatique lancée à l'ajout). Échec fermé : une réponse
    # illisible ou une date inconnue comptent comme « récent »
    def recently_grabbed(self, media_id, seconds=900):
        rows = (self.request("GET", "history/movie", params={"movieId": media_id}) if self.name == "radarr"
                else self.episode_history(media_id))
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise RuntimeError(f"[{self.name}] Invalid history: send cancelled")
        now = datetime.now(timezone.utc)
        for row in rows:
            if str(row.get("eventType", "")).lower() != "grabbed":
                continue
            try:
                when = datetime.fromisoformat(str(row.get("date", "")).replace("Z", "+00:00"))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
            except ValueError:
                return True
            if (now - when).total_seconds() < seconds:
                return True
        return False

    # --------------------- SONDAGE LÉGER ---------------------

    # Nombre de médias manquants et surveillés, en UNE petite requête (pageSize=1).
    # Sert seulement à repérer une nouvelle demande entre deux cycles : aucun envoi n'en dépend
    def demand_count(self):
        data = self.request("GET", "wanted/missing",
                            params={"page": 1, "pageSize": 1, "monitored": "true"})
        total = data.get("totalRecords") if isinstance(data, dict) else None
        if type(total) is not int or total < 0:
            raise RuntimeError(f"[{self.name}] Invalid polling response")
        return total

    # --------------------- FILE D'ATTENTE ---------------------

    # Identifiants des médias déjà en file. Si la file ne peut pas être vérifiée,
    # aucun téléchargement n'est lancé
    def queued_ids(self):
        page, page_size, found = 1, 250, set()
        expected_total = None
        while True:
            data = self.request("GET", "queue", params={"page": page, "pageSize": page_size})
            # Échec fermé : une réponse tronquée ne doit JAMAIS passer pour une file vide
            # (elle pourrait créer un doublon)
            if (not isinstance(data, dict) or
                    not isinstance(data.get("records"), list) or
                    type(data.get("totalRecords")) is not int or
                    data["totalRecords"] < 0):
                raise RuntimeError(f"[{self.name}] Invalid API queue: download cancelled")
            records = data["records"]
            if expected_total is None:
                expected_total = data["totalRecords"]
            elif data["totalRecords"] != expected_total:
                raise RuntimeError(f"[{self.name}] Queue changed during pagination: send cancelled")
            # Un total positif avec une page vide : réponse incomplète
            if not records and (page - 1) * page_size < data["totalRecords"]:
                raise RuntimeError(f"[{self.name}] Incomplete queue pagination: download cancelled")
            if any(not isinstance(entry, dict) for entry in records):
                raise RuntimeError(f"[{self.name}] Invalid queue entry: download cancelled")
            for entry in records:
                if self.name == "radarr":
                    if entry.get("movieId") is not None:
                        found.add(int(entry["movieId"]))
                else:
                    raw_ids = entry.get("episodeIds")
                    ids = list(raw_ids) if isinstance(raw_ids, list) else []
                    ids += [e["id"] for e in entry.get("episodes", []) if isinstance(e, dict) and e.get("id")]
                    if entry.get("episodeId") is not None:
                        ids.append(entry["episodeId"])
                    found.update(int(i) for i in ids)
            if not records or page * page_size >= data.get("totalRecords", 0):
                break
            page += 1
        return found

    # --------------------- RESULTATS DE RECHERCHE ---------------------

    # Ramène le format imbriqué de Sonarr v5 vers les champs utilisés par GentleSeed.
    # Sans décision explicite, rien n'est envoyé (échec fermé) : la structure brute
    # ne suffit jamais à approuver un torrent
    def _normalize_releases(self, rows):
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise RuntimeError(f"[{self.name}] Invalid releases response")
        # Chaque release porte son service : les réglages (indexeurs ignorés) sont propres à Radarr et à Sonarr
        if self.name != "sonarr":
            return [{**row, "gentleseedService": self.name} for row in rows]
        normalized = []
        for row in rows:
            if not isinstance(row.get("release"), dict):
                normalized.append({**row, "gentleseedService": self.name})  # Sonarr v3/v4 : format historique
                continue
            release = row["release"]
            decision = row.get("decision")
            parsed = row.get("parsedInfo") or {}
            reasons = None
            if isinstance(decision, dict) and isinstance(decision.get("rejections"), list):
                reasons = [str(v.get("message", "Rejection without details")) if isinstance(v, dict) else str(v)
                           for v in decision["rejections"]]
            season_numbers = parsed.get("seasonNumbers") if isinstance(parsed, dict) else None
            if isinstance(season_numbers, list):
                # Une release multi-saisons ne doit pas passer pour une seule
                season_number = (season_numbers[0] if len(season_numbers) == 1
                                 and type(season_numbers[0]) is int else None)
            else:
                season_number = row.get("mappedSeasonNumber")
            normalized.append({
                "guid": release.get("guid"), "indexerId": release.get("indexerId"),
                "title": release.get("title"), "indexer": release.get("indexer"),
                "releaseGroup": (parsed.get("releaseGroup") if isinstance(parsed, dict) else None) or release.get("releaseGroup"),
                "infoUrl": release.get("infoUrl"),
                "protocol": release.get("protocol"), "seeders": release.get("seeders"),
                "leechers": release.get("leechers"), "size": release.get("size"),
                "rejections": reasons, "downloadAllowed": row.get("downloadAllowed") is True,
                "approved": decision.get("approved") if isinstance(decision, dict) else False,
                "rejected": decision.get("rejected", True) if isinstance(decision, dict) else True,
                "temporarilyRejected": decision.get("temporarilyRejected", False) if isinstance(decision, dict) else True,
                "seriesId": row.get("mappedSeriesId"), "seasonNumber": season_number,
                "fullSeason": parsed.get("fullSeason") if isinstance(parsed, dict) else False,
                "quality": parsed.get("quality") if isinstance(parsed, dict) else {},
                "gentleseedService": self.name,
            })
        return normalized

    # Recherche interactive d'un film ou d'un épisode
    def releases(self, item_id):
        param = "movieId" if self.name == "radarr" else "episodeId"
        data = self.request("GET", "release", params={param: item_id},
                            timeout=max(REQUEST_TIMEOUT, RELEASE_SEARCH_TIMEOUT))
        # Structure d'API changée : recherche abandonnée, aucune sélection à l'aveugle
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise RuntimeError(f"Unexpected response from {self.name.title()} for the interactive search")
        return self._normalize_releases(data)

    # Recherche interactive d'une saison entière (Sonarr interroge ses indexeurs, dont Prowlarr).
    # Identifiants positifs et numéro de saison non négatif exigés
    def episode_file_groups(self, series_id):
        # Équipes des fichiers d'épisodes déjà présents dans Sonarr (lecture seule)
        rows = self.request("GET", "episodefile", params={"seriesId": series_id})
        if not isinstance(rows, list):
            raise RuntimeError("[sonarr] Invalid episode file list")
        return [str(row.get("releaseGroup") or "").strip() for row in rows if isinstance(row, dict)]

    def season_releases(self, series_id, season_number):
        if self.name != "sonarr" or type(series_id) is not int or series_id < 1 or type(season_number) is not int or season_number < 0:
            raise ValueError("Invalid Sonarr season search")
        data = self.request("GET", "release", params={"seriesId": series_id, "seasonNumber": season_number},
                            timeout=max(REQUEST_TIMEOUT, SEASON_SEARCH_TIMEOUT))
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise RuntimeError("[sonarr] Incomplete season results: selection cancelled")
        return self._normalize_releases(data)

    # Sonarr v5 recherche mieux les saisons d'anime. Sur les versions anciennes, la recherche
    # interroge chaque épisode et peut saturer les indexeurs : pas de pack par saison.
    # Une erreur de statut n'autorise jamais cette option
    def supports_anime_season_packs(self):
        if self.name != "sonarr":
            return False
        if hasattr(self, "_anime_season_packs_supported"):
            return self._anime_season_packs_supported
        try:
            status = self.request("GET", "system/status")
            version = status.get("version", "") if isinstance(status, dict) else ""
            major = int(str(version).split(".", 1)[0])
        except (ValueError, TypeError, KeyError, requests.RequestException, RuntimeError):
            # Échec fermé, mais non mémorisé : une panne passagère ne désactive pas l'option durablement
            return False
        self._anime_season_packs_supported = major >= 5
        return self._anime_season_packs_supported

    # --------------------- TRANSMISSION DU CHOIX ---------------------

    # Demande à Radarr/Sonarr de prendre la release (guid + indexeur) d'une recherche juste faite.
    # Rien n'est transmis à Prowlarr ni à qBittorrent : l'ajout en file passe par le client configuré
    def grab(self, release, *, manual_test=False):
        return self.request("POST", "release", json={
            "guid": release["guid"], "indexerId": release["indexerId"]
        })
# =================================================
