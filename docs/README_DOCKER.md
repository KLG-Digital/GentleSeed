# GentleSeed — Docker / TrueNAS SCALE

**English** · [Français](README_DOCKER.fr.md)

## Minimal Docker Compose install

Copy the project to the host, then run this in the folder that contains `Dockerfile` and `docker-compose.yml`:

```bash
docker compose up -d --build
```

Or, without building, use the published image with `docker compose pull && docker compose up -d`, or:

```bash
docker run -d --name gentleseed --restart unless-stopped --stop-timeout 30 \
  -p 1853:1853 -v gentleseed_data:/data \
  starkev/gentleseed:latest
```

Open `http://SERVER-IP:1853` from a device on the network. On the first launch, choose the **language**, the **theme** and the **sign-in method** (form recommended); nothing is predefined. Then, in **Settings → Connections**, enter the Radarr/Sonarr URLs and API keys.

## Port

The default port is `1853`. To change it, create an optional `.env` file containing `WEB_PORT=1854`, or change the published port in Compose to `1854:1853`. Do not change the internal port `1853`.

## Health check

Docker requests the `/login` page every 30 seconds (`docker ps` shows "healthy" about fifteen seconds after start-up). The image has no `curl`: the check uses Python.

## Data

The **named** Docker volume `gentleseed_data` is mounted on `/data`: it persists even if the container is recreated. Back this volume up before updates (settings, sessions, API keys, history). The container runs as user `app` (UID `10001`) with a read-only filesystem, so `/data` is the only writable place besides `/tmp`.

On TrueNAS SCALE, paste the content of `docker-compose.truenas.yml` into a custom app (it uses the published image) and give `/data` a persistent volume. If it is a host path, grant write access to UID `10001` (the container user).

## Network

The simple Compose file uses the default Compose network. In the interface, enter the Radarr/Sonarr URLs that are reachable **from the container** (often `http://SERVER-IP:7878` and `http://SERVER-IP:8989`). `localhost` is GentleSeed itself inside the container, not the host. The container names `radarr` and `sonarr` only resolve on a shared Docker network: the simple Compose file does not impose an external network.

## Security and activation

Keep sign-in enabled for LAN access. Do not expose the port directly to the Internet; for remote access, use a VPN or a correctly configured HTTPS reverse proxy. **As soon as automatic monitoring is on, GentleSeed really sends releases to Radarr/Sonarr** for new media (media already present at first launch are ignored). A manual send always asks for confirmation. Radarr's and Sonarr's own RSS/automatic searches can still act independently: turn off their search on add (see the [README](../README.md)).

## Access without an account

"None" authentication only works from the local network, without a proxy, and through an IP address, a name without a dot (`truenas`) or a private name (`.local`, `.lan`, `.home`, `.internal`). This blocks "DNS rebinding", where a public web site points its own domain at your server. To use another name, list it in `WEB_ALLOWED_HOSTS` (comma separated), or switch to form sign-in.

## Current limits

From the interface, **Restart** works in Docker only when a restart policy brings the container back (`restart: unless-stopped` in the provided Compose file, `--restart unless-stopped` with `docker run`). **Stop** is not available in a container: use TrueNAS or Docker Compose to stop it.
