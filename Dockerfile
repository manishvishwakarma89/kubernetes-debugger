FROM python:3.12-slim-bookworm
ARG SCOUT_VERSION=1.26.0
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Install the client only. The Docker daemon must be supplied separately.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL --retry 3 https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable\n' "$(dpkg --print-architecture)" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# Verify the release archive against Docker's published SHA-256 checksums.
RUN set -eu; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in amd64|arm64) ;; *) echo "Unsupported Scout architecture: $arch" >&2; exit 1 ;; esac; \
    archive="docker-scout_${SCOUT_VERSION}_linux_${arch}.tar.gz"; \
    base="https://github.com/docker/scout-cli/releases/download/v${SCOUT_VERSION}"; \
    mkdir -p /tmp/scout /usr/local/lib/docker/cli-plugins; \
    cd /tmp/scout; \
    curl -fsSL --retry 3 "$base/$archive" -o "$archive"; \
    curl -fsSL --retry 3 "$base/docker-scout_${SCOUT_VERSION}_checksums.txt" -o checksums.txt; \
    awk -v name="$archive" '$2 == name { print; found=1 } END { if (!found) exit 1 }' checksums.txt > selected-checksum.txt; \
    sha256sum -c selected-checksum.txt; \
    tar -xzf "$archive" docker-scout; \
    install -m 0755 docker-scout /usr/local/lib/docker/cli-plugins/docker-scout; \
    rm -rf /tmp/scout

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home appuser
COPY main.py auth.py kubernetes_api.py validator.py cli.py docker_debugger.py scout_jobs.py ./
COPY static ./static
ENV DOCKER_SCOUT_CACHE_DIR=/home/appuser/.cache/docker-scout
RUN mkdir -p /home/appuser/.cache/docker-scout /home/appuser/.docker \
    && chown -R appuser:appuser /home/appuser
USER appuser
# Fail the image build if either executable is unavailable to the runtime user.
RUN docker --version && docker scout version
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
