# ======================== IMPORTS ========================
import math
import re
from collections import Counter

from backend.engine import journal as journal
# =================================================


# ======================== CONFIGURATION ========================
# Garde les torrents rares : avec 1 seeder, une release reste admissible.
MIN_SEEDERS = 1  # remplacé par le réglage de l'interface

# Si True, les releases dont le seeding n'est pas renseigné restent admissibles,
# mais elles seront classées après celles dont le nombre de seeders est connu.
ALLOW_UNKNOWN_SEEDERS = False  # remplacé par le réglage de l'interface

# Indexeurs à ignorer, par service (noms en minuscules) : remplacés par les réglages de l'interface
IGNORED_INDEXERS = {"radarr": frozenset(), "sonarr": frozenset()}

# Préférence douce : aucun codec n'est éliminé du seul fait de sa compression
PREFERRED_CODEC = "auto"
CODEC_PRIORITY = "equilibree"
# Préférence pour la même équipe de release d'une saison à l'autre : « off », « faible », « equilibree » ou « forte »
TEAM_PREFERENCE = "off"
# Bonus ajouté au logarithme des seeders : la release de l'équipe passe devant jusqu'à environ 1,4× / 3× / 10× moins de seeders
TEAM_BONUS = {"faible": 0.35, "equilibree": 1.1, "forte": 2.3}
# =================================================


# ======================== SEEDERS ========================

# Nombre de seeders, ou None s'il est inconnu
def number_of_seeders(release):
    value = release.get("seeders")
    try:
        return int(value) if value is not None and int(value) >= 0 else None
    except (TypeError, ValueError):
        return None


# Un compteur inconnu est classé après 0, sans confondre les deux
def seeder_score(release):
    count = number_of_seeders(release)
    return count if count is not None else -1
# =================================================


# ======================== FILTRAGE ET DIAGNOSTIC ========================

# Vrai si l'indexeur de cette release est dans la liste « à ignorer » de son service
def indexer_ignored(release):
    name = str(release.get("indexer") or "").strip().lower()
    return bool(name) and name in IGNORED_INDEXERS.get(release.get("gentleseedService"), ())


# Liste les raisons de refus : celles de Radarr/Sonarr et celles de GentleSeed (jamais contournées)
def rejection_details(release):
    reasons = []
    provided = release.get("rejections")
    if not isinstance(provided, list):
        reasons.append("Rejection decision missing or unreadable in the *arr response")
    else:
        reasons.extend(str(r).strip()[:180] for r in provided if str(r).strip())
    if release.get("rejected") is True and not reasons:
        reasons.append("Release rejected by Radarr/Sonarr without details")
    if release.get("approved") is False and not reasons:
        reasons.append("Release not approved by Radarr/Sonarr")
    if release.get("temporarilyRejected") is True:
        reasons.append("Temporary rejection by Radarr/Sonarr")
    if release.get("downloadAllowed") is False:
        reasons.append("Download forbidden by Radarr/Sonarr")
    if str(release.get("protocol", "")).lower() not in ("torrent", "1"):
        reasons.append("Protocol is not torrent or not provided by the API")
    if not release.get("guid") or not release.get("indexerId"):
        reasons.append("Missing release/indexer identifier")
    if indexer_ignored(release):
        reasons.append("Indexer ignored in GentleSeed")
    seeders = number_of_seeders(release)
    if seeders is None and not ALLOW_UNKNOWN_SEEDERS:
        reasons.append("Unknown seeders ('Allow unknown seeders' option disabled)")
    if seeders is not None and seeders < MIN_SEEDERS:
        reasons.append(f"Insufficient seeders ({seeders} < {MIN_SEEDERS})")
    # Ordre stable, sans raison en double
    return list(dict.fromkeys(reasons))


# Releases sans aucun refus (on respecte toujours Radarr/Sonarr et les garde-fous)
def eligible_releases(releases):
    return [release for release in releases if not rejection_details(release)]


