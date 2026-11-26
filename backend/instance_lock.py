# ======================== IMPORTS ========================
import fcntl
import os
from pathlib import Path
# =================================================


# ======================== VERROU D'INSTANCE ========================

# Verrou exclusif sur un fichier : libéré automatiquement si le processus disparaît
class InstanceLock:

    def __init__(self, filename):
        self.path = Path(filename)
        self.handle = None

    # --------------------- PRISE DU VERROU ---------------------

    # Prend le verrou ou lève une erreur si une autre instance le détient déjà
    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open('a+b')
        try:
            # Le fichier ne doit jamais être vide
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise RuntimeError('GentleSeed is already running with this data folder') from exc
        self.handle = handle
        return self

    # --------------------- LIBÉRATION DU VERROU ---------------------

    # Rend le verrou (sans effet s'il n'est pas pris)
    def release(self):
        if self.handle is None:
            return
        handle = self.handle
        self.handle = None
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    # --------------------- UTILISATION AVEC « with » ---------------------

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.release()
# =================================================
