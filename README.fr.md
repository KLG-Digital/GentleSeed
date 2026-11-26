<div align="center">

<h1 align="center">
<br>
<a href="https://github.com/KLG-Digital"><img src="./web/assets/gentleseed-logo.svg" alt="GentleSeed Icon" width="140"></a>
<br>
<b>GentleSeed</b>
<br>
</h1>

[English](./README.md) · **Français**

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://github.com/KLG-Digital/GentleSeed/releases)
[![Docker](https://img.shields.io/badge/docker-starkev%2Fgentleseed-2496ED.svg)](https://hub.docker.com/r/starkev/gentleseed)
[![Platform](https://img.shields.io/badge/platform-Docker%20%7C%20Python-lightgrey.svg)](https://github.com/KLG-Digital/GentleSeed)
[![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://github.com/KLG-Digital/GentleSeed)
[![License](https://img.shields.io/badge/license-AGPL%20v3-green.svg)](./LICENSE)

[**Installation**](#démarrage-rapide) · [**Fonctionnalités**](#fonctionnalités) · [**Documentation**](#documentation) · [**Changelog**](./CHANGELOG.md)

</div>

---

## Description

**GentleSeed** est un sélecteur de releases pour **Radarr** et **Sonarr**. Il surveille les films et séries ajoutés, compare les releases que Radarr/Sonarr trouvent (admissibilité, seeders, codec préféré) et rend la meilleure à Radarr/Sonarr — avec une interface web disponible en **14 langues**.

GentleSeed **ne contacte jamais directement votre client de téléchargement** : Radarr et Sonarr gardent la main sur le téléchargement. GentleSeed est un projet indépendant, non affilié à Radarr, Sonarr ou Prowlarr.

## Fonctionnement

1. Radarr/Sonarr préviennent GentleSeed qu'un film ou une série a été ajouté (webhook, avec une vérification légère toutes les 15 s en filet de sécurité).
2. GentleSeed demande à Radarr/Sonarr les releases disponibles et garde celles qu'ils acceptent.
3. Il les classe par seeders puis, si vous le souhaitez, par codec préféré (H.264 / H.265), et renvoie la meilleure à Radarr/Sonarr.

## Fonctionnalités

| # | Fonctionnalité | Description |
|---|----------------|-------------|
| 1 | Nouveaux médias seulement | La bibliothèque présente au premier lancement est ignorée ; seuls les ajouts suivants sont traités |
| 2 | Détection immédiate | Webhook installé dans Radarr/Sonarr depuis l'interface, plus une vérification légère toutes les 15 s |
| 3 | Choix de la release | Radarr/Sonarr décident de l'admissibilité ; GentleSeed classe par seeders et codec préféré |
| 4 | Packs de saison | Sonarr : tente d'abord un pack de saison, puis épisode par épisode |
| 5 | Recherche manuelle | Comparer les releases de n'importe quel média manquant et en envoyer une après confirmation |
| 6 | Anti-doublon | Contrôle la file et l'historique de Radarr/Sonarr avant tout envoi |
| 7 | Activité en direct | Recherche en cours, demandes reçues, file d'attente, suivi des téléchargements et résultats récents |
| 8 | Journaux | Événements filtrables, aperçu des fichiers en couleurs, téléchargement dans votre langue |
| 9 | Sauvegardes | Sauvegarder et restaurer vos réglages (clés API seulement sur demande) |
| 10 | Avis de mise à jour | Lit les releases GitHub et vous informe — ne se met jamais à jour tout seul |
| 11 | Langues et thèmes | 14 langues, thèmes sombre / clair / automatique et couleurs d'équipe |
| 12 | Indexeurs à ignorer | Cocher les indexeurs (lus dans Radarr et Sonarr) dont GentleSeed ne doit jamais choisir une release |
| 13 | Aucune release dans votre langue | Une release refusée uniquement pour sa langue peut être envoyée après confirmation, ou automatiquement après N recherches vides (désactivé par défaut) |

## Aperçu

Captures de l'interface en anglais (14 langues disponibles).

<details open>
<summary><b>Pages</b></summary>
<br>

| Tableau de bord | Recherches |
|:---:|:---:|
| <img src="./docs/screenshots/dashboard-desktop.webp" alt="Dashboard" width="420"> | <img src="./docs/screenshots/search-desktop.webp" alt="Searches" width="420"> |
| En cours | Journaux |
| <img src="./docs/screenshots/running-desktop.webp" alt="In progress" width="420"> | <img src="./docs/screenshots/logs-desktop.webp" alt="Logs" width="420"> |
| Paramètres | Système |
| <img src="./docs/screenshots/settings-desktop.webp" alt="Settings" width="420"> | <img src="./docs/screenshots/system-desktop.webp" alt="System" width="420"> |

</details>

<details open>
<summary><b>Mobile</b></summary>
<br>

| Tableau de bord | Recherches | En cours | Journaux |
|:---:|:---:|:---:|:---:|
| <img src="./docs/screenshots/dashboard-mobile.webp" alt="Dashboard (mobile)" width="170"> | <img src="./docs/screenshots/search-mobile.webp" alt="Searches (mobile)" width="170"> | <img src="./docs/screenshots/running-mobile.webp" alt="In progress (mobile)" width="170"> | <img src="./docs/screenshots/logs-mobile.webp" alt="Logs (mobile)" width="170"> |

</details>

<details>
<summary><b>Thèmes</b></summary>
<br>

**Auto** suit votre système (sombre ou clair). Les cinq derniers sont les thèmes **Gentle Mates**, aux couleurs d'une équipe, dont **Violet (Paris 2027)**.

| Sombre | Clair |
|:---:|:---:|
| <img src="./docs/screenshots/theme-dark.webp" alt="Sombre" width="420"> | <img src="./docs/screenshots/theme-light.webp" alt="Clair" width="420"> |
| Gentle Mates · Rose pastel | Gentle Mates · Sombre |
| <img src="./docs/screenshots/theme-rose.webp" alt="Rose pastel" width="420"> | <img src="./docs/screenshots/theme-black.webp" alt="Sombre" width="420"> |
| Gentle Mates · Paris (lavande) | Gentle Mates · Bleu |
| <img src="./docs/screenshots/theme-paris.webp" alt="Paris (lavande)" width="420"> | <img src="./docs/screenshots/theme-worlds.webp" alt="Bleu" width="420"> |
| Gentle Mates · Violet (Paris 2027) | |
| <img src="./docs/screenshots/theme-violet.webp" alt="Violet (Paris 2027)" width="420"> | |

</details>

## Démarrage rapide

```bash
docker run -d --name gentleseed --restart unless-stopped --stop-timeout 30 \
  -p 1853:1853 -v gentleseed_data:/data \
  starkev/gentleseed:latest
```

Ouvrez `http://IP-DU-SERVEUR:1853`, suivez la page de premier lancement (thème et connexion), puis saisissez l'adresse et la clé API de Radarr et/ou Sonarr dans **Paramètres → Connexions**.

> Avant de commencer, décochez la recherche automatique à l'ajout dans Radarr/Sonarr (et Seerr/Overseerr), sinon ils cherchent de leur côté et vous obtenez des **doubles téléchargements**. Voir le [guide d'installation](./docs/INSTALL.fr.md#éviter-un-double-téléchargement-important).

Docker Compose, TrueNAS SCALE et un lancement sans Docker (Python) sont décrits dans le [guide d'installation](./docs/INSTALL.fr.md).

## Documentation

- [Guide d'installation](./docs/INSTALL.fr.md) — Docker Compose, image Docker, Python, éviter un double téléchargement, sécurité, notes, structure du projet
- [Docker / TrueNAS SCALE](./docs/README_DOCKER.fr.md) — port, contrôle de santé, application personnalisée
- [Changelog](./CHANGELOG.md)
- [Contribuer](./CONTRIBUTING.md) · [Politique de sécurité](./.github/SECURITY.md)

## Soutenir le projet

Si vous appréciez GentleSeed, pensez à mettre une étoile au dépôt GitHub.

## Auteur

| [StarKev](https://github.com/StarKev) |
|---------------------------------------|
| [![StarKev](https://avatars.githubusercontent.com/u/122538129?s=80&v=4)](https://github.com/StarKev) |

## Licence

Copyright (C) 2026 Kevin Lemos Graça (StarKev) — KLG Digital.

Ce projet est distribué sous la **GNU Affero General Public License v3.0** (AGPL-3.0). Consultez le fichier [LICENSE](./LICENSE) pour plus de détails.
