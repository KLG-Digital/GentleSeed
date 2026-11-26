# ======================== IMPORTS ========================
import requests
# =================================================


# ======================== ERREURS DE RECHERCHE ========================

# Statut HTTP d'une erreur venue de Radarr/Sonarr. Pas 502 : beaucoup de proxys (Cloudflare, nginx) remplacent
# les réponses 502 par leur propre page et masquent le message
UPSTREAM_ERROR = 424


# Texte d'une erreur pour le journal : court et sans adresse quand elle vient de la connexion à Radarr/Sonarr
def error_text(error, service):
    if isinstance(error, requests.RequestException):
        return describe_connection_error(error, service)
    return str(error)


# Message court et sans adresse pour une erreur de connexion à Radarr/Sonarr (clé refusée, adresse, délai)
def describe_connection_error(error, service):
    name = 'Sonarr' if service == 'sonarr' else 'Radarr'
    if isinstance(error, requests.exceptions.Timeout):
        return f"{name} did not respond in time"
    if isinstance(error, requests.exceptions.HTTPError):
        code = getattr(getattr(error, 'response', None), 'status_code', None)
        if code in (401, 403):
            return f"{name} rejected the API key"
        return f"{name} replied HTTP {code or 'unknown'}: check its address and URL Base"
    return f"Cannot reach {name}: check its address and the network"

# Phrases entières par type de média : un mot inséré seul donnerait une grammaire fausse une fois traduit
SEARCH_TIMEOUT_MESSAGES = {
    "movie": "Movie search interrupted: {name} did not respond within the expected time.",
    "episode": "Episode search interrupted: {name} did not respond within the expected time.",
    "season": "Season search interrupted: {name} did not respond within the expected time.",
}
SEARCH_UNAVAILABLE_MESSAGES = {
    "movie": "Movie search unavailable in {name}: {error}",
    "episode": "Episode search unavailable in {name}: {error}",
    "season": "Season search unavailable in {name}: {error}",
}


# Traduit une erreur de recherche Radarr/Sonarr en (code HTTP, message lisible)
def describe_search_error(error, service='sonarr', scope='episode'):
    name = 'Sonarr' if service == 'sonarr' else 'Radarr'
    context = 'season' if scope == 'season' else ('episode' if service == 'sonarr' else 'movie')
    if isinstance(error, requests.exceptions.Timeout):
        return 504, (SEARCH_TIMEOUT_MESSAGES[context].format(name=name) + " No result could be confirmed. "
                     "Try again later or increase the API timeout in Settings → General.")
    if isinstance(error, requests.exceptions.ConnectionError):
        return UPSTREAM_ERROR, (f"Cannot connect to {name} during the search. Check its address, "
                     "its status and the network connection.")
    if isinstance(error, requests.exceptions.HTTPError):
        code = getattr(getattr(error, 'response', None), 'status_code', None)
        return UPSTREAM_ERROR, f"{name} refused the search (HTTP {code or 'unknown'}). Check its logs."
    return UPSTREAM_ERROR, SEARCH_UNAVAILABLE_MESSAGES[context].format(name=name, error=error)
# =================================================
