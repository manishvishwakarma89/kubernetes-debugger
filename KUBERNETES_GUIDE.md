# Day 4 — Kubernetes Manifest Debugger

A standalone Python/FastAPI project using the same authentication and Docker/Beanstalk deployment pattern as Day 3. It is a new application, not a replacement for your Docker Debugger. No Docker daemon or Kubernetes cluster connection is needed for its offline checks.

## What is included

| Planned feature | This version |
| --- | --- |
| Manifest validation and error detection | Safe YAML parsing; strict built-in schemas for selectable Kubernetes versions 1.32–1.36; selector/template matching; duplicate resource checks |
| Remediation suggestions | Rule-based advice for each finding; no automatic YAML changes |
| Security/configuration advice | Floating tags, missing resource budgets/readiness probes, privileged mode, and missing non-root requirement |
| Browser interface and API | Paste/open YAML, version selection, authenticated validation and JSON download; Swagger at /docs |
| CI/CD automation | GitHub Actions tests, sample validation and Docker build; a separate manually triggered AWS deployment workflow |
| Elastic Beanstalk deployment | Root Dockerfile source bundle and instructions; deployment itself is not performed |
| CI/CD pipeline error analysis | Deferred; no arbitrary workflow-log diagnosis in this version |
| Docker/build troubleshooting | Your existing Day 3 project; not reimplemented here |
| General log/error analysis | Deferred |
| Live Kubernetes/admission checks and custom CRD schemas | Not included; unknown/custom resource schemas are reported as incomplete |

Only the first schema violation per resource is reported by the schema library. Suggestions are rules, not LLM-generated diagnoses. Schema validity is not a guarantee that a cluster will accept or successfully run the workload. Runtime image availability, admission policies, networking, cross-resource dependencies, quantity semantics and operational behavior need separate verification. “Valid” can still contain warnings. The CLI fails on invalid or incomplete coverage, with an option to fail on warnings too.

## Run locally

From this extracted folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Set `DEBUGGER_API_TOKEN` to that newly generated value in your terminal (do not paste credentials into a repository). Then run:

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8082 --no-access-log
```

Open http://localhost:8082/ and enter the token. Load the example to see a selector mismatch and configuration warnings. You may also open examples/valid.yaml. /docs has an Authorize button: paste the token without `Bearer` and use POST /validate. The app does not automatically load a .env file.

## Command-line and CI checks

```bash
python cli.py examples/valid.yaml --report reports/manifest-report.json
python cli.py examples/invalid.yaml
python cli.py path/to/manifest.yaml --kubernetes-version 1.34.0 --fail-on-warnings
```

Exit codes: 0 = included checks passed; 1 = invalid/incomplete (or warnings when requested); 2 = input/configuration failure. Offline CLI use needs no API token.

## Docker

```bash
docker build -t kubernetes-manifest-debugger .
docker run --rm -p 8082:8080 --env-file /absolute/path/to/your-private.env kubernetes-manifest-debugger
```

The env file must contain DEBUGGER_API_TOKEN with your generated value. Keep it outside this project. Container port is 8080. The image runs as user 10001 and contains a /healthz check. No Docker socket, Kubernetes credentials or Docker Hub credentials are needed to validate YAML.

## Elastic Beanstalk

1. Use a separate environment for this new project if you want to keep the Docker Debugger running.
2. Choose a Docker platform and upload the supplied ZIP directly. Dockerfile is at ZIP root; do not wrap the files in a parent directory.
3. Set Environment property DEBUGGER_API_TOKEN to a new random token of at least 32 characters. It is not included in the ZIP.
4. Container/service port: 8080. Health path: /healthz.
5. After launch, open the environment domain, enter the token and validate examples/valid.yaml. A /healthz response verifies the web process, not actual cluster behavior.
6. Configure HTTPS before transmitting tokens or sensitive manifests over a public endpoint. This package does not provision HTTPS, AWS resources or a cluster.

## GitHub Actions

Put the project contents at your repository root. `.github/workflows/validate.yml` runs on push, pull request and manual dispatch. It tests the application, validates examples/valid.yaml, builds Docker, and uploads a redacted JSON report. Replace the sample CLI path with the manifest you want to gate. This is a workflow scaffold; it has not been run on your GitHub account.

For AWS deployment, configure the `aws-deployment` GitHub environment:

| Setting | Type | Purpose |
| --- | --- | --- |
| AWS_REGION | Variable | Region containing the Beanstalk environment and source bucket |
| EB_APPLICATION | Variable | Existing Beanstalk application name |
| EB_ENVIRONMENT | Variable | Existing environment name |
| EB_SOURCE_BUCKET | Variable | Existing S3 source bundle bucket in that region |
| AWS_ROLE_ARN | Secret | IAM role assumable using GitHub OIDC |

Restrict the role trust policy to your repository and the aws-deployment environment, and restrict permissions to the required S3 and Beanstalk resources. Configure environment approval protection if desired. The workflow runs only when manually dispatched on main, and it does not create the AWS environment. It waits for the update and prints status; confirm environment health and /healthz afterward. Runtime DEBUGGER_API_TOKEN stays in Beanstalk, not this workflow. No AWS credentials are embedded in source.

## Privacy and input limits

Manifests are processed in memory and are not written to server disk. Reports do not include manifest values or YAML error snippets. Browser tokens are held only in the password field and are not persisted in local/session storage. Downloaded reports contain issue paths and advice, so review them before sharing. Access logging is disabled in the provided startup command; infrastructure logs remain under your configuration.

Limits: 512 KiB manifest, 1 MiB JSON request, 100 resources, 40 YAML nesting levels, 30,000 YAML nodes and four concurrent validation requests per process. Aliases and duplicate mapping keys are rejected to avoid ambiguous or unbounded parsing. YAML templates such as Helm input must be rendered before validation. Resources in a Kubernetes List are validated individually. Multiple workers/instances scale validation independently because there is no server-side job history.

## Validation performed

27 automated tests passed with actual installed schema packages: all five versions, valid/invalid schema examples, selectors, custom-resource incompleteness, multi-resource/List input, duplicates, YAML injection/aliases/depth/size, secret-value redaction, API authentication/capacity/body limits, Swagger request schema and CLI reports/exit codes. These are local offline checks, not simulated cluster acceptance.

A Docker container build, visual browser interaction, GitHub Actions run and AWS deployment were not performed here. The environment has no Docker CLI. No deployment is claimed. Direct Python dependency versions are pinned; transitive dependencies are not a complete lock file.

Schema library: https://github.com/willthames/kubernetes-validate
Kubernetes Deployment documentation: https://kubernetes.io/docs/concepts/workloads/controllers/deployment/
