# Sauvegarde et restauration des réglages de GentleSeed.
#
# Un fichier de sauvegarde est un JSON lisible (réglages seulement : la mémoire du moteur se reconstruit au premier passage). Par défaut il NE CONTIENT PAS les clés API :
# après une restauration, les clés actuelles sont conservées. On peut les inclure explicitement ; le fichier donne alors
# accès à Radarr/Sonarr, comme le fichier de réglages lui-même.
#
# Jamais sauvegardés : mot de passe (auth.json), secret de session, jeton du webhook, jetons d'autorisation temporaires.

# ======================== IMPORTS ========================
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from backend import private_file
from backend import settings as Settings
from backend.version import VERSION
# =================================================


# ======================== CONFIGURATION ========================
FORMAT = "gentleseed-backup"
KEEP = 10  # nombre de sauvegardes conservées (les plus anciennes sont supprimées)
KEEP_SAFETY = 3  # copies de sécurité faites avant une restauration : comptées à part, pour ne pas chasser les sauvegardes
MAX_BYTES = 1_000_000  # taille maximale acceptée à la restauration
# Nom : gentleseed-backup-2026-11-22_15-38-58[-pre-restore].json (année-mois-jour, comme les journaux, heure UTC).
# L'ancien format 20261122-153858 reste accepté
NAME_PATTERN = re.compile(r"^gentleseed-backup-(?:\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}|\d{8}-\d{6})(?:-[a-z]+(?:-[a-z]+)*)?\.json$")


# Copie faite automatiquement avant une restauration (« -restore » : ancien nom, encore reconnu)
def is_safety_copy(path):
    return path.name.endswith(("-pre-restore.json", "-restore.json"))


# Clé de tri : les 14 chiffres de la date et de l'heure, identiques dans les deux formats de nom
def name_order(path):
    return re.sub(r"\D", "", path.name.removeprefix("gentleseed-backup-"))[:14] + path.name
STATE_LISTS = ("known", "tracked", "new_series", "new_movies", "baselined_services")
STATE_DICTS = ("catalog_baselines", "last_attempt", "timeout_hits")
LOCK = threading.Lock()


# Message destiné à l'utilisateur
class BackupError(ValueError):
    pass


# Dossier des sauvegardes (BACKUP_DIR, sinon « backups » à côté des réglages)
def backup_dir():
    return Path(os.environ.get("BACKUP_DIR") or (Settings.SETTINGS_FILE.parent / "backups"))


def _now():
    return datetime.now(timezone.utc)
# =================================================


# ======================== CONTENU D'UNE SAUVEGARDE ========================

# Lecture des anciennes sauvegardes qui contenaient l'état du moteur : on n'en garde que les champs connus, avec le bon type
def _state_subset(state):
    kept = {}
    for key in STATE_LISTS:
        if isinstance(state.get(key), list):
            kept[key] = [item for item in state[key] if isinstance(item, (str, int))]
    # Les valeurs sont relues en nombres ou en listes par le moteur : un type inattendu ne doit jamais entrer dans l'état
    for key in STATE_DICTS:
        value = state.get(key)
        if not isinstance(value, dict):
            continue
        if key == "catalog_baselines":
            kept[key] = {str(name): [i for i in ids if isinstance(i, (str, int)) and not isinstance(i, bool)]
                         for name, ids in value.items() if isinstance(ids, list)}
        else:
            kept[key] = {str(name): number for name, number in value.items()
                         if isinstance(number, (int, float)) and not isinstance(number, bool)}
    if "initialized" in state:
        kept["initialized"] = bool(state["initialized"])
    return kept


# Document complet : réglages (sans DRY_RUN, sans clés API par défaut)
def build_document(settings, include_keys=False):
    config = {key: value for key, value in settings.items() if key != "DRY_RUN"}
    if not include_keys:
        for key in Settings.API_KEYS:
            config.pop(key, None)
    return {"format": FORMAT, "version": VERSION, "created": _now().isoformat(timespec="seconds"),
            "includes_keys": bool(include_keys), "settings": config}
# =================================================


# ======================== FICHIERS DE SAUVEGARDE ========================

# Écrit une sauvegarde (permissions 0600) et supprime les plus anciennes. Renvoie son nom.
def create(settings, include_keys=False, tag=""):
    stamp = _now().strftime("%Y-%m-%d_%H-%M-%S")
    name = f"gentleseed-backup-{stamp}{('-' + tag) if tag else ''}.json"
    document = build_document(settings, include_keys)
    with LOCK:
        folder = backup_dir()
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        private_file.write(target, json.dumps(document, ensure_ascii=False, indent=2))
        old = sorted((p for p in folder.glob("gentleseed-backup-*.json") if NAME_PATTERN.match(p.name)), key=name_order, reverse=True)
        # Deux groupes comptés séparément : sauvegardes normales (KEEP) et copies d'avant restauration (KEEP_SAFETY)
        for group, limit in ((False, KEEP), (True, KEEP_SAFETY)):
            for path in [p for p in old if is_safety_copy(p) == group][limit:]:
                path.unlink(missing_ok=True)
    return name


# Liste des sauvegardes, la plus récente d'abord
def listing():
    folder = backup_dir()
    rows = []
    if folder.is_dir():
        for path in sorted(folder.glob("gentleseed-backup-*.json"), key=name_order, reverse=True):
            if not NAME_PATTERN.match(path.name) or not path.is_file():
                continue
            try:
                head = json.loads(path.read_text(encoding="utf-8"))
                created, keys = head.get("created"), bool(head.get("includes_keys"))
            except (OSError, ValueError):
                created, keys = None, False
            rows.append({"name": path.name, "size": path.stat().st_size, "created": created, "includes_keys": keys})
    return rows


# Chemin d'une sauvegarde (nom strictement contrôlé : aucun chemin fourni par l'utilisateur)
def path_for(name):
    if not isinstance(name, str) or not NAME_PATTERN.match(name):
        raise BackupError("Invalid backup name")
    path = backup_dir() / name
    if not path.is_file():
        raise BackupError("Backup not found")
    return path


def delete(name):
    path_for(name).unlink()
# =================================================


# ======================== RESTAURATION ========================

# Valide un document de sauvegarde (jamais de confiance envers un fichier importé)
def parse(document):
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise BackupError("This file is not a GentleSeed backup")
    settings, state = document.get("settings"), document.get("state", {})
    if not isinstance(settings, dict) or not isinstance(state, dict):
        raise BackupError("Incomplete backup")
    try:
        config = Settings.validate_settings(settings)
    except ValueError as error:
        raise BackupError(f"Invalid settings in the backup: {error}") from error
    return config, _state_subset(state)


# Lit une sauvegarde du dossier (taille limitée)
def load_file(name):
    path = path_for(name)
    if path.stat().st_size > MAX_BYTES:
        raise BackupError("Backup too large")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BackupError("Backup unreadable") from error
# =================================================
