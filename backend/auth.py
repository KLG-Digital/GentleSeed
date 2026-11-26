# ======================== IMPORTS ========================
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import threading

from backend import private_file
from pathlib import Path
from urllib.parse import urlsplit
# =================================================


# ======================== CONFIGURATION ========================
AUTH_FILE = Path(os.environ.get("AUTH_FILE", "/data/auth.json"))
LOCK = threading.RLock()

# Réseaux "locaux" au sens de Sonarr/Radarr (hors CGNAT 100.64/10)
_LOCAL_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
    "::1/128", "fe80::/10", "fc00::/7"))
# =================================================


# ======================== RÉSEAU LOCAL ========================

# Dit si une adresse IP est une adresse locale
def is_local_address(host):
    try:
        address = ipaddress.ip_address(str(host).split("%")[0])
    except ValueError:
        return False
    if getattr(address, "ipv4_mapped", None):
        address = address.ipv4_mapped
    return any(address.version == network.version and address in network for network in _LOCAL_NETWORKS)


# En-têtes ajoutés par les reverse proxys : leur présence prouve que la requête a transité par un proxy
PROXY_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip", "x-forwarded-host", "x-forwarded-proto",
                 "x-forwarded-server", "cf-connecting-ip", "true-client-ip")


# Comme Sonarr, en plus strict : local seulement si l'IP est locale ET sans aucun en-tête de proxy
# (derrière un proxy, l'IP vue est celle du proxy : le vrai client peut être sur Internet)
def is_local_client(client_host, headers):
    if any(headers.get(name) is not None for name in PROXY_HEADERS):
        return False
    return bool(client_host) and is_local_address(client_host)


# Noms réservés aux réseaux privés (aucun site public ne peut les faire pointer ici)
LOCAL_SUFFIXES = (".local", ".lan", ".home", ".home.arpa", ".internal", ".localdomain", ".localhost")


# Protection contre le « DNS rebinding » : un nom de domaine public pointant sur GentleSeed est refusé.
# Acceptés : adresse IP, nom sans point (localhost, truenas), nom privé, ou nom déclaré dans WEB_ALLOWED_HOSTS
def trusted_host(header):
    value = str(header or "").strip().lower()
    if not value:
        return True  # aucun navigateur n'omet l'en-tête Host
    try:
        name = (urlsplit("//" + value).hostname or "").rstrip(".")
    except ValueError:
        return False
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    allowed = {item.strip().lower() for item in os.environ.get("WEB_ALLOWED_HOSTS", "").split(",") if item.strip()}
    return bool(name) and ("." not in name or name.endswith(LOCAL_SUFFIXES) or name in allowed)
# =================================================


# ======================== MOT DE PASSE ========================

# Calcule l'empreinte d'un mot de passe (scrypt + sel aléatoire)
def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return {"salt": salt.hex(), "digest": digest.hex()}


# Vérifie un identifiant et un mot de passe
def verify(username, password, document=None):
    document = document if document is not None else load_auth()
    if not document or document.get("mode") == "none":
        return False
    if not isinstance(username, str) or not isinstance(password, str):
        return False
    if not hmac.compare_digest(username.encode("utf-8"), str(document.get("username", "")).encode("utf-8")):
        return False
    try:
        actual = bytes.fromhex(document["digest"])
        salt = bytes.fromhex(document["salt"])
        candidate = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
        return hmac.compare_digest(candidate, actual)
    except (ValueError, KeyError, TypeError):
        return False
# =================================================


# ======================== FICHIER D'AUTHENTIFICATION ========================

# Lit la configuration d'accès (None tant que la première configuration n'est pas faite)
def load_auth():
    with LOCK:
        if AUTH_FILE.exists():
            document = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
            if document.get("mode") not in ("none", "form"):
                raise ValueError("Invalid authentication configuration")
            return document
        return None


# Enregistre la configuration d'accès (fichier réservé à son propriétaire, droits 0600)
def save_auth(document):
    with LOCK:
        private_file.write(AUTH_FILE, json.dumps(document, indent=2))


# Résumé public pour l'interface (jamais le mot de passe ni son empreinte)
def public_auth(allow_none=False):
    document = load_auth()
    return {"configured": document is not None,
            "mode": document.get("mode", "form") if document else None,
            "username": document.get("username", "") if document else "",
            "no_auth_allowed": bool(allow_none)}
# =================================================


# ======================== VALIDATION ========================

# Contrôle une demande de changement d'accès et renvoie le nouveau document à enregistrer
def validate(payload, existing=None, allow_none=False):
    if not isinstance(payload, dict):
        raise ValueError("Invalid configuration")
    mode = payload.get("mode")
    if mode not in ("none", "form"):
        raise ValueError("Choose None or Form")
    if mode == "none" and not allow_none:
        raise ValueError("Authentication-free mode is only accepted from the local network, without a proxy (like Radarr/Sonarr)")
    # Un compte existant : le mot de passe actuel est obligatoire pour changer quoi que ce soit
    if existing and existing.get("mode") == "form":
        if not verify(existing.get("username", ""), payload.get("current_password", ""), existing):
            raise ValueError("Current password is incorrect")
    if mode == "none":
        return {"mode": "none", "revision": secrets.token_hex(12)}
    username = payload.get("username", "")
    password = payload.get("password", "")
    if not isinstance(username, str) or not 3 <= len(username.strip()) <= 48:
        raise ValueError("Username: 3 to 48 characters")
    # Mot de passe libre, même un seul caractère : l'interface peut avertir, jamais refuser
    if not isinstance(password, str):
        raise ValueError("Invalid password")
    # Changement de nom seul : on garde le mot de passe actuel
    if password == "" and existing and existing.get("mode") == "form":
        return {"mode": "form", "username": username.strip(),
                "salt": existing["salt"], "digest": existing["digest"],
                "revision": secrets.token_hex(12)}
    if not password:
        raise ValueError("Enter a password (one character is enough)")
    if password != payload.get("confirm_password"):
        raise ValueError("The passwords do not match")
    return {"mode": "form", "username": username.strip(),
            **password_hash(password), "revision": secrets.token_hex(12)}
# =================================================
