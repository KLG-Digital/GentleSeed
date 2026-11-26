# ======================== IMPORTS ========================
import time

import requests

from backend.engine import activity as Activity
from backend.engine import diagnostics as Diagnostics
from backend.engine import journal as journal
from backend.engine import ranking as Ranking
from backend.engine.arr_client import RateLimitedError
from backend.engine.ranking import (eligible_season_packs, explain, language_fallback_candidates, rejection_summary, revalidate_selection,
                                    select_language_fallback,
                                    season_episodes, season_pack_rejection_details, seeder_score,
                                    select_release, codec_and_indexer)
from backend.engine.store import save_state, reserve_handoff
# =================================================


# ======================== CONFIGURATION ========================
# Valeurs de départ : search.configure_engine() les remplace par les réglages enregistrés.
# DRY_RUN est l'interrupteur de développement : aucune demande de téléchargement n'est envoyée
DRY_RUN = False

# True : ne surveille que les médias ajoutés APRÈS le premier lancement
ONLY_NEW = True

CHECK_INTERVAL = 300
RETRY_INTERVAL = 21600
MAX_SEARCHES_PER_CYCLE = 2
# Recherches sans résultat avant d'accepter une autre langue (0 = jamais) ; remplacé par le réglage de l'interface
LANGUAGE_FALLBACK_AFTER = 0
# Un délai dépassé = un essai raté : retenté dans 30 min (puis de plus en plus tard), pas dans 6 h
SLOW_RETRY_SECONDS = 1800
# =================================================


# ======================== ÉQUIPE DE LA SÉRIE ========================
MAX_COMPARED_SEASONS = 2  # saisons cherchées en plus de la saison en cours pour choisir une équipe


# Équipe déjà connue pour une série : dernier choix mémorisé, sinon fichiers présents dans Sonarr.
# Renvoie (équipe ou None, origine « memory » / « files » / None)
def known_team(client, memory, series_id):
    if Ranking.TEAM_PREFERENCE == "off" or client.name != "sonarr" or type(series_id) is not int:
        return None, None
    remembered = (memory or {}).get(str(series_id))
    if remembered and str(remembered).lower() not in Ranking.NOT_A_TEAM:
        return remembered, "memory"
    if not hasattr(client, "episode_file_groups"):
        return None, None
    try:
        team = Ranking.dominant_team([name for name in client.episode_file_groups(series_id)
                                      if str(name).lower() not in Ranking.NOT_A_TEAM])
    except RateLimitedError:
        raise  # HTTP 429 : la pause demandée par Sonarr s'applique
    except (requests.RequestException, ValueError, RuntimeError) as error:
        journal.log(f"[sonarr] Episode files unreadable: {type(error).__name__}", level="DEBUG")
        return None, None
    return (team, "files") if team else (None, None)


# Équipe à préférer pour une saison. Sans équipe connue, on cherche aussi d'autres saisons manquantes :
# une équipe présente sur plusieurs saisons vaut mieux qu'une équipe qui n'a sorti que la première
def season_team(client, memory, series_id, candidates, other_seasons, tag):
    if Ranking.TEAM_PREFERENCE == "off":
        return None
    team, origin = known_team(client, memory, series_id)
    if origin == "memory":
        journal.log(f"[{tag}] Preferred release team: {team} (last choice for this series)")
    elif origin == "files":
        journal.log(f"[{tag}] Preferred release team: {team} (files already in Sonarr)")
    if team or not other_seasons:
        return team
    compared = [candidates]
    for number in list(other_seasons)[:MAX_COMPARED_SEASONS]:
        try:
            compared.append(eligible_season_packs(client.season_releases(series_id, number), series_id, number))
        except RateLimitedError:
            raise
        except (requests.RequestException, ValueError, RuntimeError) as error:
            journal.log(f"[{tag}] Season {number} not compared: {type(error).__name__}", level="WARN")
    team, count = Ranking.coverage_team(compared)
    if team is None:
        journal.log(f"[{tag}] No release team covers several seasons: normal choice")
        return None
    journal.log(f"[{tag}] Preferred release team: {team} (found in {count} of the {len(compared)} seasons searched)")
    if memory is not None and not DRY_RUN:
        memory[str(series_id)] = team
    return team
