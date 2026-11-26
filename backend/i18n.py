# ======================== IMPORTS ========================
import json
import re
from pathlib import Path
# =================================================


# ======================== CONFIGURATION ========================
LOCALES = Path(__file__).resolve().parents[1] / "web" / "locales"
SUPPORTED = ("fr", "de", "es", "it", "pt-PT", "pt-BR", "nl", "pl", "ru", "ja", "ko", "zh-CN", "uk")

# Dictionnaires chargés une fois : langue -> (textes exacts, modèles)
_CACHE = {}
_PLACEHOLDER = re.compile(r"\{(\d*)\}")
# =================================================


# ======================== TRADUCTION ========================
# Même logique que web/i18n.js : les journaux sont écrits en anglais, la traduction
# se fait à l'affichage et au téléchargement, avec les mêmes fichiers web/locales/*.json

# Charge une langue (None si inconnue ou anglais, la langue par défaut)
def _load(language):
    if language not in SUPPORTED:
        return None
    if language not in _CACHE:
        exact = {}
        try:
            exact.update(json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        patterns = []
        for key in sorted((k for k in exact if "{}" in k), key=len, reverse=True):
            source = "(.+?)".join(re.escape(part) for part in key.split("{}"))
            # None : traduction identique à la clé (ligne technique), valeurs à ne pas toucher
            patterns.append((re.compile(f"^{source}$", re.S), None if exact[key] == key else exact[key]))
        _CACHE[language] = (exact, patterns)
    return _CACHE[language]


# Remplit les {} d'une traduction dans l'ordre ; {1} {2}… changent l'ordre selon la langue
def _fill(target, args):
    position = iter(range(len(args)))

    def put(match):
        index = int(match.group(1)) - 1 if match.group(1) else next(position, len(args))
        return args[index] if 0 <= index < len(args) else match.group(0)
    return _PLACEHOLDER.sub(put, target)


# Motif suivi de son nombre (« Insufficient seeders (0 < 1) (2) ») : chaque motif se traduit séparément
_COUNTED = re.compile(r"^(.*\S) \((\d{1,3})\)$", re.S)


# Traduit un texte (l'anglais reste inchangé si aucune traduction n'existe).
# Les valeurs variables d'un modèle sont traduites à leur tour (deux niveaux au plus)
def translate(text, language, depth=0):
    loaded = _load(language)
    if loaded is None:
        return text
    exact, patterns = loaded
    if text in exact:
        return exact[text]
    if depth > 2:
        return text
    items = [_COUNTED.match(item) for item in text.split("; ")]
    if all(items):
        return "; ".join(f"{translate(item.group(1), language, depth + 1)} ({item.group(2)})" for item in items)
    for pattern, target in patterns:
        match = pattern.match(text)
        if match and target is None:
            return text  # sinon « /movie » deviendrait « /film »
        if match:
            return _fill(target, [translate(part, language, depth + 1) for part in match.groups()])
    return text


# Traduit un contenu de fichier journal : « [heure] [NIVEAU] message » ou une ligne JSON {"message": …}
_LOG_LINE = re.compile(r"^(\[[^\]]*\] \[[A-Z]+\] )(.*)$", re.S)


def translate_log_line(line, language):
    if _load(language) is None:
        return line
    ending = "\n" if line.endswith("\n") else ""
    body = line[:-1] if ending else line
    if body.startswith("{"):
        try:
            event = json.loads(body)
            if isinstance(event.get("message"), str):
                event["message"] = translate(event["message"], language)
                return json.dumps(event, ensure_ascii=False) + ending
        except ValueError:
            return line
    match = _LOG_LINE.match(body)
    if match:
        return match.group(1) + translate(match.group(2), language) + ending
    return line


# Couleur d'une ligne de journal (mêmes règles que web/js/logcolors.js), sur le texte d'origine (anglais).
# Les anciens mots français restent reconnus pour les journaux écrits avant le passage à l'anglais.
_SUCCESS_WORDS = ("request accepted", "release confirmed by", "import confirmed by", "pack handed to", "season handed to",
                  "link operational", "release is in the queue", "gentleseed webhook installed",
                  "demande acceptée", "confirmée par l'historique", "confirmée par l’historique", "importation confirmée",
                  "pack transmis", "saison transmise", "liaison opérationnelle", "release présente dans la file",
                  "webhook gentleseed installé")
_LEVEL = re.compile(r"^\[[^\]]*\]\s*\[(ERROR|WARN|INFO|DEBUG)\]")


def classify_log_line(line):
    text = line.rstrip("\r\n")
    if text.startswith("{"):
        try:
            event = json.loads(text)
            text = f"[{event.get('time', '')}] [{event.get('level', 'INFO')}] {event.get('message', '')}"
        except ValueError:
            pass
    level = _LEVEL.match(text)
    if level and level.group(1) == "ERROR":
        return "log-error"
    if level and level.group(1) == "WARN":
        return "log-warn"
    if "──" in text and ("Startup" in text or "Shutdown" in text or "Démarrage" in text or "Arrêt" in text):
        return "log-lifecycle"
    if re.search(r"web interface and engine (started|stopped)|interface Web et moteur (démarrés|arrêtés)", text):
        return "log-lifecycle"
    lower = text.lower()
    if any(word in lower for word in _SUCCESS_WORDS):
        return "log-ok"
    return ""
# =================================================