# Bilan court pour les journaux : motifs dominants et exemples repérables
def rejection_summary(releases, *, limit=4, reasons_for=None):
    get_reasons = reasons_for or rejection_details
    refusals = [row for row in releases if get_reasons(row)]
    if not refusals:
        return "No detailed rejection"
    counts = Counter(reason for row in refusals for reason in get_reasons(row))
    motifs = "; ".join(f"{reason} ({count})" for reason, count in counts.most_common(limit))
    # Les plus riches en seeders aident à retrouver la release incriminée
    examples = sorted(refusals, key=seeder_score, reverse=True)[:2]
    names = "; ".join(
        f"{str(row.get('title') or '?')[:95]} [indexer: {str(row.get('indexer') or row.get('indexerId') or '?')[:45]}]"
        for row in examples)
    return f"Main reasons: {motifs}. Examples: {names}"
# =================================================


# ======================== CODEC VIDÉO ========================

# Identifie h264 / h265 par les métadonnées ou le nom, sans inventer un codec
# (un x265 collé dans un nom de groupe, sans séparateurs, n'est pas pris en compte)
def video_codec(release):
    title = str(release.get("title") or "")
    raw = release.get("videoCodec") or release.get("codec")
    # L'API n'indique pas toujours le codec : le nom reste la référence
    text = f"{raw or ''} {title}"
    if re.search(r"(?<![a-z0-9])(?:x[. _-]?265|h[. _-]?265|hevc)(?![a-z0-9])", text, re.I):
        return "h265"
    if re.search(r"(?<![a-z0-9])(?:x[. _-]?264|h[. _-]?264|avc)(?![a-z0-9])", text, re.I):
        return "h264"
    return "unknown"
# =================================================


# ======================== ÉQUIPE DE RELEASE ========================

# Fins de titre techniques (WEB-DL, Blu-ray, DTS-HD, DTS-X, DTS-ES…) : ce ne sont pas des équipes
NOT_A_TEAM = frozenset(("dl", "ray", "rip", "hd", "ma", "es", "x", "bit", "multi", "french", "truefrench",
                        "vf", "vff", "vfq", "vostfr", "sub", "subs", "dub", "audio"))


# Équipe d'une release : donnée par Radarr/Sonarr, sinon lue à la fin du nom (« …x264-T3KASHi »). Vide si inconnue
def release_group(release):
    group = str(release.get("releaseGroup") or "").strip()
    if not group:
        found = re.search(r"-\s?([A-Za-z0-9]{2,20})(?:\.(?:FRENCH|mkv|mp4))?$", str(release.get("title") or "").strip(), re.I)
        group = found.group(1) if found and not found.group(1).isdigit() else ""
    if group.lower() in NOT_A_TEAM:
        return ""
    return "".join(ch for ch in group if ch.isprintable())[:40]


# Équipe la plus fréquente d'une liste de noms (None si la liste est vide)
def dominant_team(names):
    counts = {}
    for name in names:
        if name:
            counts.setdefault(name.lower(), [name, 0])[1] += 1
    return max(counts.values(), key=lambda entry: entry[1])[0] if counts else None


# Équipe qui couvre le plus de saisons (au moins 2), à égalité la mieux fournie en seeders.
# seasons : une liste de releases admissibles par saison. Renvoie (équipe, nombre de saisons) ou (None, 0)
def coverage_team(seasons):
    found = {}
    for releases in seasons:
        best = {}
        for release in releases:
            name = release_group(release)
            if name:
                key = name.lower()
                best[key] = (name, max(number_of_seeders(release) or 0, best.get(key, ("", 0))[1]))
        for key, (name, seeders) in best.items():
            entry = found.setdefault(key, [name, 0, 0.0])
            entry[1] += 1
            entry[2] += math.log1p(seeders)
    shared = [entry for entry in found.values() if entry[1] >= 2]
    if not shared:
        return None, 0
    name, count, _ = max(shared, key=lambda entry: (entry[1], entry[2]))
    return name, count