# =================================================


# ======================== VÉRIFICATION D'UN MÉDIA ========================

# Cherche, choisit et envoie la meilleure release d'un film ou d'un épisode.
# Renvoie : queued, empty, simulated, stale ou grabbed.
# fallback : le média a déjà eu assez de recherches vides, les refus de langue peuvent être levés
def check_item(client, item, queued, before_grab=None, auto_test=False, fallback=False, team=None):
    if item["id"] in queued:
        journal.log(f"[{item['key']}] Already in the queue: no new download.", flush=True)
        return "queued"
    releases = client.releases(item["id"])
    choose = (lambda rows: select_release(rows, team)) if team else select_release
    selected = choose(releases)
    using_fallback = False
    if selected is None and fallback:
        selected = select_language_fallback(releases)
        using_fallback = selected is not None
        if using_fallback:
            journal.log(f"[{item['key']}] No release in the required language after {LANGUAGE_FALLBACK_AFTER} searches: "
                        "other languages are now accepted for this media", level="WARN")
    explain(item, releases, selected)
    if selected is None:
        return "empty"
    if DRY_RUN and not auto_test:
        journal.log(f"[{item['key']}] SIMULATION: no download handed off.", flush=True)
        return "simulated"
    # Sécurité : le média doit toujours être surveillé, manquant et hors file
    # (pas d'envoi après un import concurrent)
    if item["id"] in client.queued_ids():
        journal.log(f"[{item['key']}] New queue entry detected: cancelling.", flush=True)
        return "queued"
    if client.recently_grabbed(item["id"]):
        journal.log(f"[{item['key']}] {client.name.title()} already grabbed a release for this media (recent history): "
            "no second download.", flush=True)
        return "queued"
    current = client.missing_items()
    if item["id"] not in {m["id"] for m in current}:
        journal.log(f"[{item['key']}] Media not missing or not monitored: cancelling.", flush=True)
        return "stale"
    # La seconde recherche peut changer de GUID : on rechoisit parmi les résultats encore admissibles
    if using_fallback:
        fresh = revalidate_selection(client, item, selected, lambda: client.releases(item["id"]),
                                     eligible=language_fallback_candidates, choose=lambda rows: rows[0])
    else:
        fresh = revalidate_selection(client, item, selected, lambda: client.releases(item["id"]), choose=choose)
    if fresh is None:
        return "stale"
    if item["id"] in client.queued_ids():
        journal.log(f"[{item['key']}] Queue changed between searches: cancelling")
        return "queued"
    if before_grab is not None:
        before_grab()  # réservation anti-doublon par média, avant tout envoi
    # Un seul envoi de test peut contourner la simulation, et seulement si l'utilisateur l'a armé
    response = client.grab(fresh, manual_test=True) if auto_test else client.grab(fresh)
    if isinstance(response, dict) and (response.get("success") is False or response.get("error")):
        raise RuntimeError(f"{client.name.title()} refused the release")
    try:
        from backend.engine import delivery as DeliveryTracker
        DeliveryTracker.register(client.name, item["id"], fresh,
                                 source="automatique-test" if auto_test else "automatique")
    except (OSError, ValueError, RuntimeError) as error:
        # La requête est déjà partie : ne surtout PAS la renvoyer
        journal.log(f"[{item['key']}] Request sent, tracking not recorded: {type(error).__name__}", level="WARN")
    return "grabbed"
# =================================================


# ======================== PACK DE SAISON SONARR ========================

# Nom lisible pour le journal : « Death Note - S01E03 » devient « Death Note »
def series_name(title):
    text = str(title or "?")
    return text.rsplit(" - S", 1)[0] if " - S" in text else text


