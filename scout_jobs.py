"""One scan at a time, bounded process-local job history, no credentials stored."""
from copy import deepcopy
import threading
import time
import uuid

from docker_debugger import DockerDebugger


class ScoutJobs:
    def __init__(self):
        self._lock = threading.Lock()
        self._jobs = {}
        self._active = None

    def submit(self, image, source):
        DockerDebugger.validate_scout_input(image, source)
        with self._lock:
            if self._active is not None:
                raise BlockingIOError("A scan is already running. Poll its status before starting another.")
            now = time.time()
            for key in list(self._jobs):
                if now - self._jobs[key]["created_at"] > 1800:
                    del self._jobs[key]
            while len(self._jobs) >= 20:
                del self._jobs[next(iter(self._jobs))]
            job_id = uuid.uuid4().hex
            self._jobs[job_id] = {"job_id": job_id, "image": image, "source": source,
                                  "state": "queued", "created_at": now, "result": None, "error": None}
            self._active = job_id
            try:
                threading.Thread(target=self._run, args=(job_id, image, source), daemon=True).start()
            except Exception:
                self._active = None
                del self._jobs[job_id]
                raise
            return {"job_id": job_id, "state": "accepted", "status_url": "/images/scout/jobs/" + job_id}

    def _run(self, job_id, image, source):
        with self._lock:
            self._jobs[job_id]["state"] = "running"
        result = None
        error = None
        state = "failed"
        try:
            result = DockerDebugger.scout_scan(image, source=source)
            state = "succeeded" if result["status"] in ("completed", "vulnerabilities_found") else "failed"
        except TimeoutError as exc:
            state, error = "timed_out", str(exc)
        except (ValueError, FileNotFoundError, BlockingIOError) as exc:
            error = str(exc)
        except Exception:
            error = "Scout could not complete. Check deployment logs and scanner configuration."
        finally:
            with self._lock:
                self._jobs[job_id].update(state=state, result=result, error=error, finished_at=time.time())
                self._active = None

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or (job_id != self._active and time.time() - job["created_at"] > 1800):
                raise KeyError(job_id)
            return deepcopy(job)
