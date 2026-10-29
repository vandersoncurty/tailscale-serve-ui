# AGENTS.md — Tailscale Serve UI

## Build / run
- Single Python file: `app.py` (Flask). Frontend is `static/` served directly by the Python server — no npm/build step.
- `docker compose up -d --build` — builds and starts.
- `docker compose up -d --force-recreate` — restart after code changes.
- `docker logs -f tailscale-serve-ui` — view logs (structured, `tailscale-serve-ui:` prefix).
- `docker compose down` — stop.

## Required runtime environment (host)
The container mounts host paths; it will fail or behave incorrectly if missing:
- `/var/run/tailscale` → host `tailscaled` socket
- `/usr/bin/tailscale` → mounted read-only at `/usr/local/bin/tailscale`
- `/var/run/docker.sock` → Docker socket for container detection

The container runs as `root`. If `tailscale serve` fails with permission errors, confirm the host user is a Tailscale operator or the container runs as root.

## Environment variables (docker-compose.yml)
Key ones that change behavior:
- `UI_USER` / `UI_PASSWORD` — HTTP Basic Auth. If `UI_PASSWORD` is empty, auth is disabled.
- `TAILSCALE_API_TOKEN`, `TAILSCALE_TAILNET`, `TAILSCALE_DEVICE_ID` — enable API-driven service creation + approval (3-step flow: create on Tailnet → run `tailscale serve` on host → approve on device). Token is never sent to the frontend.
- `TAILSCALE_API_BASE_URL` — default `https://api.tailscale.com/api/v2`.
- `SERVE_HTTPS_PORT` / `TARGET_HOST` — used in generated `tailscale serve` commands; exposed via `/api/config`.
- `PORT` — internal port; if changed, also update `ports` and `x-casaos.port_map` in compose.
- `HOST` — bind address, default `0.0.0.0`.
- `TAILSCALE_BIN` — tailscale binary path inside container, default `tailscale` (mounted at `/usr/local/bin/tailscale`).
- `DOCKER_SOCKET` — Docker socket path, default `/var/run/docker.sock`.
- `TAILSCALE_API_TIMEOUT` — API call timeout in seconds, default `10`.
Full list with defaults: `README.md` section "Variáveis de ambiente".

## Ports
Container exposes `8009`. Compose publishes `8009:8009`. If you change `PORT`, update both `ports` and `x-casaos.port_map`.

## Static assets
`app.py` serves `/`, `/index.html`, `/styles.css`, `/app.js` from `static/`. After editing frontend files, rebuild the image (`docker compose build`) — the image copies `static/`. Verify with (Basic Auth is enforced on these too, add `-u $UI_USER:$UI_PASSWORD` when set):
```
curl -u $UI_USER:$UI_PASSWORD http://127.0.0.1:8009/styles.css   # HTTP 200
curl -u $UI_USER:$UI_PASSWORD http://127.0.0.1:8009/app.js        # HTTP 200
```

## API endpoints (all require Basic Auth unless `UI_PASSWORD` empty)
- `GET /api/status` — Tailscale services status (`tailscale serve status --json`)
- `GET /api/containers` — Docker containers with `registered` boolean
- `GET /api/config` — public config (`serveHttpsPort`, `targetHost`)
- `GET /api/tailscale/config` — API configured flag, tailnet, device id
- `GET /api/health` — health check
- `POST /api/serve` — run `tailscale serve` on host
- `POST /api/clear` — remove a service
- `GET /api/tailscale/services` — list tailnet services (Tailscale API)
- `GET/PUT/DELETE /api/tailscale/services/<name>` — get/create-or-update/delete a tailnet service (PUT requires `tag` in body)
- `GET /api/tailscale/services/<name>/devices` — devices for a service
- `GET/POST /api/tailscale/services/<name>/device/<device_id>/approved` — device approval status / approve or revoke
- `POST /api/tailscale/services/<name>/provision` — 3-step create/serve/approve via Tailscale API
- `POST /api/tailscale/services/<name>/provision-step` — single-step provision (step 1 only)

## Service names
- Validated against `^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$` — lowercase, numbers, hyphens, 1–63 chars.
- Stored/referred to with the `svc:` prefix in `tailscale serve` and API calls.
- Container detection normalizes names from container names; editable before exposing.

## Key gotchas
- `docker-compose.yml.bak` exists in root — ignore it, it's a stale backup.
- `__pycache__/` exists — ignored by git.
- Tailscale API tag must be pre-approved in the Tailnet admin console (Access controls > Tags), or creation fails with "tags are invalid or not permitted".
- `TAILSCALE_TAILNET` value `-` means the default tailnet of the token.
- Basic Auth is enforced on static assets too; `fetch` from the browser will prompt for credentials.
- No test suite, linter, or typechecker is configured. Verify manually with `curl` against the running container.

## Troubleshooting
- `tailscale: command not found` — check `TAILSCALE_BIN` and that `/usr/bin/tailscale` is mounted on the host.
- `tailscale serve` permission errors — container runs as `root`; confirm host user is a Tailscale operator or container runs as root.
- Interface shows Tailscale unavailable — confirm `tailscaled` is running and `/var/run/tailscale` mounted; if the container started before `tailscaled`, run `docker restart tailscale-serve-ui`.
- Docker containers not listed — confirm `/var/run/docker.sock` is mounted; UI still works with manual name/port entry.
- Registered containers always hidden in the list — `static/app.js` had a duplicate `loadContainers` that ignored the "Exibir todos" checkbox; remove the second definition (kept the one that reads `showAllEl.checked`).

## Security
The container has access to the host `tailscaled` socket and Docker socket — treat as root-level access. Do not expose port `8009` publicly without `UI_USER`/`UI_PASSWORD`. Prefer LAN/tailnet access.