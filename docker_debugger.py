"""Docker operations live in one class; no containers are changed automatically."""
import os
import re
import shutil
import signal
import subprocess
import threading
from pathlib import Path

import docker


_SCOUT_SLOT = threading.BoundedSemaphore(1)


class DockerDebugger:
    def __init__(self):
        host = os.getenv("DOCKER_HOST", "unix:///var/run/docker.sock")
        if host.startswith("tcp://"):
            if os.getenv("DOCKER_TLS_VERIFY") != "1":
                raise ValueError("Remote Docker requires DOCKER_TLS_VERIFY=1.")
            folder = Path(os.getenv("DOCKER_CERT_PATH", "/run/docker-certs"))
            if not all((folder / name).is_file() for name in ("ca.pem", "cert.pem", "key.pem")):
                raise ValueError("Provide ca.pem, cert.pem and key.pem in DOCKER_CERT_PATH.")
        elif not host.startswith("unix://"):
            raise ValueError("Use a Unix socket locally or a remote Docker host with TLS.")
        # Docker SDK uses DOCKER_HOST, DOCKER_TLS_VERIFY and DOCKER_CERT_PATH.
        self.client = docker.from_env(timeout=15)

    def close(self):
        self.client.close()

    def _container(self, name):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name):
            raise ValueError("Invalid container name or ID.")
        return self.client.containers.get(name)

    def list_containers(self):
        return [
            {"id": item.short_id, "name": item.name, "status": item.status}
            for item in self.client.containers.list(all=True, limit=100)
        ]

    def list_images(self):
        return [
            {"id": item.short_id, "tags": item.tags}
            for item in self.client.images.list()
        ][:100]

    def get_logs(self, name, tail=200):
        output = self._container(name).logs(tail=tail, timestamps=True)
        return {
            "logs": output[-262144:].decode("utf-8", errors="replace"),
            "truncated": len(output) > 262144,
        }

    def inspect_container(self, name):
        details = self._container(name).attrs
        state = details.get("State", {})
        # Omit environment variables, mount paths and command arguments.
        return {
            "id": details.get("Id"),
            "name": details.get("Name"),
            "image": details.get("Config", {}).get("Image"),
            "state": {key: state.get(key) for key in ("Status", "Running", "ExitCode", "OOMKilled")},
        }

    def get_metrics(self, name):
        container = self._container(name)
        if container.status != "running":
            raise ValueError("Metrics require a running container.")
        stats = container.stats(stream=False)
        cpu = stats.get("cpu_stats", {})
        previous = stats.get("precpu_stats", {})
        cpu_usage = cpu.get("cpu_usage", {})
        previous_usage = previous.get("cpu_usage", {})
        cpu_delta = cpu_usage.get("total_usage", 0) - previous_usage.get("total_usage", 0)
        system_delta = cpu.get("system_cpu_usage", 0) - previous.get("system_cpu_usage", 0)
        cores = cpu.get("online_cpus") or len(cpu_usage.get("percpu_usage") or [])
        cpu_percent = None
        if previous_usage and system_delta > 0 and cpu_delta >= 0 and cores:
            cpu_percent = round(cpu_delta / system_delta * cores * 100, 2)

        memory = stats.get("memory_stats", {})
        usage = memory.get("usage")
        limit = memory.get("limit")
        cache = memory.get("stats", {})
        inactive = cache.get("total_inactive_file", cache.get("inactive_file", 0))
        # Match Linux docker stats: exclude inactive file cache when valid.
        used = usage - inactive if usage is not None and 0 <= inactive < usage else usage
        return {
            "container": container.name,
            "cpu_percent": cpu_percent,
            "memory_mb": round(used / 1_000_000, 2) if used is not None else None,
            "memory_limit_mb": round(limit / 1_000_000, 2) if limit is not None else None,
            "memory_percent": round(used / limit * 100, 2) if used is not None and limit else None,
        }

    @staticmethod
    def validate_scout_input(image_name, source="registry"):
        # Accept image references, not filesystem/OCI/archive source paths or flags.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}", image_name) or "://" in image_name:
            raise ValueError("Enter a Docker image name, tag or digest, such as nginx:latest.")
        if source not in ("local", "registry"):
            raise ValueError("Choose local or registry as the image source.")
        if source == "registry" and re.fullmatch(r"(?:sha256:)?[a-fA-F0-9]{12,64}", image_name):
            raise ValueError("Enter a published image name such as nginx:latest or your-user/your-image:tag. A local image ID requires source=local and a connected Docker daemon.")

    @staticmethod
    def scout_scan(image_name, source="registry"):
        """Scan an image; bound output and stop the process after five minutes."""
        DockerDebugger.validate_scout_input(image_name, source)
        executable = shutil.which("docker")
        if not executable:
            raise FileNotFoundError("Docker CLI is missing. Install Docker CLI and the Scout plugin where FastAPI runs.")
        if not _SCOUT_SLOT.acquire(blocking=False):
            raise BlockingIOError("A Scout scan is already running. Try again after it finishes.")
        process = None
        try:
            environment = os.environ.copy()
            environment.pop("DEBUGGER_API_TOKEN", None)
            environment["NO_COLOR"] = "1"
            command = [executable, "scout", "cves", "--exit-code", source + "://" + image_name]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       env=environment, start_new_session=(os.name == "posix"))
            buffers = {"stdout": bytearray(), "stderr": bytearray()}
            truncated = [False]
            def read_output(pipe, key):
                with pipe:
                    while True:
                        chunk = pipe.read(8192)
                        if not chunk:
                            break
                        remaining = 262144 - len(buffers[key])
                        buffers[key].extend(chunk[:max(remaining, 0)])
                        if len(chunk) > remaining:
                            truncated[0] = True
            readers = [threading.Thread(target=read_output, args=(process.stdout, "stdout"), daemon=True),
                       threading.Thread(target=read_output, args=(process.stderr, "stderr"), daemon=True)]
            for reader in readers:
                reader.start()
            try:
                process.wait(timeout=300)
            except subprocess.TimeoutExpired:
                self_stop = process.kill if os.name != "posix" else lambda: os.killpg(process.pid, signal.SIGKILL)
                try:
                    self_stop()
                except ProcessLookupError:
                    pass
                process.wait()
                for reader in readers:
                    reader.join(timeout=2)
                raise TimeoutError("Scout scan exceeded 300 seconds and was stopped.")
            for reader in readers:
                reader.join(timeout=2)
            return {
                "image": image_name,
                "source": source,
                "status": {0: "completed", 2: "vulnerabilities_found"}.get(process.returncode, "execution_failed"),
                "exit_code": process.returncode,
                "stdout": buffers["stdout"].decode("utf-8", errors="replace"),
                "stderr": buffers["stderr"].decode("utf-8", errors="replace"),
                "truncated": truncated[0],
            }
        finally:
            _SCOUT_SLOT.release()
