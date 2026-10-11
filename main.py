"""Main class registers FastAPI routes using decorators."""
import os
import secrets
from typing import Literal

from docker.errors import DockerException, NotFound
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from requests.exceptions import RequestException

from docker_debugger import DockerDebugger
from scout_jobs import ScoutJobs
from auth import require_token
from fastapi.responses import FileResponse
from pathlib import Path
import kubernetes_api


class DockerDebuggerApp:
    def __init__(self):
        self.app = FastAPI(title="Docker & Kubernetes Debugger", version="2.0.0")
        self.scout_jobs = ScoutJobs()
        self.register_routes()

    check_token = staticmethod(require_token)

    def get_debugger(self):
        debugger = None
        try:
            debugger = DockerDebugger()
            yield debugger
        except NotFound:
            raise HTTPException(404, "Container not found.")
        except ValueError as error:
            raise HTTPException(400, str(error))
        except (DockerException, RequestException):
            raise HTTPException(502, "Cannot communicate with Docker. Check the connection and permissions.")
        finally:
            if debugger is not None:
                debugger.close()

    def register_routes(self):
        app = self.app
        protected = [Depends(self.check_token)]

        @app.get("/")
        def home():
            return FileResponse(Path(__file__).parent / "static" / "index.html")

        @app.get("/healthz")
        def health():
            return {"status": "ok"}

        @app.get("/containers", dependencies=protected)
        def containers(debugger=Depends(self.get_debugger)):
            return debugger.list_containers()

        @app.get("/images", dependencies=protected)
        def images(debugger=Depends(self.get_debugger)):
            return debugger.list_images()

        @app.post("/images/scout", status_code=202, dependencies=protected)
        def start_scout(
            image_name: str = Query(..., min_length=1, max_length=255),
            source: Literal["local", "registry"] = Query("registry"),
        ):
            """Start a background scan, then poll status_url for progress and results."""
            try:
                return self.scout_jobs.submit(image_name, source)
            except ValueError as error:
                raise HTTPException(400, str(error))
            except BlockingIOError as error:
                raise HTTPException(429, str(error))

        @app.get("/images/scout/jobs/{job_id}", dependencies=protected)
        def scout_job(job_id: str):
            """Read job state. Results expire after 30 minutes or an app restart."""
            try:
                return self.scout_jobs.get(job_id)
            except KeyError:
                raise HTTPException(404, "Scan job not found or expired. Jobs are cleared on restart.")

        @app.post("/images/scout/sync", dependencies=protected, include_in_schema=False)
        def scout(
            image_name: str = Query(..., min_length=1, max_length=255),
            source: Literal["local", "registry"] = Query(
                "registry", description="Registry is the default for published images without Docker Engine; local needs a connected Docker daemon."
            ),
        ):
            try:
                result = DockerDebugger.scout_scan(image_name, source=source)
                if result["status"] == "execution_failed":
                    raise HTTPException(502, detail=result)
                return result
            except ValueError as error:
                raise HTTPException(400, str(error))
            except BlockingIOError as error:
                raise HTTPException(429, str(error))
            except FileNotFoundError as error:
                raise HTTPException(503, str(error))
            except TimeoutError as error:
                raise HTTPException(504, str(error))
            except OSError:
                raise HTTPException(502, "Docker Scout could not start. Check executable permissions.")

        @app.get("/containers/{name}/logs", dependencies=protected)
        def logs(name: str, tail: int = Query(200, ge=1, le=1000), debugger=Depends(self.get_debugger)):
            return debugger.get_logs(name, tail)

        @app.get("/containers/{name}/inspect", dependencies=protected)
        def inspect(name: str, debugger=Depends(self.get_debugger)):
            return debugger.inspect_container(name)

        @app.get("/containers/{name}/metrics", dependencies=protected)
        def metrics(name: str, debugger=Depends(self.get_debugger)):
            return debugger.get_metrics(name)


application = DockerDebuggerApp()
app = application.app

app.include_router(kubernetes_api.app)
slots = kubernetes_api.slots