# =================================================


# ======================== CLASSEMENT ========================

# Clé de tri : les seeders décident, le codec et l'équipe préférée ajoutent un bonus (jamais un refus).
# Simulation, automatisation et repli utilisent la même règle ; seeders inconnus en dernier
def release_rank_key(release, team=None):
    seeders = number_of_seeders(release)
    if seeders is None:
        return (0, 0)
    bonus = {"faible": 0.12, "equilibree": 0.35, "forte": 0.65}.get(CODEC_PRIORITY, 0.35)
    codec_bonus = bonus if PREFERRED_CODEC in ("h264", "h265") and video_codec(release) == PREFERRED_CODEC else 0.0
    team_bonus = TEAM_BONUS.get(TEAM_PREFERENCE, 0.0) if team and release_group(release).lower() == team.lower() else 0.0
    return (1, math.log1p(seeders) + codec_bonus + team_bonus)


# Tri stable des releases admissibles (l'ordre de l'API est gardé en cas d'égalité)
def ranked_releases(releases, team=None):
    return sorted(eligible_releases(releases), key=lambda release: release_rank_key(release, team), reverse=True)


# Meilleure release admissible, ou None
def select_release(releases, team=None):
    candidates = ranked_releases(releases, team)
    return candidates[0] if candidates else None
# =================================================


# ======================== REPLI SUR UNE AUTRE LANGUE ========================
# Un film sans version française (muet, non traduit…) est refusé par les règles de langue de Radarr/Sonarr.
# Seuls ces refus-là peuvent être levés, et seulement sur demande : par un envoi manuel, ou automatiquement après
# plusieurs recherches sans résultat (réglage). Tous les autres refus restent absolus : seeders, protocole,
# indexeur ignoré, termes interdits, téléchargement refusé…
LANGUAGE_REASON = re.compile(r"\bis wanted,? but found\b", re.I)
REQUIRED_TERMS = re.compile(r"^Does not contain one of the required terms:?(.*)$", re.I | re.S)
LANGUAGE_TAGS = frozenset((
    "french", "truefrench", "vf", "vff", "vfq", "vfi", "vf2", "multi", "vostfr", "subfrench", "vo", "vost",
    "english", "eng", "fre", "fra", "german", "deutsch", "ger", "spanish", "castellano", "latino", "spa",
    "italian", "ita", "japanese", "jpn", "dutch", "portuguese", "russian", "polish", "korean", "chinese", "ukrainian"))
FRENCH_SUBTITLES = re.compile(r"(?<![a-z0-9])(?:vostfr|subfrench|sub[ ._-]?fr|fr[ ._-]?subs?)(?![a-z0-9])", re.I)


# Refus de langue : « X is wanted but found Y », ou des termes requis parmi lesquels figure une langue.
# Un profil qui exige « x265 » ou une équipe n'a rien à voir avec la langue : il reste absolu
def is_language_reason(reason):
    if LANGUAGE_REASON.search(reason):
        return True
    required = REQUIRED_TERMS.match(reason)
    if not required:
        return False
    words = re.findall(r"[a-z0-9]+", re.sub(r"\\[a-z]", " ", required.group(1).lower()))
    return not LANGUAGE_TAGS.isdisjoint(words)


# Raisons de refus liées à la langue (celles que le repli peut lever)
def language_reasons(release):
    return [reason for reason in rejection_details(release) if is_language_reason(reason)]


# Vrai si la langue est la SEULE raison du refus (et qu'il y en a au moins une)
def language_only_rejected(release):
    reasons = rejection_details(release)
    return bool(reasons) and all(is_language_reason(reason) for reason in reasons)


# Releases refusées pour leur seule langue, les meilleures d'abord : sous-titres français, puis seeders
def language_fallback_candidates(releases):
    candidates = [release for release in releases if language_only_rejected(release)]
    return sorted(candidates, key=lambda r: (bool(FRENCH_SUBTITLES.search(str(r.get("title") or ""))), release_rank_key(r)),
                  reverse=True)


