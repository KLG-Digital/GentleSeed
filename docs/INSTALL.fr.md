# GentleSeed — Guide d'installation

[English](INSTALL.md) · **Français**

## Prérequis

- **Docker** avec Docker Compose, **ou** Python 3.12+
- **Radarr et/ou Sonarr** joignables depuis GentleSeed, avec leurs clés API
- **Port** : `1853` par défaut (`WEB_PORT` pour le changer)

## Installation & Utilisation

### Option 1 — Docker Compose (recommandé)

1. **Cloner** le dépôt (ou le télécharger) et ouvrir le dossier
2. **Démarrer** GentleSeed :
   ```bash
   docker compose up -d --build
   ```
3. **Ouvrir** `http://IP-DU-SERVEUR:1853` et suivre la page de premier lancement (thème et connexion)
4. Dans **Paramètres → Connexions**, saisir l'adresse et la clé API de Radarr et/ou Sonarr

> Sur TrueNAS SCALE, coller `docker-compose.truenas.yml` dans une application personnalisée (image publiée, rien à construire). Plus de détails dans [README_DOCKER.fr.md](README_DOCKER.fr.md).

### Option 2 — Image Docker

```bash
docker run -d --name gentleseed --restart unless-stopped --stop-timeout 30 \
  -p 1853:1853 -v gentleseed_data:/data \
  starkev/gentleseed:latest
```

Image sur [Docker Hub](https://hub.docker.com/r/starkev/gentleseed). Le volume `gentleseed_data` conserve vos réglages, votre compte et vos journaux.

### Option 3 — Sans Docker (Python)

```bash
pip install -r requirements.txt
python main.py          # écoute sur 127.0.0.1:1853
```

Définir la variable d'environnement `WEB_HOST=0.0.0.0` pour y accéder depuis le réseau. Vos données sont dans `data/`.

## Éviter un double téléchargement (important)

Quand un film ou une série est ajouté, Radarr/Sonarr (ou Seerr/Overseerr) lancent par défaut **leur propre recherche**. Pour que GentleSeed soit le seul à choisir, **décochez la recherche automatique à l'ajout** :

| Application | Où | Case à décocher |
|---|---|---|
| **Radarr** | fenêtre « Ajouter un film » | *Démarrer la recherche du film manquant* |
| **Sonarr** | fenêtre « Ajouter une série » | *Démarrer la recherche des épisodes manquants* (et celle des épisodes sous le seuil) |
| **Listes d'import** (Radarr/Sonarr) | Réglages → Listes | *Recherche à l'ajout* |
| **Seerr / Overseerr** | Réglages → Services → serveur Radarr/Sonarr | *Activer la recherche automatique* |

Ouvrez ensuite **Paramètres → Intégration** dans GentleSeed et cliquez **Installer** puis **Tester** pour chaque service. Si vous ne pouvez pas décocher l'option, réglez « Délai avant analyse d'un nouveau média » à 30 s dans les paramètres avancés : GentleSeed attend Radarr/Sonarr et contrôle leur historique avant tout envoi.

## Sécurité

- Gardez la **connexion par formulaire**. Le mode « Aucun » n'est accepté que depuis le réseau local, jamais derrière un proxy.
- N'exposez pas directement le port sur Internet ; utilisez un VPN ou un reverse proxy HTTPS correctement configuré.
- Le conteneur tourne sans droits administrateur, avec un système de fichiers en lecture seule et un contrôle de santé.
- Les clés API ne sont plus jamais affichées une fois enregistrées, et ne sont pas incluses dans les sauvegardes sauf demande.

Pour signaler une faille, voir la [politique de sécurité](../.github/SECURITY.md).

## Notes

- **GentleSeed commence à surveiller dès que la surveillance automatique est activée** (Paramètres → Général) : les releases sont réellement envoyées à Radarr/Sonarr. Un envoi manuel demande toujours une confirmation.
- Les **données** (`settings.json`, `state.json`, journaux, compte) sont dans `/data` (Docker) ou `data/` (sans Docker). Ne jamais publier ce dossier.
- **Icône sur l'écran d'accueil** (iPhone/Android) : supprimez puis rajoutez le raccourci après une mise à jour, car iOS garde l'ancienne icône en cache.
- **Redémarrer** est disponible dans le menu utilisateur ; **Arrêter** seulement sans Docker (le conteneur redémarre tout seul).

## Structure du projet

```
GentleSeed/
├── backend/                 # Code Python (FastAPI)
│   ├── engine/              # choix des releases, activité, suivi
│   ├── routes/              # routes de l'API, rangées par thème
│   └── services/            # intégration *arr, sauvegardes, mises à jour
├── web/                     # interface (HTML, CSS, JavaScript)
│   ├── pages/               # une section HTML par page
│   ├── js/  css/            # sources de l'interface
│   ├── locales/             # les 13 traductions
│   └── assets/              # logo et icônes
├── scripts/
│   └── build_frontend.py    # assemble l'interface (index.html, app.js, style.css)
├── docs/                    # documentation d'installation et Docker
├── .github/                 # politique de sécurité, publication automatique Docker Hub et GitHub
├── Dockerfile
├── docker-compose.yml       # Docker Compose
├── docker-compose.truenas.yml
├── main.py                  # lanceur local (sans Docker)
├── requirements.txt
├── CHANGELOG.md
├── CONTRIBUTING.md
└── README.md
```

`web/index.html`, `web/app.js` et `web/style.css` sont **générés** : modifiez les sources dans `web/pages`, `web/js` et `web/css`, puis lancez `python scripts/build_frontend.py`.