# Tente un pack de saison pour plusieurs épisodes manquants d'une nouvelle série.
# Sans pack reconnu par Sonarr, on revient à la recherche épisode par épisode.
# Le pack n'est envoyé qu'UNE fois pour la saison
def check_season(client, series_id, season_number, episodes, queued, before_grab=None, auto_test=False, allow_anime=False,
                 teams=None, other_seasons=()):
    if client.name != "sonarr" or len(episodes) < 2:
        return "none"
    key = f"sonarr:season:{series_id}:{season_number}"
    tag = f"{key} · {series_name(episodes[0].get('title'))} S{season_number:02d}"
    item = {"key": key, "id": episodes[0]["id"],
            "title": f"Series {series_id} · season {season_number}"}
    episode_ids = {e["id"] for e in episodes}
    if episode_ids & queued:
        journal.log(f"[{tag}] Season partially in the queue: pack search skipped")
        return "queued"
    releases = client.season_releases(series_id, season_number)
    candidates = eligible_season_packs(releases, series_id, season_number)
    team = season_team(client, teams, series_id, candidates, other_seasons, tag) if candidates else None
    choose = (lambda rows: select_release(rows, team)) if team else select_release
    selected = choose(candidates)
    if selected is None:
        journal.log(f"[{tag}] No eligible season pack: falling back to episodes")
        if releases:
            journal.log(f"[{tag}] Diagnostics of the {len(releases)} season results: "
                f"{rejection_summary(releases, reasons_for=lambda row: season_pack_rejection_details(row, series_id, season_number))}", level="INFO")
        return "none"
    journal.log(f"[{tag}] {len(releases)} results, {len(candidates)} eligible packs; "
        f"proposal '{selected.get('title','?')}' ({seeder_score(selected)} seeders, codec {codec_and_indexer(selected)})")
    if DRY_RUN and not auto_test:
        journal.log(f"[{tag}] SEASON PACK SIMULATION: nothing sent")
        return "simulated"
    if episode_ids & client.queued_ids():
        return "queued"
    # L'historique est à jour avant la file : un pack déjà pris par Sonarr (recherche à l'ajout) ne se double pas
    for episode_id in sorted(episode_ids):
        if client.recently_grabbed(episode_id):
            journal.log(f"[{tag}] Sonarr already grabbed a release for this season (recent history): no second download.", flush=True)
            return "queued"
    current = client.missing_items()
    still_missing = season_episodes(current, series_id, season_number, allow_anime=allow_anime)
    if not episode_ids.issubset({e["id"] for e in still_missing}):
        journal.log(f"[{tag}] Episodes became unavailable/unmonitored: pack cancelled", level="WARN")
        return "stale"
    fresh = revalidate_selection(client, item, selected,
             lambda: client.season_releases(series_id, season_number),
             lambda rows: eligible_season_packs(rows, series_id, season_number), choose=choose)
    if fresh is None:
        return "none"
    if episode_ids & client.queued_ids():
        return "queued"
    if before_grab:
        before_grab()
    response = client.grab(fresh, manual_test=True) if auto_test else client.grab(fresh)
    if isinstance(response, dict) and (response.get("success") is False or response.get("error")):
        raise RuntimeError("Sonarr refused the season pack")
    try:
        from backend.engine import delivery as DeliveryTracker
        # Un seul épisode représente la saison dans le suivi (il ne prétend pas que tous sont importés)
        DeliveryTracker.register("sonarr", episodes[0]["id"], fresh,
            source="saison-automatique-test" if auto_test else "saison-automatique")
    except (OSError, ValueError, RuntimeError) as error:
        journal.log(f"[{tag}] Send done, tracking impossible: {type(error).__name__}", level="WARN")
    if teams is not None and Ranking.TEAM_PREFERENCE != "off" and Ranking.release_group(fresh):
        teams.setdefault(str(series_id), Ranking.release_group(fresh))
    journal.log(f"[{tag}] Pack handed to Sonarr for {len(episode_ids)} missing episodes")
    return "grabbed"
# =================================================


# ======================== AFFICHAGE ET ESSAIS RATÉS ========================

