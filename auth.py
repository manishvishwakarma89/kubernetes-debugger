import os
import secrets
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
auth = HTTPBearer(auto_error=False)

def require_token(credentials: HTTPAuthorizationCredentials = Depends(auth)):
    expected = os.getenv("DEBUGGER_API_TOKEN", "")
    if len(expected) < 32:
        raise HTTPException(503, "Configure DEBUGGER_API_TOKEN with at least 32 random characters.")
    if credentials is None or not secrets.compare_digest(credentials.credentials.encode(), expected.encode()):
        raise HTTPException(401, "Invalid access token.", headers={"WWW-Authenticate": "Bearer"})


