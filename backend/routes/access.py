# ======================== IMPORTS ========================
import secrets
import threading
from pathlib import Path

from starlette.concurrency import run_in_threadpool
from fastapi import APIRouter, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import auth as Auth
from backend import settings as Settings
from backend.engine import journal as journal
from backend.version import VERSION
from backend.routes import security
# =================================================


# ======================== PAGES, CONNEXION ET SÉCURITÉ ========================

router = APIRouter()


# --------------------- DOSSIER DES PAGES ---------------------

STATIC_DIR = Path(__file__).resolve().parents[2] / "web"


# --------------------- THÈME PUBLIC SANS INFORMATION SENSIBLE ---------------------

# Nécessaire pour colorer la page de connexion AVANT authentification.
@router.get("/api/theme")
def public_theme():
    theme = Settings.load_settings().get("UI_THEME", "auto")
    allowed = {"sombre", "clair", "auto", "maillot-rose", "maillot-noir", "maillot-paris", "maillot-worlds", "maillot-violet"}
    return {"theme": theme if theme in allowed else "auto"}


# Page HTML avec le numéro de version (marqueur {{VERSION}}) : jamais écrit en dur dans les pages
def page_response(name):
    html = (STATIC_DIR / name).read_text(encoding="utf-8").replace("{{VERSION}}", VERSION)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


NOTICE_ICONS = {
    "sad": '<circle cx="12" cy="12" r="9.5"/><path d="M8 16c1-1.4 2.4-2 4-2s3 .6 4 2"/><path d="M9 9.5h.01M15 9.5h.01"/>',
    "info": '<circle cx="12" cy="12" r="9.5"/><path d="M12 11v6"/><path d="M12 7.5h.01"/>',
    "alert": '<path d="m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3Z"/><path d="M12 9v4M12 17h.01"/>',
}


# Page d'information lisible (au lieu d'un JSON brut) pour qui ouvre une adresse dans son navigateur
def notice_page(icon, title, message, hint="", status=200, base="./"):
    from html import escape
    html = (STATIC_DIR / "notice.html").read_text(encoding="utf-8")
    for key, value in (("{{ICON}}", NOTICE_ICONS.get(icon, NOTICE_ICONS["info"])), ("{{TITLE}}", escape(title)),
                       ("{{MESSAGE}}", escape(message)), ("{{HINT}}", escape(hint)), ("{{BASE}}", base), ("{{VERSION}}", VERSION)):
        html = html.replace(key, value)
    return HTMLResponse(html, status_code=status, headers={"Cache-Control": "no-store"})


NOTICE_BY_STATUS = {
    401: ("sad", "Login required", "Sign in to continue."),
    403: ("sad", "Access denied", "Open GentleSeed from the server's network (private address, no domain or proxy), "
                                 "or choose Form mode in Settings → Security for remote access."),
    404: ("info", "Page not found", "This address does not exist in GentleSeed."),
    405: ("info", "Page not found", "This address does not exist in GentleSeed."),
    409: ("info", "Action required", "GentleSeed is not configured yet. Do the first setup from the server's network."),
}


# Navigateur : page lisible ; API et appels du site : JSON inchangé
async def browser_friendly_errors(request: Request, error: StarletteHTTPException):
    path = request.url.path
    wants_page = (request.method in ("GET", "HEAD") and "text/html" in request.headers.get("accept", "")
                  and not path.startswith(("/api/", "/static/")))
    if not wants_page:
        return await http_exception_handler(request, error)
    icon, title, hint = NOTICE_BY_STATUS.get(error.status_code, ("alert", "An error occurred", "Try again in a moment."))
    message = error.detail if isinstance(error.detail, str) and error.detail and error.status_code != 404 else title
    if error.status_code == 404:
        message = "This address does not exist in GentleSeed."
        hint = ""
    base = "../" * max(path.rstrip("/").count("/") - 1, 0) or "./"
    return notice_page(icon, title, message, hint, status=error.status_code, base=base)


# Page de première configuration (réservée au réseau local, sans proxy)
@router.get("/setup")
def setup_page(request: Request):
    if Auth.load_auth() is not None:
        return RedirectResponse("./", status_code=303)
    if not security.local_request(request):
        return notice_page(
            "sad", "Setup not possible from here",
            "The first GentleSeed setup is restricted to the server's local network.",
            "Open GentleSeed from the server's network, using its private address (for example http://192.168.1.10:1853), without going through a domain or a proxy.",
            status=403)
    return page_response("setup.html")


# Verrou de la première configuration : deux demandes simultanées ne créent pas deux comptes
SETUP_LOCK = threading.Lock()


