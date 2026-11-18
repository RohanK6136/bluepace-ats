# DevOps Starter Lab

A deliberately small, isolated full-stack operations demo for learning Linux/server operations, Docker Compose, Nginx, health checks, CI, and troubleshooting.

> This is a learning lab. It does not change the BluePace ATS application, deployment configuration, secrets, or production services.

## Architecture

```text
Browser
  |
  | http://localhost:8080
  v
Nginx reverse proxy (web)
  |
  | /api/* proxy
  v
Node.js API (api) ---- /health
  |
  +-- process/container logs via Docker

GitHub Actions
  |
  +-- install dependencies
  +-- run tests
  +-- build Docker image
```

The web container serves a static dashboard and proxies `/api/` to the API container over the private Compose network. Only Nginx publishes a host port. The API is not exposed directly.

## Prerequisites

- Docker Engine with the Compose plugin (or Docker Desktop)
- Git
- A terminal

## Run locally

From this directory:

```bash
docker compose up --build -d
docker compose ps
curl -i http://localhost:8080/health
curl -i http://localhost:8080/api/health
```

Open http://localhost:8080.

Stop and remove the containers:

```bash
docker compose down
```

## Operations exercises

### 1. Inspect services and logs

```bash
docker compose ps
docker compose logs --tail=100
docker compose logs -f api
```

### 2. Restart a service

```bash
docker compose restart api
curl -fsS http://localhost:8080/api/health
```

### 3. Simulate and recover from a failure

Stop the API:

```bash
docker compose stop api
```

Observe the effect:

```bash
curl -i http://localhost:8080/api/health
docker compose ps
docker compose logs --tail=100 api
```

Recover:

```bash
docker compose start api
docker compose ps
curl -fsS http://localhost:8080/api/health
```

### 4. Inspect resource use

```bash
docker stats
docker system df
```

### 5. Validate configuration

```bash
docker compose config
docker compose ps
```

## Useful endpoints

| Endpoint | Purpose |
|---|---|
| `/` | Demo operations dashboard |
| `/health` | Nginx/web process health |
| `/api/health` | API health through reverse proxy |
| `/api/info` | API and runtime metadata |

## What this demonstrates

- Containerising a Node.js API and web tier.
- Running multiple services with Docker Compose.
- Private service-to-service networking.
- Nginx reverse proxying.
- Container health checks and restart policy.
- Centralised inspection of service logs.
- A CI workflow that tests the API and builds the image.
- Failure injection and recovery using a controlled local environment.

## Security notes

- No production credentials or secrets are required.
- The API is not published directly to the host.
- The demo uses a non-root Node.js user in its container.
- The app binds to the internal container interface; Nginx is the public entry point.
- Do not expose this learning stack to the internet without a proper firewall, TLS, secret management, updates, and review.

## Next stages

1. Run this locally and capture the health endpoints, service list, logs, and recovery exercise.
2. Practise the same commands on an Ubuntu VM over SSH.
3. Add HTTPS with a locally trusted development certificate, then a real domain/certificate only on a controlled environment.
4. Add image publishing and a deployment workflow after reviewing secrets and deployment permissions.
5. Add Prometheus and Grafana, then define an SLI/SLO and an alert.
6. Add Terraform only after the manual infrastructure and networking are understood.

## Troubleshooting

- Docker daemon not running: start Docker Desktop or the Docker service.
- Port 8080 already in use: change the left side of `ports` in `docker-compose.yml`.
- API not healthy: inspect `docker compose logs api`.
- Nginx cannot reach API: confirm both services are in the Compose file and the upstream is named `api`.
