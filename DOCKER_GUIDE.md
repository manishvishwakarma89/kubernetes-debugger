# Simple Docker Debugger

Two Python classes:
- main.py: DockerDebuggerApp creates FastAPI and registers endpoints with @app.get decorators.
- docker_debugger.py: DockerDebugger contains Docker diagnostic methods.

## Run locally with Python
Install Python and Docker, then run from this folder:

```bash
python -m pip install -r requirements.txt
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Set DEBUGGER_API_TOKEN to the generated value in your shell. On Linux/macOS, use `export DEBUGGER_API_TOKEN='YOUR_GENERATED_TOKEN'`; in PowerShell, use `$env:DEBUGGER_API_TOKEN='YOUR_GENERATED_TOKEN'`.

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8081
```

Open http://localhost:8081/docs, click Authorize, enter the token (without the word Bearer), and use Try it out on an endpoint. Port 8081 avoids conflicting with TWS Labs on port 8080. The Swagger interface needs internet access to load its default assets.

Docker must be running and your Python process must have access to it. The SDK defaults to the local Docker socket. Docker Desktop, rootless Docker or Windows can need additional connection configuration; this app supports Unix sockets and TLS-protected remote TCP hosts, not Windows named pipes. Use WSL with a reachable Unix socket or configure a TLS host.

## Methods
- list_containers: running and stopped containers
- list_images: images and tags
- get_logs: recent stdout/stderr logs
- inspect_container: selected diagnostic fields (excludes environment secrets)
- get_metrics: CPU and memory snapshot for a running container
- close: release the Docker connection

Diagnostic methods and POST /images/scout are included. Image build, start/stop and Trivy scans from the original script are not implemented. This version has no custom dashboard, shared log files or automatic container changes. Returned application logs may still contain sensitive data.

## Docker and Elastic Beanstalk
The ZIP has Dockerfile at its root. Container/service port: 8080. Health check: /healthz. Set DEBUGGER_API_TOKEN before using diagnostic endpoints. Configure HTTPS before entering tokens on a public application endpoint.

The web container needs an explicitly configured Docker connection. Its deployment alone does not provide access to Docker on your computer or on Beanstalk nodes. A healthy /healthz confirms only that the web process runs.

For a remote host, configure DOCKER_HOST=tcp://YOUR_PRIVATE_HOST:2376, DOCKER_TLS_VERIFY=1, DOCKER_CERT_PATH=/run/docker-certs. Supply ca.pem, cert.pem and key.pem securely at runtime. The host needs mutual TLS configured independently and private network access from the web application. No certificates, host or infrastructure are provisioned by this package.

For a local container, mounting a Docker socket requires matching its group permissions to the app's non-root user. Access to that socket grants extensive host control; use a host you own and never give the socket to shared learner terminals. Do not expose an unauthenticated Docker TCP daemon.

## Validation
API tests use a fake Docker connection. Live Docker, container image build and AWS deployment need separate verification. Dependency ranges are not a production lock file.

## Scout deployment fix

The Dockerfile now installs Docker CLI from Docker's Debian repository and Scout
1.26.0 from a release archive verified against Docker's SHA-256 checksum file.
It checks `docker --version` and `docker scout version` as the non-root app user
during the image build. The Scout cache is writable by that user.

Upload this ZIP with Upload and deploy. Keep port 8080 and the existing
DEBUGGER_API_TOKEN. Configure these runtime environment properties for Scout:

| Name | Value |
| --- | --- |
| DOCKER_SCOUT_HUB_USER | Your Docker Hub username |
| DOCKER_SCOUT_HUB_PASSWORD | Your Docker Hub personal access token |

Supply secrets at runtime; do not put them in this ZIP or in the Dockerfile.
Scout credentials differ from DEBUGGER_API_TOKEN, which protects the web API.
No Docker login is needed during the image build.

POST /images/scout accepts source=local or source=registry. The default is now
registry for cloud deployments. In /docs, click Try it out and use registry
to scan a published image without connecting Docker Engine:

- image_name: nginx:latest (public example), or your-user/your-image:tag
- source: registry

Requests that omit source now use registry. This changes the previous local
default: callers needing local scans must explicitly send source=local.
Short local image IDs in registry mode return HTTP 400 with instructions.
The optional synchronous route /images/scout/sync returns HTTP 502 for Scout
execution failures and HTTP 200 for completed scans, including reports that
find vulnerabilities. The main scan endpoint uses background jobs as below.
The API cannot translate a local image ID into a published repository/tag.

Registry scans download from the registry and require outbound network access
and Scout credentials. For private registries, configure
DOCKER_SCOUT_REGISTRY_USER and DOCKER_SCOUT_REGISTRY_PASSWORD as runtime secrets,
or provide the appropriate runtime Docker credential configuration. Local
image IDs such as 5e2309035332 are rejected for registry scans. Publish your
image separately first if it currently exists only on your computer.

source=local scans an image on the Docker daemon reachable by the deployed
application. A short image ID from your laptop will not resolve on an unrelated
Beanstalk host. Use /images to find references on the configured daemon. For a
remote daemon, configure the TLS connection and certificates described above.
Installing CLI and Scout does not connect a daemon or mount a socket. The
non-root user needs appropriate socket group permissions if you choose a local
Unix socket. /containers and /images still require Docker daemon connectivity;
registry scanning does not enable those endpoints.

The package structure and source syntax were checked. A local container build,
live Scout scan and AWS deployment were not performed in the preparation
environment because it does not have Docker CLI/Engine.

## Background scans: gateway timeout fix

POST /images/scout now returns HTTP 202 immediately with job_id and status_url.
In /docs, start the scan using a published image name and source=registry. Copy
the job_id into GET /images/scout/jobs/{job_id} and Execute every few seconds.
The authenticated status response reports queued, running, succeeded, failed or
timed_out. A successful status lookup does not imply a successful scan: read
state and result.status. The final result contains the Scout report or error.

Only one scan runs at a time; another submission returns HTTP 429. The scanner
is stopped after 300 seconds. At most 20 results are retained for 30 minutes.
Jobs are in-memory and disappear on restart or deployment. This package runs
one Uvicorn process; use a single instance for this job implementation. Multiple
instances require a shared queue/store and are not supported by this job manager.
Running scans have no cancellation endpoint and are bounded by the timeout.

Do not increase instance sizes without checking logs: the prior Mongo indexing
exit code 255 has not been diagnosed. Background jobs address HTTP gateway wait
timeouts, not memory, disk, credentials, networking or scanner failures.
