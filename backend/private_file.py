# ======================== FICHIERS PRIVÉS ========================
import os
import secrets
from pathlib import Path


# Écrit un fichier lisible par le seul propriétaire : droits 0600 dès la création, puis remplacement atomique
def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


# Lit un secret ; le crée une seule fois s'il manque ou s'il est vide (jamais lu à moitié écrit)
def read_or_create(path, make):
    path = Path(path)
    try:
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(make())
        try:
            os.link(temp, path)  # échoue si un autre processus l'a créé entre-temps
        except FileExistsError:
            pass
    finally:
        temp.unlink(missing_ok=True)
    value = path.read_text(encoding="utf-8").strip()
    if value:
        return value
    write(path, make())  # fichier vide laissé par un ancien plantage : on le remplace
    return path.read_text(encoding="utf-8").strip()
# =================================================
