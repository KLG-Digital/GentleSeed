# ======================== IMPORTS ========================
import json
import os
import re
import threading

from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend import private_file
# =================================================


# ======================== CONFIGURATION ========================
SETTINGS_FILE = Path(os.environ.get("SETTINGS_FILE", "/data/settings.json"))
LOCK = threading.RLock()


# Lit une variable d'environnement oui/non
def _boolean(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ("true", "1", "oui", "yes")


# --------------------- VALEURS PAR DÉFAUT ---------------------
# Tout se règle dans l'interface. Seules 3 variables d'environnement existent :
# AUTO_ENABLED (main.py démarre surveillance arrêtée), UPDATE_CHECK (couper l'accès à GitHub, ex. tests), DRY_RUN (développement)
DEFAULTS = {
    "RADARR_URL": "",
    "RADARR_API_KEY": "",
    "SONARR_URL": "",
    "SONARR_API_KEY": "",
    "DRY_RUN": _boolean("DRY_RUN", False),
    "ONLY_NEW": True,
    "INTEGRATION_BASE_URL": "",
    "INTEGRATION_CLEANUP": True,
    "INTEGRATION_RADARR": False,
    "INTEGRATION_SONARR": False,
    "UPDATE_CHECK": _boolean("UPDATE_CHECK", True),
    "UPDATE_REPO": "KLG-Digital/GentleSeed",
    "AUTO_ENABLED": _boolean("AUTO_ENABLED", True),
    "MIN_SEEDERS": 1,
    "ALLOW_UNKNOWN_SEEDERS": False,
    "PREFERRED_CODEC": "auto",
    "CODEC_PRIORITY": "equilibree",
    "TEAM_PREFERENCE": "off",
    "CHECK_INTERVAL": 300,
    "PROBE_INTERVAL": 15,
    "NEW_DEMAND_DELAY": 0,
    "RETRY_INTERVAL": 21600,
    "REQUEST_TIMEOUT": 60,
    "MAX_SEARCHES_PER_CYCLE": 2,
    "IGNORED_INDEXERS_RADARR": [],
    "IGNORED_INDEXERS_SONARR": [],
    "LANGUAGE_FALLBACK_AFTER": 0,
    "UI_THEME": "sombre",
    "UI_LANGUAGE": "auto",
    "UI_TIMEZONE": "auto",
    "UI_HOUR_FORMAT": "auto",
    "UI_DATE_FORMAT": "auto",
    "UI_SHOW_SECONDS": True,
    "LOG_LEVEL": "INFO",
}

# --------------------- LIMITES ET TYPES ---------------------
# Entiers : valeur minimale et maximale acceptées
INT_LIMITS = {
    "MIN_SEEDERS": (0, 10000),
    "CHECK_INTERVAL": (60, 86400),
    "PROBE_INTERVAL": (5, 600),
    "NEW_DEMAND_DELAY": (0, 600),
    "RETRY_INTERVAL": (600, 604800),
    "REQUEST_TIMEOUT": (5, 300),
    "MAX_SEARCHES_PER_CYCLE": (1, 20),
    "LANGUAGE_FALLBACK_AFTER": (0, 50),  # 0 = jamais : les refus de langue de Radarr/Sonarr sont toujours respectés
}
# Listes de noms d'indexeurs à ignorer (par service)
INDEXER_LIST_KEYS = {"IGNORED_INDEXERS_RADARR", "IGNORED_INDEXERS_SONARR"}
BOOL_KEYS = {"INTEGRATION_CLEANUP", "INTEGRATION_RADARR", "INTEGRATION_SONARR", "UPDATE_CHECK", "ONLY_NEW",
             "AUTO_ENABLED", "ALLOW_UNKNOWN_SEEDERS", "UI_SHOW_SECONDS"}
API_KEYS = {"RADARR_API_KEY", "SONARR_API_KEY"}
URL_KEYS = {"RADARR_URL", "SONARR_URL", "INTEGRATION_BASE_URL"}
# Réglages à choix limité : valeurs autorisées
CHOICES = {
    "UI_THEME": {"sombre", "clair", "auto", "maillot-rose", "maillot-noir", "maillot-paris", "maillot-worlds", "maillot-violet"},
    "UI_LANGUAGE": {"auto", "fr", "en", "de", "es", "it", "pt-PT", "pt-BR", "nl", "pl", "ru", "ja", "ko", "zh-CN", "uk"},
    "UI_HOUR_FORMAT": {"auto", "12", "24"},
    "UI_DATE_FORMAT": {"auto", "ch", "eu", "us", "iso"},
    "LOG_LEVEL": {"INFO", "WARN", "ERROR", "DEBUG"},
    "PREFERRED_CODEC": {"auto", "h264", "h265"},
    "CODEC_PRIORITY": {"faible", "equilibree", "forte"},
    "TEAM_PREFERENCE": {"off", "faible", "equilibree", "forte"},
}
# =================================================


# ======================== LECTURE ========================

# Lit les réglages : valeurs par défaut, puis ce qui est enregistré dans settings.json
def load_settings():
    with LOCK:
        current = DEFAULTS.copy()
        if SETTINGS_FILE.exists():
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                raise ValueError("Invalid saved configuration")
            current.update({key: value for key, value in saved.items() if key in DEFAULTS})
        # Plus de « mode » dans l'interface : un ancien DRY_RUN enregistré est ignoré
        current["DRY_RUN"] = DEFAULTS["DRY_RUN"]
        return current
# =================================================


# ======================== VALIDATION ========================

# Contrôle une demande de modification et renvoie la configuration complète à enregistrer
def validate_settings(data):
    if not isinstance(data, dict):
        raise ValueError("Invalid configuration")
    # Anciens clients : ces deux champs n'existent plus
    data = {key: value for key, value in data.items() if key not in ("DRY_RUN", "confirm_live")}
    unknown = set(data) - set(DEFAULTS)
    if unknown:
        raise ValueError("Unknown settings: " + ", ".join(sorted(unknown)))

    with LOCK:
        config = load_settings()

        # --------------------- OUI / NON ---------------------
        for key in BOOL_KEYS:
            if key in data:
                if not isinstance(data[key], bool):
                    raise ValueError(f"{key} must be true or false")
                config[key] = data[key]

        # --------------------- NOMBRES ---------------------
        for key, (low, high) in INT_LIMITS.items():
            if key in data:
                value = data[key]
                if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                    raise ValueError(f"{key} must be between {low} and {high}")
                config[key] = value

        # --------------------- INDEXEURS IGNORÉS ---------------------
        for key in INDEXER_LIST_KEYS:
            if key in data:
                names = data[key]
                if not isinstance(names, list) or len(names) > 500 or any(not isinstance(name, str) for name in names):
                    raise ValueError(f"Invalid value for {key}")
                cleaned = list(dict.fromkeys(name.strip() for name in names if name.strip()))
                if any(len(name) > 120 for name in cleaned):
                    raise ValueError(f"Invalid value for {key}")
                config[key] = cleaned

        # --------------------- CHOIX LIMITÉS ---------------------
        for key, values in CHOICES.items():
            if key in data:
                if not isinstance(data[key], str) or data[key] not in values:
                    raise ValueError(f"Invalid value for {key}")
                config[key] = data[key]

        # --------------------- FUSEAU HORAIRE ---------------------
        if "UI_TIMEZONE" in data:
            zone = data["UI_TIMEZONE"]
            if not isinstance(zone, str) or len(zone) > 80 or not re.fullmatch(r"[A-Za-z0-9_+\-/]+", zone):
                raise ValueError("Invalid time zone")
            if zone != "auto":
                if zone.startswith("/") or ".." in zone or "//" in zone:
                    raise ValueError("Invalid IANA time zone")
                try:
                    ZoneInfo(zone)
                except ZoneInfoNotFoundError as error:
                    raise ValueError("Unknown IANA time zone (install tzdata)") from error
            config["UI_TIMEZONE"] = zone

        # --------------------- DÉPÔT DES MISES À JOUR ---------------------
        if "UPDATE_REPO" in data:
            repo = data["UPDATE_REPO"].strip() if isinstance(data["UPDATE_REPO"], str) else None
            if repo is None or (repo and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/(?!\.{1,2}$)[A-Za-z0-9._-]{1,100}", repo)):
                raise ValueError("Invalid repository: format owner/repository (e.g. KLG-Digital/GentleSeed)")
            config["UPDATE_REPO"] = repo

        # --------------------- ADRESSES ---------------------
        for key in URL_KEYS:
            if key in data:
                url = data[key].strip() if isinstance(data[key], str) else ""
                if not url:
                    config[key] = ""
                    continue
                parsed = urlsplit(url)
                if (parsed.scheme not in ("http", "https") or not parsed.hostname or
                        parsed.username or parsed.password or parsed.query or parsed.fragment or
                        # Radarr et Sonarr peuvent avoir une « URL Base » (/radarr) ; l'adresse de GentleSeed, non
                        (parsed.path not in ("", "/") and key not in ("RADARR_URL", "SONARR_URL")) or
                        len(url) > 250 or any(ord(char) < 33 for char in url)):
                    raise ValueError(f"Invalid {key} address: example http://radarr:7878")
                try:
                    _ = parsed.port
                except ValueError as error:
                    raise ValueError(f"Invalid port for {key}") from error
                config[key] = url.rstrip("/")

        # --------------------- CLÉS API ---------------------
        # Champ vide = on garde l'ancienne clé (jamais de suppression par accident)
        for key in API_KEYS:
            if key in data:
                raw = data[key]
                if not isinstance(raw, str) or len(raw) > 250:
                    raise ValueError(f"Invalid key for {key}")
                if raw.strip():
                    config[key] = raw.strip()

        return config
# =================================================


# ======================== CLÉ ET ADRESSE ========================

# Services dont l'adresse change alors que la clé déjà enregistrée serait conservée : la clé partirait
# vers la nouvelle adresse sans que personne l'ait retapée. Vider puis remettre l'adresse ne contourne rien
def moved_without_key(before, config, data):
    moved = []
    for service in ("RADARR", "SONARR"):
        url, old = str(config[f"{service}_URL"]).rstrip("/"), str(before[f"{service}_URL"]).rstrip("/")
        typed = str(data.get(f"{service}_API_KEY") or "").strip()
        if url and url != old and before[f"{service}_API_KEY"] and not typed:
            moved.append(service)
    return moved
# =================================================


# ======================== ENREGISTREMENT ========================

# Écrit settings.json d'un seul coup (fichier privé 0600 puis remplacement)
def save_settings(config):
    with LOCK:
        private_file.write(SETTINGS_FILE, json.dumps(config, ensure_ascii=False, indent=2))


# Réglages pour l'interface : jamais les clés API, seulement « clé enregistrée oui/non »
def public_settings():
    config = load_settings()
    return {key: value for key, value in config.items() if key not in API_KEYS} | {
        "RADARR_API_KEY_SET": bool(config["RADARR_API_KEY"]),
        "SONARR_API_KEY_SET": bool(config["SONARR_API_KEY"]),
    }
# =================================================
