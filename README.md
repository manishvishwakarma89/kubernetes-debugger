# Docker & Kubernetes Debugger

One FastAPI application and browser dashboard for Docker diagnostics and offline Kubernetes manifest validation. Existing Docker API paths are preserved. One `DEBUGGER_API_TOKEN` protects all diagnostic APIs.

## Included

- Docker container listing, image listing, logs, sanitized inspect, and metrics.
- Docker Scout background scan jobs with automatic dashboard polling and JSON downloads.
- Kubernetes YAML parsing, versioned schema validation, selector checks, configuration warnings, and suggested fixes.
- Manifest CLI, examples, tests, Dockerfile, and GitHub Actions test/manual deployment workflows.

Pipeline error analysis, general log analysis, automatic remediation, and live cluster checks are future work. Container logs are retrieved as text; they are not automatically analyzed.

## Start locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DEBUGGER_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uvicorn main:app --host 127.0.0.1 --port 8080
```

Open http://localhost:8080 and enter the configured token. `/docs` lists both APIs. In Swagger Authorize, enter only the token; direct HTTP clients send `Authorization: Bearer TOKEN`. No `.env` is loaded automatically. To use a private environment file with Docker, pass `--env-file /absolute/path/private.env`. Never commit it.

Local Python execution needs Docker CLI and the Scout plugin installed separately for scans. The supplied Dockerfile installs both. Kubernetes validation requires neither Docker Engine nor kubectl.

## Elastic Beanstalk

1. Upload the source ZIP directly: Dockerfile is at its root.
2. Use a Docker environment, application port 8080, and health check `/healthz`.
3. Configure `DEBUGGER_API_TOKEN` with at least 32 random characters in environment properties. Use the same token in the dashboard. Use HTTPS for public access.
4. For Docker Hub Scout access, configure `DOCKER_SCOUT_HUB_USER` and `DOCKER_SCOUT_HUB_PASSWORD` (Docker Hub access token). Private registry credentials use `DOCKER_SCOUT_REGISTRY_USER` and `DOCKER_SCOUT_REGISTRY_PASSWORD`. These are separate from the debugger API token.
5. Choose Registry for published images such as `nginx:latest` or `manishvishwa801/mongo:latest`. Choose Local only when a connected Docker Engine contains that image.

Run one instance and one Uvicorn process: scan job records are in memory, expire after 30 minutes, and disappear on restart. Multiple instances need a shared queue/store before scaling. A scan has a 300-second execution limit and only one scan may run at once.

Docker container APIs and local scans require a separately configured Docker daemon. Hosting this API does not itself grant access to the host Docker socket. Remote connections require mutual TLS using `DOCKER_HOST`, `DOCKER_TLS_VERIFY=1`, and `DOCKER_CERT_PATH`; see DOCKER_GUIDE.md. `/healthz` checks the API process, not Docker connectivity.

## API paths

| Feature | Method and path |
| --- | --- |
| Dashboard / health | GET `/`, GET `/healthz` |
| Container / image listing | GET `/containers`, GET `/images` |
| Logs / inspect / metrics | GET `/containers/{name}/logs`, `/inspect`, `/metrics` |
| Start scan | POST `/images/scout?image_name=nginx:latest&source=registry` (202) |
| Poll scan | GET `/images/scout/jobs/{job_id}` |
| Schema versions | GET `/versions` |
| Validate YAML | POST `/validate` with JSON `manifest` and optional `kubernetes_version` |

A completed validation HTTP request returns 200 even when its report says `outcome: invalid`; check the report. The older `/images/scout/sync` compatibility endpoint remains available but can exceed gateway timeouts; use background scans.

## CI/CD and validation

GitHub Actions runs tests, a valid manifest example, and Docker build on push/PR. AWS deployment is manual and needs OIDC role/environment configuration documented in KUBERNETES_GUIDE.md. Deployment uploads replace the selected EB application's version; configure it deliberately. The workflow does not create infrastructure.

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
python cli.py examples/valid.yaml --report reports/manifest.json
docker build -t integrated-debugger .
docker run --rm --env-file /absolute/path/private.env -p 8080:8080 integrated-debugger
```

Detailed module behavior and limitations: KUBERNETES_GUIDE.md and DOCKER_GUIDE.md. Their standalone packaging instructions are superseded by this README.

Verification: automated tests use real offline Kubernetes schemas and simulated Docker/Scout backends. Docker image build, live registry scans, browser visual inspection, and AWS deployment have not been verified in this environment.
