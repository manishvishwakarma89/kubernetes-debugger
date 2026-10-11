"""Authenticated, bounded manifest validation API. Nothing is deployed to a cluster."""
import json
import os
from pathlib import Path
import secrets
import threading

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.concurrency import run_in_threadpool

from validator import analyze, InputError, VERSIONS

from fastapi import APIRouter
from auth import require_token
app = APIRouter(tags=["Kubernetes"])
slots = threading.BoundedSemaphore(4)
auth = HTTPBearer(auto_error=False)


@app.get("/versions", dependencies=[Depends(require_token)])
def versions():
    return {"versions": VERSIONS, "default": "1.34.0"}


@app.post("/validate", dependencies=[Depends(require_token)], openapi_extra={
    "requestBody": {"required": True, "content": {"application/json": {
        "schema": {"type": "object", "required": ["manifest"], "additionalProperties": False,
                   "properties": {"manifest": {"type": "string", "maxLength": 524288},
                                  "kubernetes_version": {"type": "string", "enum": list(VERSIONS), "default": "1.34.0"}}},
        "example": {"manifest": "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: demo\ndata:\n  example: value\n", "kubernetes_version": "1.34.0"}
    }}}
})
async def validate_manifest(request: Request):
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "Validation capacity reached. Try again shortly.")
    try:
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 1024 * 1024:
                raise HTTPException(413, "Request exceeds the 1 MiB limit.")
        try:
            payload = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, "Send JSON with a manifest string and optional kubernetes_version.")
        if not isinstance(payload, dict) or set(payload) - {"manifest", "kubernetes_version"}:
            raise HTTPException(400, "Accepted fields: manifest and kubernetes_version.")
        try:
            return await run_in_threadpool(analyze, payload.get("manifest"), payload.get("kubernetes_version", "1.34.0"))
        except InputError as error:
            raise HTTPException(400, str(error))
    finally:
        slots.release()
