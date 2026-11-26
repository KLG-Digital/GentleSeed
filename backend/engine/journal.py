# ======================== IMPORTS ========================
import json
import os
import re
import threading
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
# =================================================


# ======================== CONFIGURATION ========================
EVENT_LOG_FILE = Path(os.environ.get("EVENT_LOG_FILE", "/data/events.jsonl"))
LOG_LOCK = threading.Lock()
DAILY_LOG_RETENTION_DAYS = 30
DAILY_LOG_MAX_BYTES = 5_000_000
LOG_LEVEL = "INFO"  # remplacé par le réglage de l'interface
# =================================================


# ======================== JOURNALISATION ========================

# Enregistre un événement : console (Docker), journal de l'interface et fichier du jour
def log(*parts, flush=True, level=None, **kwargs):
    message = " ".join(str(part) for part in parts)
    # Nom d'exception (« ConnectionError ») ou « unavailable » ; un titre comme « Human Error » reste normal
    severity = level or ("ERROR" if re.search(r"\b[A-Za-z]+Error\b|\bunavailable\b", message) else "INFO")
    thresholds = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}
    if thresholds.get(severity, 1) < thresholds.get(LOG_LEVEL, 1):
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{now}] [{severity}] {message}", flush=flush, **kwargs)

    try:
        with LOG_LOCK:
            # Journal de l'interface : rotation à 2 Mo
            EVENT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            if EVENT_LOG_FILE.exists() and EVENT_LOG_FILE.stat().st_size > 2_000_000:
                rotated = EVENT_LOG_FILE.with_suffix(".previous.jsonl")
                os.replace(EVENT_LOG_FILE, rotated)
            with EVENT_LOG_FILE.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"time": now, "level": severity,
                                         "message": message}, ensure_ascii=False) + "\n")

            # Fichier texte du jour (les noms sont contrôlés à la consultation Web)
            daily_folder = EVENT_LOG_FILE.parent / "logs"
            daily_folder.mkdir(parents=True, exist_ok=True)
            today = datetime.now(timezone.utc).date()
            base_name = f"gentleseed-{today.isoformat()}"
            candidate = daily_folder / f"{base_name}.log"
            rotation = 1
            while candidate.is_file() and candidate.stat().st_size >= DAILY_LOG_MAX_BYTES:
                candidate = daily_folder / f"{base_name}.{rotation}.log"
                rotation += 1
            with candidate.open("a", encoding="utf-8") as daily:
                daily.write(f"[{now}] [{severity}] {message}\n")

            # Supprime les fichiers trop anciens (uniquement ceux de GentleSeed)
            cutoff = today - timedelta(days=DAILY_LOG_RETENTION_DAYS)
            for old in daily_folder.glob("gentleseed-*.log"):
                match = re.fullmatch(r"gentleseed-(\d{4}-\d{2}-\d{2})(?:\.\d+)?\.log", old.name)
                if match:
                    try:
                        if date.fromisoformat(match.group(1)) < cutoff:
                            old.unlink(missing_ok=True)
                    except ValueError:
                        continue
    except OSError:
        # Dossier de données absent ou non inscriptible : la console suffit
        pass
# =================================================
