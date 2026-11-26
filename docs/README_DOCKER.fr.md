# GentleSeed — Docker / TrueNAS SCALE

[English](README_DOCKER.md) · **Français**

## Installation minimale Docker Compose

Copier le code du projet sur l'hôte puis, dans le dossier contenant `Dockerfile` et `docker-compose.yml`, lancer :

```bash
docker compose up -d --build
```

Ou, sans construire l'image, utiliser l'image publiée :

```bash
docker run -d --name gentleseed --restart unless-stopped --stop-timeout 30 \
  -p 1853:1853 -v gentleseed_data:/data \
  starkev/gentleseed:latest
```

Ouvrir `http://IP-DU-SERVEUR:1853` depuis un appareil du réseau. Au premier lancement, choisir la **langue**, le **thème** et l'**authentification** (formulaire recommandé) ; aucune valeur n'est imposée. Ensuite, dans **Paramètres → Connexions**, saisir les URL et clés API Radarr/Sonarr.

## Port

Le port par défaut est `1853`. Pour le changer, créer facultativement un fichier `.env` contenant `WEB_PORT=1854`, ou changer le port publié dans Compose en `1854:1853`. Ne pas modifier le port interne `1853`.

## Contrôle de santé

Docker interroge la page `/login` toutes les 30 secondes (`docker ps` affiche « healthy » une quinzaine de secondes après le démarrage). L'image n'a pas `curl` : le test utilise Python.

## Données

Le volume Docker **nommé** `gentleseed_data` est monté sur `/data` : il persiste même si le conteneur est recréé. Sauvegarder ce volume avant les mises à jour (paramètres, sessions, clés API, historiques). Le conteneur tourne avec l'utilisateur `app` (UID `10001`) et un système de fichiers en lecture seule : `/data` est le seul endroit inscriptible, avec `/tmp`.

Sur TrueNAS SCALE, coller le contenu de `docker-compose.truenas.yml` dans une application personnalisée (il utilise l'image publiée) et donner à `/data` un volume persistant. Si c'est un chemin hôte, donner les droits d'écriture à l'UID `10001` (l'utilisateur du conteneur).

## Réseau

Le Compose simple utilise le réseau Compose par défaut. Renseigner dans l'interface les URL Radarr/Sonarr accessibles **depuis le conteneur** (souvent `http://IP-DU-SERVEUR:7878` et `http://IP-DU-SERVEUR:8989`). `localhost` désigne GentleSeed dans le conteneur, pas l'hôte. Les noms de conteneurs `radarr` et `sonarr` ne sont résolus que sur un même réseau Docker : pas de réseau externe imposé dans le compose simple.

## Sécurité et activation

Conserver une authentification pour l'accès LAN. Ne pas exposer directement le port sur Internet ; pour un accès distant, utiliser un VPN ou un reverse proxy HTTPS correctement configuré. **Dès que la surveillance automatique est active, GentleSeed envoie réellement les releases à Radarr/Sonarr** pour les nouveaux médias (les médias déjà présents au premier lancement sont ignorés). Un envoi manuel demande toujours une confirmation. Les recherches RSS/automatiques de Radarr et Sonarr peuvent agir indépendamment : désactiver leur recherche à l'ajout (voir le [README](../README.fr.md)).

## Accès sans compte

L'authentification « Aucun » ne fonctionne que depuis le réseau local, sans proxy, et via une adresse IP, un nom sans point (`truenas`) ou un nom privé (`.local`, `.lan`, `.home`, `.internal`). Cela bloque le « DNS rebinding », où un site public fait pointer son propre domaine sur votre serveur. Pour un autre nom, l'ajouter à `WEB_ALLOWED_HOSTS` (séparés par des virgules), ou passer au mode Formulaire.

## Limites actuelles

Depuis l'interface, **Redémarrer** fonctionne dans Docker seulement si une politique de redémarrage relance le conteneur (`restart: unless-stopped` dans le Compose fourni, `--restart unless-stopped` avec `docker run`). **Arrêter** n'est pas disponible dans un conteneur : utiliser TrueNAS ou Docker Compose.
