# Historique des versions et détection d'une mise à jour (dépôt GitHub public).
#
# Une seule requête sortante : GET https://api.github.com/repos/<propriétaire>/<dépôt>/releases, sans authentification, avec
# un User-Agent « GentleSeed/<version> ». Rien d'autre n'est envoyé (ni réglages, ni adresses, ni clés). Résultat gardé 6 h en
# mémoire. GentleSeed ne se met JAMAIS à jour tout seul : il informe seulement.

# ======================== IMPORTS ========================
import re
import threading
import time

import requests

from backend.version import VERSION
# =================================================


# ======================== CONFIGURATION ========================
CURRENT = VERSION
DEFAULT_REPO = "KLG-Digital/GentleSeed"
DOCKER_IMAGE = "starkev/gentleseed"  # image publiée sur Docker Hub (synchronisée avec les releases GitHub)
DOCKER_URL = "https://hub.docker.com/r/starkev/gentleseed"
REPO_REGEX = r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/(?!\.{1,2}$)[A-Za-z0-9._-]{1,100}"  # propriétaire/dépôt GitHub
REPO_PATTERN = re.compile(rf"^{REPO_REGEX}$")
CACHE_SECONDS = 6 * 3600
MIN_REFRESH_SECONDS = 60
API_HOST = "api.github.com"

_LOCK = threading.Lock()
_FETCH_LOCK = threading.Lock()  # une seule requête GitHub à la fois, sans bloquer la lecture du cache
_CACHE = {"repo": None, "at": 0.0, "data": None}
# =================================================


# ======================== VERSIONS ========================

# « v1.2.3-beta » → (1, 2, 3). Renvoie None si ce n'est pas une version numérique.
def parse_version(text):
    match = re.match(r"^v?(\d+)\.(\d+)(?:\.(\d+))?", str(text or "").strip())
    return tuple(int(part or 0) for part in match.groups()) if match else None


# Texte venant de GitHub : caractères imprimables seulement, longueur limitée
def _clean(text, limit):
    return "".join(ch for ch in str(text or "") if ch.isprintable() or ch in "\n\t")[:limit].strip()


# Garde d'une release GitHub uniquement les champs utiles (le lien doit rester sur github.com)
def _release(row):
    url = str(row.get("html_url") or "")
    return {"tag": _clean(row.get("tag_name"), 40), "name": _clean(row.get("name") or row.get("tag_name"), 120),
            "published": _clean(row.get("published_at"), 30), "prerelease": bool(row.get("prerelease")),
            "notes": _clean(row.get("body"), 4000),
            "url": url if url.startswith("https://github.com/") and len(url) < 300 else ""}


# Dernière version stable et présence d'une mise à jour
def summarize(releases, current=CURRENT):
    versions = [(parse_version(r["tag"]), r) for r in releases if not r["prerelease"]]
    versions = [(v, r) for v, r in versions if v]
    latest = max(versions, key=lambda item: item[0])[1] if versions else None
    here = parse_version(current)
    return {"latest": latest["tag"] if latest else None,
            "update_available": bool(latest and here and parse_version(latest["tag"]) > here),
            "latest_url": latest["url"] if latest else ""}
# =================================================


# ======================== INTERROGATION DE GITHUB ========================

# Interroge GitHub. Lève RuntimeError (message pour l'utilisateur) en cas de problème.
def fetch(repo, session=None, timeout=6):
    if not REPO_PATTERN.match(repo or ""):
        raise RuntimeError("Invalid repository: expected format owner/repository")
    try:
        response = (session or requests).get(
            f"https://{API_HOST}/repos/{repo}/releases?per_page=15", timeout=timeout,
            headers={"Accept": "application/vnd.github+json", "User-Agent": f"GentleSeed/{CURRENT}"})
    except requests.RequestException as error:
        raise RuntimeError(f"GitHub unreachable ({type(error).__name__})") from error
    if requests.utils.urlparse(response.url).hostname != API_HOST:
        raise RuntimeError("Unexpected response (redirect refused)")
    if response.status_code == 404:
        raise RuntimeError("Repository not found or without a published release")
    if response.status_code in (403, 429):
        raise RuntimeError("GitHub rate limit reached: try again later")
    if not response.ok:
        raise RuntimeError(f"GitHub replied HTTP {response.status_code}")
    try:
        rows = response.json()
    except ValueError as error:
        raise RuntimeError("Unreadable GitHub response") from error
    if not isinstance(rows, list):
        raise RuntimeError("Unexpected GitHub response")
    return [_release(row) for row in rows if isinstance(row, dict) and not row.get("draft")]


# Résultat en cache (6 h). `force` ignore le cache, mais pas plus d'une fois par minute.
# Le verrou du cache n'est jamais tenu pendant l'appel réseau : l'état (cached) reste toujours lisible
def check(repo, force=False, fetcher=None, now=time.time):
    with _FETCH_LOCK:
        with _LOCK:
            age = now() - _CACHE["at"]
            same = _CACHE["repo"] == repo and _CACHE["data"] is not None
            if same and (age < MIN_REFRESH_SECONDS or (not force and age < CACHE_SECONDS)):
                return _CACHE["data"]
        releases = (fetcher or fetch)(repo)
        data = {"releases": releases, "checked_at": now(), **summarize(releases)}
        with _LOCK:
            _CACHE.update(repo=repo, at=now(), data=data)
        return data


# Dernier résultat connu, sans aucun accès réseau
def cached():
    with _LOCK:
        return _CACHE["data"]


def reset():
    with _LOCK:
        _CACHE.update(repo=None, at=0.0, data=None)
# =================================================
