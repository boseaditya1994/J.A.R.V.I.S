"""Bearer-token auth for the Phase 9 server.

A single shared secret, not a user/account system — proportionate for a
single-user personal assistant reachable off the home network for the
first time. Checked with `secrets.compare_digest` so a timing attack can't
narrow down the token character by character.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from jarvis.core.config import Settings

_bearer_scheme = HTTPBearer(auto_error=False)


def require_auth(settings: Settings):
    """Build a FastAPI dependency bound to this `settings` instance."""

    def _check(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    ) -> None:
        if not settings.api_auth_token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server has no API_AUTH_TOKEN configured.",
            )
        if credentials is None or not secrets.compare_digest(
            credentials.credentials, settings.api_auth_token
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing bearer token.",
            )

    return _check
