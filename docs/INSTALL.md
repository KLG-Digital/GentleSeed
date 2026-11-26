# GentleSeed — Installation guide

**English** · [Français](INSTALL.fr.md)

## Requirements

- **Docker** with Docker Compose, **or** Python 3.12+
- **Radarr and/or Sonarr** reachable from GentleSeed, with their API keys
- **Port**: `1853` by default (`WEB_PORT` to change it)

## Installation & Usage

### Option 1 — Docker Compose (recommended)

1. **Clone** the repository (or download it) and open the folder
2. **Start** GentleSeed:
   ```bash
   docker compose up -d --build
   ```
3. **Open** `http://SERVER-IP:1853` and follow the first-launch page (theme and sign-in)
4. In **Settings → Connections**, enter the address and API key of Radarr and/or Sonarr

> On TrueNAS SCALE, paste `docker-compose.truenas.yml` into a custom app (published image, nothing to build). More details in [README_DOCKER.md](README_DOCKER.md).

### Option 2 — Docker image

```bash
docker run -d --name gentleseed --restart unless-stopped --stop-timeout 30 \
  -p 1853:1853 -v gentleseed_data:/data \
  starkev/gentleseed:latest
```

Image on [Docker Hub](https://hub.docker.com/r/starkev/gentleseed). The `gentleseed_data` volume keeps your settings, account and logs.

### Option 3 — Without Docker (Python)

```bash
pip install -r requirements.txt
python main.py          # listens on 127.0.0.1:1853
```

Set the `WEB_HOST=0.0.0.0` environment variable to reach it from the network. Your data is stored in `data/`.

## Avoid double downloads (important)

When a movie or series is added, Radarr/Sonarr (or Seerr/Overseerr) start **their own search** by default. To let GentleSeed be the only one choosing, **untick the automatic search on add**:

| Application | Where | Option to untick |
|---|---|---|
| **Radarr** | "Add Movie" window | *Start search for missing movie* |
| **Sonarr** | "Add Series" window | *Start search for missing episodes* (and the cutoff-unmet one) |
| **Import lists** (Radarr/Sonarr) | Settings → Lists | *Search on Add* |
| **Seerr / Overseerr** | Settings → Services → Radarr/Sonarr server | *Enable Automatic Search* |

Then open **Settings → Integration** in GentleSeed and click **Install** and **Test** for each service. If you cannot untick the option, set *Delay before analyzing a new media* to 30 s in the advanced settings: GentleSeed then waits for Radarr/Sonarr and checks their history before sending anything.

## Security

- Keep **form sign-in** enabled. The "None" mode is only accepted from the local network, never through a proxy.
- Do not expose the port directly on the Internet; use a VPN or a correctly configured HTTPS reverse proxy.
- The container runs without administrator rights, with a read-only file system and a health check.
- API keys are never displayed again once saved, and are not included in backups unless you ask for it.

To report a vulnerability, see the [security policy](../.github/SECURITY.md).

## Notes

- **GentleSeed starts watching as soon as automatic monitoring is on** (Settings → General): the releases are really sent to Radarr/Sonarr. A manual send always asks for confirmation.
- **Data** (`settings.json`, `state.json`, logs, account) lives in `/data` (Docker) or `data/` (without Docker). Never publish this folder.
- **Home-screen icon** (iPhone/Android): delete and re-add the shortcut after an update, as iOS keeps the old icon in cache.
- **Restart** is available from the user menu; **Stop** only without Docker (the container restarts by itself).

## Project Structure

```
GentleSeed/
├── backend/                 # Python code (FastAPI)
│   ├── engine/              # release choice, activity, follow-up
│   ├── routes/              # API routes, by theme
│   └── services/            # *arr integration, backups, updates
├── web/                     # interface (HTML, CSS, JavaScript)
│   ├── pages/               # one HTML section per page
│   ├── js/  css/            # sources of the interface
│   ├── locales/             # the 13 translations
│   └── assets/              # logo and icons
├── scripts/
│   └── build_frontend.py    # assembles the interface (index.html, app.js, style.css)
├── docs/                    # installation and Docker documentation
├── .github/                 # security policy, automatic Docker Hub and GitHub publication
├── Dockerfile
├── docker-compose.yml       # Docker Compose
├── docker-compose.truenas.yml
├── main.py                  # local launcher (without Docker)
├── requirements.txt
├── CHANGELOG.md
├── CONTRIBUTING.md
└── README.md
```

`web/index.html`, `web/app.js` and `web/style.css` are **generated**: edit the sources in `web/pages`, `web/js` and `web/css`, then run `python scripts/build_frontend.py`.
