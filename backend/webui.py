# ======================== IMPORTS ========================
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from backend import settings as Settings
from backend.engine import journal as journal
from backend.engine import store as store
from backend.engine.monitor import SCAN_EVENT, STOP_EVENT, track_deliveries_worker, worker
from backend.engine.search import configure_engine
from backend.instance_lock import InstanceLock
from backend.version import VERSION
from backend.routes import access, integration, maintenance, media, security, service_control, status, system
from backend.routes.access import STATIC_DIR
# =================================================


# ======================== DÉMARRAGE ET ARRÊT ========================
RUNNING_THREADS = []  # threads du moteur de la session en cours, attendus avant un nouveau démarrage

# Démarre les tâches de fond (surveillance, suivi, mises à jour, intégration) et les arrête proprement
@asynccontextmanager
async def lifespan(app):
    # --------------------- VERROU MULTI-INSTANCE ---------------------
    # Le même dossier /data ne peut pas piloter deux fois Radarr/Sonarr.
    with InstanceLock(store.STATE_FILE.parent / '.gentleseed.lock'):
        configure_engine(Settings.load_settings())
        # Un redémarrage dans le même processus attend la fin des anciens threads : jamais deux moteurs en parallèle
        for old in RUNNING_THREADS:
            old.join(timeout=300)
        RUNNING_THREADS.clear()
        STOP_EVENT.clear()
        SCAN_EVENT.clear()
        thread = threading.Thread(target=worker, name="srs-worker", daemon=True)
        thread.start()
        delivery_thread = threading.Thread(target=track_deliveries_worker, name="gs-deliveries", daemon=True)
        delivery_thread.start()
        RUNNING_THREADS.extend([thread, delivery_thread])
        threading.Thread(target=maintenance.update_worker, name="gs-updates", daemon=True).start()
        threading.Thread(target=integration.integration_restore_on_start, name="gs-integration", daemon=True).start()
        try:
            yield
        finally:
            STOP_EVENT.set()
            SCAN_EVENT.set()
            deadline = time.monotonic() + 25  # tout l'arrêt tient sous les 30 s laissées par Docker
            integration.integration_remove_on_stop()  # d'abord : Docker peut couper avant la fin des recherches
            for running in (thread, delivery_thread):
                running.join(timeout=max(0, deadline - time.monotonic()))
            journal.log(f"GentleSeed v{VERSION}: web interface and engine stopped")
            journal.log("─" * 20 + " Shutdown " + "─" * 20)
# =================================================


# ======================== APPLICATION ========================

app = FastAPI(title="GentleSeed", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=security.session_secret(), max_age=43200,
                   same_site="strict", https_only=os.environ.get("WEB_HTTPS_ONLY", "false").lower() == "true")


# Fichiers du site toujours revalidés (ETag) : jamais un ancien app.js avec une nouvelle page
class RevalidatedStatic(StaticFiles):

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", RevalidatedStatic(directory=STATIC_DIR), name="static")

# Navigateur : page d'erreur lisible ; API : JSON inchangé
app.add_exception_handler(StarletteHTTPException, access.browser_friendly_errors)

# Routes, rangées par thème (l'ordre est celui d'origine)
for module in (access, service_control, status, media, integration, maintenance, system):
    app.include_router(module.router)
# =================================================
