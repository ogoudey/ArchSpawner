# Container Spawner

A small local "PaaS": an HTTP API that builds/runs Docker containers of
configured types, opens each one on its own host port, and tracks them —
plus a terminal UI (SSH-friendly) to watch and kill them.

## Layout

```
config.py     - container type definitions (Dockerfile env vars, params, ports)
manager.py    - thread-safe registry + docker lifecycle (build/run/stop/rm)
api.py        - FastAPI server: one POST endpoint per container type
tui.py        - Textual terminal UI, polls the API
requirements.txt
```

## Setup

```bash
pip install -r requirements.txt
```

Set the Dockerfile location for each type before starting the server
(paths, not committed anywhere in code):

```bash
export TYPE1_DOCKERFILE=/path/to/type1/Dockerfile
export TYPE2_DOCKERFILE=/path/to/type2/Dockerfile

# optional: build context dir, if it's not just the Dockerfile's directory
export TYPE1_BUILD_CONTEXT=/path/to/type1
export TYPE2_BUILD_CONTEXT=/path/to/type2
```

Images are built lazily (on first spawn of that type) and cached for the
life of the process.

## Run the API

```bash
python api.py
# listens on 0.0.0.0:9000 by default (SPAWNER_API_HOST / SPAWNER_API_PORT)
```

This binds to `0.0.0.0` so it's reachable from the network, as requested.
**There's no auth built in** — put it behind a VPN, SSH tunnel, or reverse
proxy with auth before exposing it beyond a trusted LAN.

Host ports for spawned containers come from a pool, `8001`–`8999` by
default (`SPAWNER_PORT_RANGE_START` / `SPAWNER_PORT_RANGE_END`).

## API

Each type has its own endpoint with its own required/optional fields
(see `config.py` / `api.py` to adjust these once the real Dockerfiles
are in place):

```bash
# Type 1 — only "name" is required
curl -X POST localhost:9000/spawn/type1 \
  -H 'Content-Type: application/json' \
  -d '{"name": "job-a", "memory_limit": "512m"}'

# Type 2 — "name" and "dataset_id" are required
curl -X POST localhost:9000/spawn/type2 \
  -H 'Content-Type: application/json' \
  -d '{"name": "job-b", "dataset_id": "ds-42", "cpu_limit": 1.5}'
```

Response includes at least the assigned port:

```json
{
  "id": "a1b2c3d4e5",
  "port": 8001,
  "status": "running",
  "name": "job-a",
  "type": "type1",
  "container_id": "8f3a2b1c9d7e",
  "started_at": "2026-09-24 10:15:32"
}
```

Other endpoints:

| Method | Path                    | What it does                         |
|--------|-------------------------|---------------------------------------|
| GET    | `/instances`            | list all running instances            |
| GET    | `/instances?type=type1` | list instances of one type            |
| GET    | `/instances/{id}`       | get one instance                      |
| DELETE | `/instances/{id}`       | stop + remove one container           |
| DELETE | `/instances`            | kill everything                       |
| GET    | `/types`                | show each type's param schema         |
| GET    | `/health`               | liveness check                        |

Every request param is also passed into the container as an env var
(`SPAWNER_PARAM_<NAME>`), so app code inside can see what it was launched
with without extra wiring.

## Run the TUI

In a separate terminal (or a separate SSH session — it's a plain terminal
app, no browser needed):

```bash
python tui.py
# or, against a remote spawner:
SPAWNER_API_URL=http://your-host:9000 python tui.py
```

Shows a live table of every instance (id, type, name, port, status,
container id, start time), refreshing every 2s.

- `k` — kill the selected (highlighted) instance, with a confirm prompt
- `r` — refresh immediately
- `q` — quit

## Notes / next steps

- Port allocation is a simple linear scan over the configured range,
  shared across both types (a spawn call holds the manager lock while it
  picks the port, so it's race-free).
- Container status is queried live from Docker on every list/refresh
  (fine at this scale — call volume is tiny).
- To add a third type: add an entry to `CONTAINER_TYPES` in `config.py`,
  add a matching Pydantic request model + `/spawn/typeN` route in `api.py`.
