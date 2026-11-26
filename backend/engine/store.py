# ======================== IMPORTS ========================
import json
import os
import time
from pathlib import Path
# =================================================


# ======================== CONFIGURATION ========================
STATE_FILE = Path(os.environ.get("STATE_FILE", "/data/state.json"))
HANDOFF_RETRY_SECONDS = 900  # anti-doublon propre à chaque média, sans quota horaire global
# =================================================


# ======================== ÉTAT (state.json) ========================

# Lit l'état (état vide au premier lancement)
def load_state():
    if not STATE_FILE.exists():
        return {"initialized": False, "known": [], "tracked": [], "last_attempt": {}}
    with STATE_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


# Écrit l'état dans un fichier temporaire puis le remplace (jamais de fichier à moitié écrit)
def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(temp, STATE_FILE)
# =================================================


# ======================== ANTI-DOUBLON D'ENVOI ========================

# Réserve l'envoi d'un média : refuse un second envoi trop proche (timeout, double clic).
# Aucun quota global : des médias différents peuvent être traités à la suite.
# La réservation est enregistrée AVANT l'envoi, pour ne pas le répéter après un redémarrage.
def reserve_handoff(state, media_key):
    if not isinstance(media_key, str) or ":" not in media_key:
        raise ValueError("Invalid media identifier")
    now = time.time()
    attempts = state.setdefault("handoff_attempts", {})
    last = float(attempts.get(media_key, 0))
    if now - last < HANDOFF_RETRY_SECONDS:
        remaining = max(1, int(HANDOFF_RETRY_SECONDS - (now - last)))
        raise RuntimeError(f"Hand-off already attempted for {media_key}: try again in {remaining}s")
    # Oublie les réservations de plus de 7 jours
    state["handoff_attempts"] = {
        key: float(value) for key, value in attempts.items()
        if now - float(value) < 7 * 86400
    }
    state["handoff_attempts"][media_key] = now
    save_state(state)
# =================================================
