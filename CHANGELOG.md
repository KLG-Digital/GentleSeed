# v1.0.0 — First stable release

GentleSeed compares the releases found by Radarr/Sonarr (eligibility, seeders, codec) and hands the best one back to Radarr/Sonarr, which pass it to their download client. It never contacts the download client itself.

## Selection engine

- Only releases accepted by Radarr/Sonarr are eligible, with a minimum number of seeders and a preferred video codec. Rejection reasons are explained in the log.
- Series: season packs are searched first, then episodes one by one. Anime season searches use Sonarr v5.
- Optional: same release team from one season to the next (a preference, never a filter).
- Indexers to ignore, per service. A release from an ignored indexer is never chosen.
- Releases refused only for their language can be sent after confirmation, or automatically after a number of empty searches (off by default).
- Only media added after activation are processed; new additions go before the backlog.
- Anti-duplicate: the history and queue are checked before every send, and when in doubt GentleSeed does not send.
- Dedicated timeouts for slow searches (240 s for a season, 120 s for a movie or an episode); media that time out are retried later.

## Interface

- Dashboard, Search, In progress, Logs, Settings and System pages, desktop and mobile, with dark, light and team-color themes.
- Download tracking for 48 hours in the Radarr/Sonarr queue and history: progress, import, failure, removal from the queue, indexer of origin. Choose the columns to show.
- Searches run in the background with their current step and elapsed time, so proxies do not cut them.
- Manual sends always ask for confirmation; unsaved settings are protected.
- Colored log preview, localized dates and times, translated downloads of the log files.

## Radarr and Sonarr integration

- GentleSeed installs itself as a webhook in Radarr and Sonarr, as Prowlarr does, with test and removal per service. The webhook only triggers a check.
- "URL Base" addresses are supported.

## System

- Health of Radarr and Sonarr, scheduled tasks, log files, debug level.
- Backups of the settings (API keys only on request; never the password or tokens), with safety copies before a restore.
- Update notice read from GitHub releases (can be disabled). GentleSeed never updates itself.

## Security

- Form sign-in, or no account from the local network only (no proxy header, and only through an IP address or a private host name).
- CSRF token and origin check on every action, sign-in attempts limited, secrets written with owner-only rights.
- Container runs without administrator rights, with a read-only filesystem.

## Languages

- English (default) and 13 translations: French, German, Spanish, Italian, Portuguese (Portugal and Brazil), Dutch, Polish, Russian, Ukrainian, Japanese, Korean and Simplified Chinese. Logs are written in English on disk and translated when displayed or downloaded.

## Running it

- Docker image `starkev/gentleseed`, Docker Compose, TrueNAS SCALE, or `python main.py`. Default port 1853.