# File prévue pour la page « En cours » : ce que ce passage va tenter, nouveautés d'abord
def plan_activity(service, items, tracked, fresh, attempts, queued, now):
    due = [i for i in items if (not ONLY_NEW or i["key"] in tracked) and i["id"] not in queued
           and now - float(attempts.get(i["key"], 0)) >= RETRY_INTERVAL]
    plan, seen = [], set()
    groups = {}
    if service == "sonarr":
        for i in due:
            if type(i.get("seriesId")) is int and type(i.get("seasonNumber")) is int:
                groups.setdefault((i["seriesId"], i["seasonNumber"]), []).append(i)
    for i in due:
        group = groups.get((i.get("seriesId"), i.get("seasonNumber")), [])
        if len(group) >= 2:
            key = f"sonarr:season:{i['seriesId']}:{i['seasonNumber']}"
            if key in seen:
                continue
            seen.add(key)
            plan.append({"key": key, "kind": "season", "fresh": any(g["key"] in fresh for g in group),
                         "title": f"{series_name(i.get('title'))} · season {i['seasonNumber']} ({len(group)} episodes)"})
        else:
            plan.append({"key": i["key"], "kind": "episode" if service == "sonarr" else "movie",
                         "fresh": i["key"] in fresh, "title": i.get("title", "?")})
    plan.sort(key=lambda e: not e["fresh"])
    return plan


# Résultat affiché pour une erreur : délai dépassé ou erreur
def activity_outcome(error):
    return "timeout" if isinstance(error, requests.Timeout) else "error"


# Un délai dépassé = un essai sans résultat : on passe au suivant et on retentera plus tard
# (30 min, puis 1 h, 2 h, 4 h… jusqu'au délai normal), sans relancer le média toutes les 30 min
def register_timeout(key, attempts, hits):
    hits[key] = int(hits.get(key, 0)) + 1
    wait = min(RETRY_INTERVAL, SLOW_RETRY_SECONDS * 2 ** min(hits[key] - 1, 10))
    attempts[key] = time.time() - RETRY_INTERVAL + wait
# =================================================


# ======================== PASSAGE AUTOMATIQUE ========================