# Valide puis enregistre la première configuration (bloquant : lancé dans un thread, sous verrou)
def apply_setup(payload):
    with SETUP_LOCK:
        if Auth.load_auth() is not None:
            raise HTTPException(409, "Initial setup already completed")
        try:
            # Le thème et la langue choisis au premier lancement sont conservés avant /login.
            # On valide d'abord toutes les entrées : aucune sauvegarde sur erreur.
            if not isinstance(payload, dict):
                raise ValueError("Invalid initial configuration")
            document = Auth.validate(payload, allow_none=True)
            selected_theme = payload.get("theme", "auto")
            if not isinstance(selected_theme, str):
                raise ValueError("Invalid theme")
            selected_language = payload.get("language", "auto")
            if not isinstance(selected_language, str):
                raise ValueError("Invalid language")
            config = Settings.validate_settings({"UI_THEME": selected_theme, "UI_LANGUAGE": selected_language})
            # Le compte d'abord : s'il ne peut pas être écrit, rien n'a changé
            Auth.save_auth(document)
            try:
                Settings.save_settings(config)
            except OSError:
                Auth.AUTH_FILE.unlink(missing_ok=True)  # sinon un nouvel essai répondrait « déjà configuré »
                raise
        except (ValueError, OSError) as error:
            raise HTTPException(400, str(error)) from error
        return document


# Première configuration : crée le compte ou choisit « Aucun » (réseau local seulement)
@router.post("/api/setup")
async def setup(request: Request):
    if Auth.load_auth() is not None:
        raise HTTPException(409, "Initial setup already completed")
    if not security.local_request(request) or not security.same_origin(request):
        raise HTTPException(403, "Setup is only available from the local network")
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "JSON required")
    payload = await security.read_json(request)
    document = await run_in_threadpool(apply_setup, payload)
    request.session.clear()
    request.session.update({"csrf": secrets.token_urlsafe(32)})
    if document["mode"] == "form":
        request.session.update({"admin": True, "username": document["username"],
                                "auth_revision": document["revision"]})
    journal.log(f"Initial setup completed: {document['mode']}")
    return {"ok": True}


# Page de connexion (redirige si la configuration manque ou si on est déjà connecté)
@router.get("/login")
def login_page(request: Request):
    document = Auth.load_auth()
    if document is None:
        return RedirectResponse("setup", status_code=303)
    if document["mode"] == "none" or (request.session.get("admin") and request.session.get("auth_revision") == document.get("revision")):
        return RedirectResponse("./", status_code=303)
    return page_response("login.html")


# Connecte avec l'identifiant et le mot de passe ; 5 échecs bloquent l'adresse 15 minutes
@router.post("/api/login")
async def login(request: Request):
    document = Auth.load_auth()
    if document is None:
        raise HTTPException(409, "Finish the initial setup first")
    if document["mode"] == "none":
        raise HTTPException(409, "No sign-in required")
    if not security.same_origin(request):
        raise HTTPException(403, "Origin not allowed")
    payload = await security.read_json(request)
    supplied = payload.get("password", "") if isinstance(payload, dict) else ""
    username = payload.get("username", "") if isinstance(payload, dict) else ""
    client_ip = security.register_attempt(request)
    # Le calcul du mot de passe (scrypt) est lent : hors de la boucle d'événements et hors du verrou
    valid = await run_in_threadpool(Auth.verify, username, supplied, document)
    if not valid:
        raise HTTPException(401, "Incorrect credentials")
    security.forgive_attempt(client_ip)
    request.session.clear()
    request.session.update({"admin": True, "username": document["username"],
                            "auth_revision": document.get("revision"), "csrf": secrets.token_urlsafe(32)})
    return {"ok": True}


# Ferme la session
@router.post("/api/logout")
def logout(request: Request):
    security.require_write(request)
    request.session.clear()
    return {"ok": True}


# Page principale (redirige vers la configuration ou la connexion si nécessaire)
@router.get("/")
def index(request: Request):
    document = Auth.load_auth()
    if document is None:
        return RedirectResponse("setup", status_code=303)
    if document["mode"] != "none" and (request.session.get("admin") is not True or request.session.get("auth_revision") != document.get("revision")):
        return RedirectResponse("login", status_code=303)
    security.require_login(request)
    return page_response("index.html")


# Mode d'accès actuel (aucun ou formulaire) et nom d'utilisateur
@router.get("/api/security")
def get_security(request: Request):
    security.require_login(request)
    return Auth.public_auth(security.local_request(request))


# Change le mode d'accès ou le compte (mot de passe actuel exigé)
@router.post("/api/security")
async def change_security(request: Request):
    security.require_write(request)
    payload = await security.read_json(request)
    # Même limite d'essais que la connexion : le mot de passe actuel ne peut pas être deviné sans fin
    attempt = security.register_attempt(request)
    allow_none = bool(security.local_request(request))

    def work():
        with Auth.LOCK:  # lecture, vérification et écriture d'un seul tenant
            document = Auth.validate(payload, Auth.load_auth(), allow_none=allow_none)
            Auth.save_auth(document)
            return document
    try:
        document = await run_in_threadpool(work)  # le calcul du mot de passe (scrypt) est lent
    except (ValueError, OSError) as error:
        if str(error) != "Current password is incorrect":
            security.forgive_attempt(attempt)  # simple erreur de saisie : ne doit pas bloquer la connexion
        raise HTTPException(400, str(error)) from error
    security.forgive_attempt(attempt)
    request.session.clear()
    request.session["csrf"] = secrets.token_urlsafe(32)
    if document["mode"] == "form":
        request.session.update({"admin": True, "username": document["username"],
                                "auth_revision": document["revision"]})
    journal.log(f"Authentication method changed: {document['mode']}")
    return {"ok": True, "security": Auth.public_auth(security.local_request(request)), "csrf": request.session["csrf"]}
# =================================================
