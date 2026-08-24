"""Self-hosted Web Push delivery (Phase 9) — the VAPID-authenticated,
vendor-free W3C Web Push Protocol via `pywebpush`, no Firebase/OneSignal.

This is the server's replacement for jarvis/interfaces/notify.py's Windows
toast: it plugs into the exact same `notify_fn` parameter that
jarvis/interfaces/proactive.py's run_morning_brief/run_reminder_check
already accept, so none of that logic changes for Phase 9 — only where the
notification actually goes.

The private key is stored in .env as a PEM string with literal newlines
escaped to `\\n` (a single env-var line), unescaped back to a real PEM on
load. Regenerating the keypair invalidates every existing browser
subscription — see settings.example.env's warning.
"""

from __future__ import annotations

import base64
import json

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid02
from pywebpush import WebPushException, webpush

from jarvis.core.config import Settings

VAPID_CLAIMS_SUB = "mailto:jarvis@localhost"


def generate_vapid_keys() -> tuple[str, str]:
    """Generate a fresh VAPID keypair. Returns (private_key_for_env, public_key_b64url).

    Call once during setup (see settings.example.env) — never regenerate
    after a browser has already subscribed to push.
    """
    vapid = Vapid02()
    vapid.generate_keys()

    private_pem = vapid.private_pem().decode("utf-8")
    private_for_env = private_pem.replace("\n", "\\n")

    public_raw = vapid.public_key.public_bytes(
        encoding=Encoding.X962, format=PublicFormat.UncompressedPoint
    )
    public_b64url = base64.urlsafe_b64encode(public_raw).decode("ascii").rstrip("=")

    return private_for_env, public_b64url


def send_push(subscription: dict, title: str, message: str, settings: Settings) -> bool:
    """Send one Web Push notification. Returns True on success, False if the
    push service rejected it (e.g. the subscription expired) — callers
    should drop a subscription that keeps failing, not retry forever."""
    private_pem = settings.vapid_private_key.replace("\\n", "\n")
    payload = json.dumps({"title": title, "body": message})

    try:
        webpush(
            subscription_info=subscription,
            data=payload,
            vapid_private_key=private_pem,
            vapid_claims={"sub": VAPID_CLAIMS_SUB},
        )
        return True
    except WebPushException:
        return False


if __name__ == "__main__":
    private_for_env, public_b64url = generate_vapid_keys()
    print(f"VAPID_PRIVATE_KEY={private_for_env}")
    print(f"VAPID_PUBLIC_KEY={public_b64url}")