# Un passage de surveillance, sans confondre nouveauté et média manquant.
# Un service doit fournir le catalogue complet ET les médias manquants ;
# un échec de lecture bloque ce service seulement, sans toucher à son état.
# Comme Radarr/Sonarr : un essai par média, sans insister (rien trouvé ou délai dépassé :
# on passe au suivant et on retente plus tard). Les NOUVEAUTÉS sont cherchées en premier
# et jamais interrompues ; l'arriéré s'arrête dès que interrupt() renvoie vrai (nouvelle demande)
def check_once(clients, state, *, local_auto_test=False, interrupt=None):
    # --- 1. Lecture de l'inventaire et du catalogue de chaque service ---
    inventory, catalog = {}, {}
    cycle_started = time.monotonic()
    now = time.time()
    Activity.clear_inbox()
    Activity.clear_running()
    backoff = state.setdefault("service_backoff", {})
    for client in clients:
        if float(backoff.get(client.name, 0)) > now:
            continue
        try:
            if hasattr(client, "inventory"):
                items, ids = client.inventory()  # une seule lecture de la liste complète
            else:
                items = client.missing_items()
                # Les faux clients des tests n'ont pas toujours catalog_ids
                ids = client.catalog_ids() if hasattr(client, "catalog_ids") else None
            if not isinstance(items, list):
                raise RuntimeError("Invalid inventory")
            if ids is None:
                ids = {i["id"] for i in items}
            if not isinstance(ids, set):
                raise RuntimeError("Invalid catalog")
            inventory[client.name], catalog[client.name] = items, ids
        except RateLimitedError as error:
            backoff[client.name] = now + error.retry_after
            journal.log(f"[{client.name}] HTTP 429: pausing for {error.retry_after}s", level="WARN")
        except (requests.RequestException, ValueError, RuntimeError, KeyError, TypeError) as error:
            journal.log(f"[{client.name}] Inventory unavailable: {Diagnostics.error_text(error, client.name)}", level="WARN")

    # --- 2. Repérage des nouveautés ---
    known = set(state.get("known", []))
    tracked = set(state.get("tracked", []))
    attempts = state.setdefault("last_attempt", {})
    hits = state.setdefault("timeout_hits", {})
    empty_searches = state.setdefault("empty_searches", {})
    baselined = set(state.get("baselined_services", []))
    catalog_baselines = state.setdefault("catalog_baselines", {})
    new_series = set(state.get("new_series", []))
    new_movies = set(state.get("new_movies", []))
    fresh = set()  # clés apparues depuis le dernier passage ET suivies : traitées en priorité
    now = time.time()

    for service, items in inventory.items():
        ids = catalog[service]
        current_keys = {item["key"] for item in items}
        previous = catalog_baselines.get(service)
        if ONLY_NEW and previous is None:
            # Premier passage : on photographie TOUS les films/séries existants, sans rien sélectionner
            catalog_baselines[service] = sorted(ids)
            baselined.add(service)
            known.update(current_keys)
            journal.log(f"[{service}] Catalog reference: {len(ids)} pre-existing media ignored")
            continue

        previous_ids = set(previous or [])
        new_ids = ids - previous_ids if ONLY_NEW else ids
        if ONLY_NEW and new_ids:
            names = sorted({(series_name(i.get("title")) if service == "sonarr" else str(i.get("title", "?")))
                            for i in items
                            if (i.get("seriesId") if service == "sonarr" else i.get("id")) in new_ids})
            shown = ", ".join(names[:5]) + (f" (+{len(names) - 5})" if len(names) > 5 else "")
            if shown:
                journal.log(f"[{service}] {len(new_ids)} new addition(s) to the catalog since the last analysis: {shown}")
            else:
                journal.log(f"[{service}] {len(new_ids)} new addition(s) to the catalog since the last analysis")
        if service == "radarr":
            new_movies.update(f"radarr:{mid}" for mid in new_ids)
            tracked.update(item["key"] for item in items if item["key"] in new_movies)
        elif service == "sonarr":
            new_series.update(f"sonarr:{sid}" for sid in new_ids)
            tracked.update(item["key"] for item in items
                           if f"sonarr:{item.get('seriesId')}" in new_series)
        if ONLY_NEW:
            fresh.update((current_keys - known) & tracked)
        known.update(current_keys)
        catalog_baselines[service] = sorted(ids)
        baselined.add(service)

    # Une série ajoutée reste suivie pour ses épisodes futurs, mais une série supprimée ne l'est plus
    if "sonarr" in catalog_baselines and "sonarr" in catalog:
        new_series &= {f"sonarr:{sid}" for sid in catalog["sonarr"]}
    if "radarr" in catalog_baselines and "radarr" in catalog:
        new_movies &= {f"radarr:{mid}" for mid in catalog["radarr"]}

    state.update({"known": sorted(known), "tracked": sorted(tracked),
                  "baselined_services": sorted(baselined),
                  "catalog_baselines": catalog_baselines,
                  "new_series": sorted(new_series), "new_movies": sorted(new_movies),
                  "initialized": bool(baselined)})
    # La référence est écrite avant toute recherche : un redémarrage ne prendra pas
    # les médias existants pour de nouveaux ajouts
    save_state(state)

    # --- 3. Recherches, service par service ---
    remaining = MAX_SEARCHES_PER_CYCLE
    for client in clients:
        items = inventory.get(client.name)
        if items is None:
            continue
        current_keys = {item["key"] for item in items}
        for gone in [name for name in empty_searches if name.startswith(f"{client.name}:") and name not in current_keys]:
            del empty_searches[gone]  # média plus manquant : son compteur n'a plus lieu d'être
        tracked = {key for key in tracked if not key.startswith(f"{client.name}:") or key in current_keys}
        if remaining <= 0:
            continue
        if ONLY_NEW and not any(key.startswith(f"{client.name}:") for key in tracked):
            continue
        try:
            queued = client.queued_ids()
        except RateLimitedError as error:
            backoff[client.name] = time.time() + error.retry_after
            journal.log(f"[{client.name}] HTTP 429 on queue: pausing for {error.retry_after}s", level="WARN")
            continue
        except (requests.RequestException, ValueError, RuntimeError) as error:
            journal.log(f"[{client.name}] Queue unavailable: {Diagnostics.error_text(error, client.name)}", level="WARN")
            continue
        Activity.set_queue(client.name, plan_activity(client.name, items, tracked, fresh, attempts, queued, time.time()))
        # Niveau Debug : état du service au début de ses recherches
        followed = [item for item in items if item["key"] in tracked]
        waiting = sum(1 for item in followed if now - float(attempts.get(item["key"], 0)) < RETRY_INTERVAL)
        journal.log(f"[{client.name}] {len(items)} missing media, {len(followed)} tracked, {waiting} waiting for the retry delay", level="DEBUG")
        # Saisons Sonarr d'abord : un pack reconnu évite N recherches d'épisodes
        # (en v5, les animes peuvent aussi tenter une saison). Sinon, recherche épisode par épisode
        season_handled = set()
        if client.name == "sonarr" and hasattr(client, "season_releases"):
            allow_anime = (client.supports_anime_season_packs()
                           if hasattr(client, "supports_anime_season_packs") else False)
            grouped = {}
            for e in items:
                if (e["key"] in tracked
                        and type(e.get("seriesId")) is int and type(e.get("seasonNumber")) is int):
                    grouped.setdefault((e["seriesId"], e["seasonNumber"]), []).append(e)
            for (sid, sn), episodes in grouped.items():
                if remaining <= 0:
                    break
                episodes = season_episodes(episodes, sid, sn, allow_anime=allow_anime)
                if not episodes or any(e["id"] in queued for e in episodes):
                    continue
                if interrupt and interrupt() and not any(e["key"] in fresh for e in episodes):
                    remaining = 0  # nouvelle demande reçue : l'arriéré attend le prochain passage
                    break
                skey = f"sonarr:season:{sid}:{sn}"
                if now - float(attempts.get(skey, 0)) < RETRY_INTERVAL:
                    continue
                attempts[skey] = now
                state["last_attempt"] = attempts
                save_state(state)
                remaining -= 1
                aid = Activity.start("sonarr", "season", skey,
                                     f"{series_name(episodes[0].get('title'))} · season {sn} ({len(episodes)} episodes)",
                                     fresh=any(e["key"] in fresh for e in episodes))
                try:
                    armed_until = float(state.get("auto_test_armed_until", 0))
                    excluded = set(state.get("auto_test_excluded_keys", []))
                    use_test = bool(local_auto_test and DRY_RUN and armed_until > time.time()
                                    and not any(e["key"] in excluded for e in episodes))
                    def before_pack_send(media_key=skey, permitted=use_test, aid=aid):
                        Activity.phase(aid, "Sending to Sonarr")
                        if permitted:
                            if float(state.get("auto_test_armed_until", 0)) <= time.time():
                                raise RuntimeError("Automatic authorization expired")
                            state["auto_test_armed_until"] = 0
                            save_state(state)
                            journal.log(f"[{media_key}] Single-use test authorization consumed")
                        reserve_handoff(state, media_key)
                    result = check_season(client, sid, sn, episodes, queued,
                               before_grab=before_pack_send if (not DRY_RUN or use_test) else None,
                               auto_test=use_test, allow_anime=allow_anime,
                               teams=state.setdefault("series_teams", {}),
                               other_seasons=sorted(number for (other, number), rows in grouped.items()
                                                    if other == sid and number != sn and len(rows) >= 2))
                    Activity.finish(aid, result)
                    hits.pop(skey, None)
                    if result in ("grabbed", "queued", "simulated"):
                        season_handled.update(e["key"] for e in episodes)
                        Activity.drop_from_queue(client.name, [e["key"] for e in episodes])
                    if result == "grabbed":
                        tracked.difference_update(e["key"] for e in episodes)
                except RateLimitedError as error:
                    Activity.finish(aid, "error", "HTTP 429: Sonarr asks to slow down")
                    backoff[client.name] = time.time() + error.retry_after
                    journal.log(f"[sonarr] HTTP 429 during season search: pausing for {error.retry_after}s", level="WARN")
                    remaining = 0
                    break
                except (requests.RequestException, ValueError, RuntimeError) as error:
                    Activity.finish(aid, activity_outcome(error), str(error))
                    journal.log(f"[{skey}] {series_name(episodes[0].get('title'))} S{sn:02d}: season search impossible: {error}", level="WARN")
                    if isinstance(error, requests.Timeout):
                        register_timeout(skey, attempts, hits)

        # Épisodes et films un par un, nouveautés d'abord (tri stable)
        for item in sorted(items, key=lambda it: it["key"] not in fresh):
            if remaining <= 0:
                break
            if item["key"] in season_handled:
                continue
            key = item["key"]
            if ONLY_NEW and key not in tracked:
                continue
            if key not in fresh:
                if interrupt and interrupt():
                    break  # nouvelle demande reçue : l'arriéré attend le prochain passage
            if now - float(attempts.get(key, 0)) < RETRY_INTERVAL:
                continue
            # Horodatage enregistré AVANT la recherche : pas de boucle après un redémarrage brutal
            attempts[key] = now
            state["last_attempt"] = attempts
            save_state(state)
            remaining -= 1
            aid = Activity.start(client.name, "episode" if client.name == "sonarr" else "movie", key,
                                 item.get("title", "?"), fresh=key in fresh)
            try:
                # Test réel : un jeton temporaire, un seul média, consommé AVANT l'envoi
                armed_until = float(state.get("auto_test_armed_until", 0))
                # Le jeton ne s'applique jamais à un média déjà en attente avant l'activation du test
                excluded = set(state.get("auto_test_excluded_keys", []))
                use_test = bool(local_auto_test and DRY_RUN and armed_until > time.time()
                                and key not in excluded)
                def before_send(media_key=key, use_test=use_test, aid=aid):
                    Activity.phase(aid, f"Sending to {client.name.capitalize()}")
                    if use_test:
                        if float(state.get("auto_test_armed_until", 0)) <= time.time():
                            raise RuntimeError("Automatic test authorization expired")
                        state["auto_test_armed_until"] = 0
                        save_state(state)
                        journal.log(f"[{media_key}] Single-use automatic authorization consumed")
                    reserve_handoff(state, media_key)
                empty_count = int(empty_searches.get(key, 0))
                team = known_team(client, state.get("series_teams"), item.get("seriesId"))[0]
                result = check_item(client, item, queued, team=team,
                                    before_grab=before_send if (not DRY_RUN or use_test) else None,
                                    auto_test=use_test,
                                    fallback=bool(LANGUAGE_FALLBACK_AFTER) and empty_count >= LANGUAGE_FALLBACK_AFTER)
                Activity.finish(aid, result)
                hits.pop(key, None)
                # Recherches sans résultat de ce média (déclenche le repli de langue, s'il est activé)
                if result == "empty":
                    empty_searches[key] = empty_count + 1
                    if LANGUAGE_FALLBACK_AFTER:
                        journal.log(f"[{key}] Search with no result #{empty_count + 1} (other languages accepted from #{LANGUAGE_FALLBACK_AFTER + 1})", level="DEBUG")
                    else:
                        journal.log(f"[{key}] Search with no result #{empty_count + 1}", level="DEBUG")
                elif result in ("grabbed", "queued", "simulated"):
                    empty_searches.pop(key, None)
                if result in ("grabbed", "queued"):
                    tracked.discard(key)
            except RateLimitedError as error:
                Activity.finish(aid, "error", "HTTP 429: the service asks to slow down")
                backoff[client.name] = time.time() + error.retry_after
                journal.log(f"[{client.name}] HTTP 429: pausing for {error.retry_after}s", level="WARN")
                break
            except (requests.RequestException, ValueError, RuntimeError) as error:
                Activity.finish(aid, activity_outcome(error), str(error))
                journal.log(f"[{key}] {item.get('title', '?')}: search or hand-off error: {error}", level="WARN")
                if isinstance(error, requests.Timeout):
                    register_timeout(key, attempts, hits)

    journal.log(f"Cycle finished in {time.monotonic() - cycle_started:.1f} s: {MAX_SEARCHES_PER_CYCLE - remaining} search(es) started", level="DEBUG")
    state.update({"known": sorted(known), "tracked": sorted(tracked),
                  "last_attempt": attempts, "new_series": sorted(new_series),
                  "new_movies": sorted(new_movies), "service_backoff": backoff})
    save_state(state)
# =================================================
