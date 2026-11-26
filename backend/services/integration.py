# Intégration à la suite *arr : GentleSeed s'inscrit comme « Webhook » dans Radarr/Sonarr.
#
# Comme Prowlarr le fait pour ses applications, GentleSeed crée lui-même la notification « GentleSeed »
# (Réglages → Connect) via l'API de Radarr/Sonarr. Radarr/Sonarr le préviennent alors immédiatement d'un film ou
# d'une série ajouté. Le webhook ne fait que déclencher une vérification : il ne décide et n'envoie rien.

# ======================== IMPORTS ========================
import copy
import hmac
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from backend import private_file
from backend import settings as Settings
# =================================================


# ======================== CONFIGURATION ========================
NAME = "GentleSeed"
# Événement *arr qui signale un nouveau média, par service
EVENT_FLAGS = {"radarr": "onMovieAdded", "sonarr": "onSeriesAdd"}
EVENT_TYPES = {"MovieAdded": "radarr", "SeriesAdd": "sonarr"}
SERVICE_LABELS = {"radarr": "Radarr", "sonarr": "Sonarr"}
MAX_BODY = 65536
# =================================================


# ======================== JETON SECRET ========================

def token_file():
    return Path(os.environ.get("WEBHOOK_TOKEN_FILE", str(Settings.SETTINGS_FILE.parent / ".webhook-token")))


# Jeton du webhook, créé une seule fois (ouverture exclusive, droits 0600)
def token():
    return private_file.read_or_create(token_file(), lambda: secrets.token_urlsafe(32))


# Nouveau jeton (l'ancien cesse de fonctionner)
def regenerate_token():
    path = token_file()
    private_file.write(path, secrets.token_urlsafe(32))
    return path.read_text(encoding="utf-8").strip()


# Comparaison en temps constant
def valid_token(candidate):
    return isinstance(candidate, str) and hmac.compare_digest(candidate.encode(), token().encode())
# =================================================


# ======================== ADRESSE DU WEBHOOK ========================

# Adresse de GentleSeed telle que Radarr/Sonarr la voient (ex. http://192.168.1.10:1853)
def clean_base_url(raw):
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 200:
        raise ValueError("Invalid GentleSeed address")
    parts = urlsplit(raw.strip())
    if (parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username or parts.password or parts.query or parts.fragment
            or parts.path not in ("", "/")):
        raise ValueError("Invalid address: expected http://address:port, with no path or credentials")
    return f"{parts.scheme}://{parts.netloc}"


# Adresse locale probable de GentleSeed : l'hôte de Radarr/Sonarr (même serveur) + le port de GentleSeed.
# Jamais l'adresse du navigateur (domaine Cloudflare, etc.) : Radarr/Sonarr doivent joindre GentleSeed en local.
# Renvoie "" si aucun hôte utilisable (hôte vide ou boucle locale).
def suggest_base_url(service_urls, port):
    for raw in service_urls:
        try:
            parts = urlsplit(str(raw or "").strip())
            host = parts.hostname
        except ValueError:
            continue
        if not host or host in ("localhost", "::1") or host.startswith("127."):
            continue
        shown = f"[{host}]" if ":" in host else host
        return f"http://{shown}:{int(port)}"
    return ""


def webhook_url(base_url):
    return f"{clean_base_url(base_url)}/api/webhook/{token()}"


# Adresse sans le jeton (pour l'affichage et les journaux)
def masked(url):
    return str(url).split("/api/webhook/")[0] + "/api/webhook/••••" if "/api/webhook/" in str(url) else str(url)
# =================================================


# ======================== NOTIFICATION DANS RADARR / SONARR ========================

# Notre notification dans la liste de *arr (nom « GentleSeed » + type Webhook)
def find_ours(items):
    for item in items if isinstance(items, list) else []:
        if (isinstance(item, dict) and item.get("name") == NAME
                and str(item.get("implementation", "")).lower() == "webhook"):
            return item
    return None


def get_field(item, name):
    for field in item.get("fields") or []:
        if isinstance(field, dict) and field.get("name") == name:
            return field
    return None


# Corps de la notification : modèle officiel de l'API (schema), seul l'essentiel est modifié
def build_body(service, schema, url, existing=None):
    flag = EVENT_FLAGS[service]
    if existing is not None:
        body = copy.deepcopy(existing)
    else:
        template = next((s for s in schema if isinstance(s, dict)
                         and str(s.get("implementation", "")).lower() == "webhook"), None) if isinstance(schema, list) else None
        if template is None:
            raise ValueError(f"{SERVICE_LABELS[service]} does not offer a Webhook notification")
        body = copy.deepcopy(template)
    support = "supports" + flag[0].upper() + flag[1:]
    if body.get(support) is False:
        raise ValueError(f"This version of {SERVICE_LABELS[service]} does not offer the \"{flag}\" event")
    body["name"] = NAME
    body[flag] = True
    body.setdefault("tags", [])
    field = get_field(body, "url")
    if field is None:
        raise ValueError(f"{SERVICE_LABELS[service]}: webhook URL field not found")
    field["value"] = url
    return body


# État de l'intégration d'après la liste des notifications de *arr
def describe(service, items, base_url=None):
    label = SERVICE_LABELS[service]
    ours = find_ours(items)
    if ours is None:
        return {"state": "absent", "message": f"Not installed in {label}"}
    current = (get_field(ours, "url") or {}).get("value") or ""
    flag = EVENT_FLAGS[service]
    info = {"id": ours.get("id"), "address": masked(current), "event_enabled": bool(ours.get(flag))}
    if not ours.get(flag):
        return {**info, "state": "outdated", "message": "Installed, but the add event is disabled"}
    if base_url:
        try:
            expected = webhook_url(base_url)
        except ValueError:
            expected = None
        if expected and current != expected:
            return {**info, "state": "outdated", "message": "Installed with another address or an old token: reinstall"}
    return {**info, "state": "active", "message": f"Active: {label} notifies GentleSeed on every addition"}
# =================================================
