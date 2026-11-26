# ======================== IMPORTS ========================
import hmac
import os
import secrets
import threading
import time
from pathlib import Path

import json

from fastapi import HTTPException

from backend import private_file
from backend import auth as Auth
# =================================================


# ======================== SÉCURITÉ : SESSION, CSRF, ACCÈS LOCAL ========================

SESSION_SECRET_FILE = Path(os.environ.get("SESSION_SECRET_FILE", "/data/.web-secret"))
LOGIN_FAILURES = {}
LOGIN_LOCK = threading.Lock()


# Clé de signature des sessions : créée une seule fois, gardée dans le dossier de données
def session_secret():
    # Création atomique (jamais de fichier à moitié écrit) : la clé n'est pas régénérée à chaque redémarrage
    try:
        return private_file.read_or_create(SESSION_SECRET_FILE, lambda: secrets.token_hex(32))
    except OSError as error:
        # Cas le plus courant : volume monté sans droit d'écriture pour l'utilisateur du conteneur
        raise SystemExit(
            f"GentleSeed cannot write to its data folder ({SESSION_SECRET_FILE.parent}): {error.strerror or error}.\n"
            f"Give the user running GentleSeed (UID {os.getuid()}) write access to this folder, then start it again."
        ) from error


# --------------------- ACCÈS LOCAL, ORIGINE ET CONNEXION ---------------------

# Client « local » selon la règle de Sonarr/Radarr (voir auth.is_local_client)
def local_request(request):
    host = request.client.host if request.client else None
    return Auth.is_local_client(host, request.headers) and Auth.trusted_host(request.headers.get("host"))


# Adresse servant à compter les échecs de connexion. Derrière un proxy installé sur le réseau local
# (peer local + X-Forwarded-For), on prend la dernière adresse ajoutée par ce proxy : un client distant
# ne peut pas la choisir. Sans proxy local, l'en-tête est ignoré, donc impossible à falsifier.
def login_key(request):
    host = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and request.client and Auth.is_local_address(host):
        last = forwarded.split(",")[-1].strip()
        if last:
            return last[:64]
    return host


# Échecs de moins de 15 minutes pour cette adresse ; les adresses sans échec récent sont oubliées
def recent_failures(key):
    now = time.monotonic()
    for other in list(LOGIN_FAILURES):
        kept = [t for t in LOGIN_FAILURES[other] if now - t < 900]
        if kept:
            LOGIN_FAILURES[other] = kept
        else:
            del LOGIN_FAILURES[other]
    # Table bornée : au-delà, les adresses les plus anciennes sont oubliées
    while len(LOGIN_FAILURES) > 2048:
        del LOGIN_FAILURES[next(iter(LOGIN_FAILURES))]
    return LOGIN_FAILURES.get(key, [])


# Plafond par appareil réellement connecté : X-Forwarded-For peut être inventé par un appareil du réseau local,
# qui obtiendrait sinon un compteur neuf à chaque essai
PEER_LIMIT = 100


# Compte une tentative de connexion ou de changement de mot de passe (5 par 15 minutes et par adresse)
# AVANT le calcul lent : des requêtes simultanées ne passent pas toutes sous la limite
def register_attempt(request):
    key = login_key(request)
    peer = "peer " + (request.client.host if request.client else "unknown")
    with LOGIN_LOCK:
        if len(recent_failures(key)) >= 5 or len(recent_failures(peer)) >= PEER_LIMIT:
            raise HTTPException(429, "Too many attempts, try again in 15 minutes")
        for name in (key, peer):
            LOGIN_FAILURES.setdefault(name, []).append(time.monotonic())
    return key, peer


# Tentative réussie : seule celle-ci est oubliée (le compteur des autres utilisateurs de la même adresse reste)
def forgive_attempt(names):
    with LOGIN_LOCK:
        for name in names:
            attempts = LOGIN_FAILURES.get(name)
            if attempts:
                attempts.pop()
                if not attempts:
                    del LOGIN_FAILURES[name]


# Refuse les requêtes venues d'un autre site (en-tête Origin)
def same_origin(request):
    origin = request.headers.get("origin")
    if not origin:
        return True  # Clients API locaux sans navigateur : autres contrôles actifs.
    from urllib.parse import urlsplit
    parsed = urlsplit(origin)
    # Derrière un reverse proxy (ex. proxy de Code Server), Host peut être réécrit :
    # on accepte aussi X-Forwarded-Host. Un site tiers ne peut pas forger ces en-têtes.
    hosts = {request.headers.get("host"), request.headers.get("x-forwarded-host")} - {None, ""}
    return parsed.scheme in ("http", "https") and parsed.netloc in hosts


# Jeton CSRF de la session (créé au besoin)
def csrf_for(request):
    if not request.session.get("csrf"):
        request.session["csrf"] = secrets.token_urlsafe(32)
    return request.session["csrf"]


# Exige une session valide (ou le mode sans authentification depuis le réseau local)
def require_login(request):
    document = Auth.load_auth()
    if document is None:
        raise HTTPException(409, "Initial configuration required")
    if document["mode"] == "none":
        if not local_request(request):
            raise HTTPException(403, "Without authentication, access is limited to PCs on the local network")
        csrf_for(request)
        return
    if request.session.get("admin") is not True or request.session.get("auth_revision") != document.get("revision"):
        raise HTTPException(status_code=401, detail="Sign-in required")


# Pour les actions qui modifient : session, jeton CSRF, JSON et même origine
def require_write(request):
    require_login(request)
    token = request.session.get("csrf", "")
    submitted = request.headers.get("X-CSRF-Token", "")
    if not token or not hmac.compare_digest(token.encode("utf-8"), submitted.encode("utf-8", "surrogatepass")):
        raise HTTPException(status_code=403, detail="Invalid security token")
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(status_code=415, detail="JSON request required")
    if not same_origin(request):
        raise HTTPException(status_code=403, detail="Origin not allowed")


DEFAULT_BODY_LIMIT = 2 * 1024 * 1024


# Lit le corps d'une requête en plafonnant sa taille, même sans Content-Length (envoi en morceaux)
async def read_body(request, limit=DEFAULT_BODY_LIMIT, message="Request too large"):
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        raise HTTPException(400, "Invalid request") from None
    if declared > limit:
        raise HTTPException(413, message)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise HTTPException(413, message)
    return bytes(body)


# Lit un corps JSON : une erreur de format donne toujours un 400, jamais un 500
async def read_json(request, limit=DEFAULT_BODY_LIMIT, message="Request too large"):
    body = await read_body(request, limit, message)
    try:
        return json.loads(body or b"null")
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "Invalid JSON") from None


# Lit le corps JSON d'une requête (un objet est obligatoire)
async def read_integration_payload(request, limit=DEFAULT_BODY_LIMIT, message="Request too large"):
    payload = await read_json(request, limit, message)
    if not isinstance(payload, dict):
        raise HTTPException(400, "Invalid request")
    return payload
# =================================================