# Meilleure release du repli, ou None
def select_language_fallback(releases):
    candidates = language_fallback_candidates(releases)
    return candidates[0] if candidates else None
# =================================================


# ======================== SAISONS SONARR ========================

# Épisodes manquants d'une saison (au moins 2, pour éviter les faux packs).
# Sonarr v4 : les animes restent cherchés épisode par épisode.
# Sonarr v5 : un pack d'anime est tenté seulement si Sonarr reconnaît une saison entière
def season_episodes(items, series_id, season_number, *, allow_anime=False):
    if type(series_id) is not int or type(season_number) is not int:
        return []
    rows = [item for item in items if item.get("seriesId") == series_id and
            item.get("seasonNumber") == season_number and
            (allow_anime or str(item.get("seriesType", "standard")).lower() != "anime")]
    return rows if len(rows) >= 2 else []


# Raisons de refus d'une release comme pack, même si l'épisode seul serait accepté
def season_pack_rejection_details(release, series_id, season_number):
    reasons = rejection_details(release)
    if release.get("fullSeason") is not True:
        reasons.append("Sonarr does not recognize a pack covering the whole season")
    if release.get("seasonNumber") != season_number:
        reasons.append("Season number differs or is not recognized by Sonarr")
    if release.get("seriesId", series_id) != series_id:
        reasons.append("Release linked to another series")
    return list(dict.fromkeys(reasons))


# Packs que Sonarr reconnaît explicitement comme saison entière
def eligible_season_packs(releases, series_id, season_number):
    return [row for row in releases if not season_pack_rejection_details(row, series_id, season_number)]


# Seconde recherche avant l'envoi : si le GUID a changé, on prend la meilleure release encore admissible.
# Jamais d'envoi si plus rien de valide
def revalidate_selection(client, item, selected, fetch, eligible=eligible_releases, choose=select_release):
    fresh = fetch()
    accepted = eligible(fresh)
    exact = [r for r in accepted if r.get("guid") == selected.get("guid") and
             r.get("indexerId") == selected.get("indexerId")]
    if len(exact) == 1:
        return exact[0]
    if not accepted:
        journal.log(f"[{item['key']}] Second search: no release eligible any more; cancelling", level="WARN")
        return None
    replacement = choose(accepted)
    journal.log(f"[{item['key']}] Initial release missing/rejected on the second search; "
        f"new proposal: '{replacement.get('title', '?')}' ({seeder_score(replacement)} seeders).", level="WARN")
    return replacement
# =================================================


# ======================== JOURNAL DU CHOIX ========================

# Nom de l'indexeur d'une release, pour le journal (jamais de lien : il peut contenir une clé personnelle)
def indexer_name(release):
    return "".join(ch for ch in str(release.get("indexer") or "") if ch.isprintable())[:80].strip()


# Codec suivi de l'indexeur quand Radarr/Sonarr l'indique
def codec_and_indexer(release):
    name = indexer_name(release)
    return f"{video_codec(release)}, indexer: {name}" if name else video_codec(release)


# Écrit dans le journal le résultat d'une sélection
def explain(item, releases, selected):
    accepted = eligible_releases(releases)
    if not selected:
        journal.log(f"[{item['key']}] {item['title']}: {len(releases)} results, "
              "no eligible release.", flush=True)
        if releases:
            journal.log(f"[{item['key']}] {rejection_summary(releases)}", level="WARN")
        return
    seeders = number_of_seeders(selected)
    journal.log(f"[{item['key']}] {item['title']}: {len(releases)} results, "
          f"{len(accepted)} eligible; choice: '{selected.get('title', '?')}' "
          f"({seeders if seeders is not None else '?'} seeders, codec {codec_and_indexer(selected)}).", flush=True)
# =================================================
