"""Self-hosted Web Push delivery (Phase 9) — the VAPID-authenticated,
vendor-free W3C Web Push Protocol via `pywebpush`, no Firebase/OneSignal.

This is the server's replacement for jarvis/interfaces/notify.py's Windows
toast: it plugs into the exact same `notify_fn` parameter that
jarvis/interfaces/proactive.py's run_morning_brief/run_reminder_check
already accept, so none of that logic changes for Phase 9 — only where the
notification actually goes.

The private key is stored in .env as a bare base64url string — the raw
32-byte EC private value, no PEM armor. Found via live testing: py_vapid's
`Vapid.from_string()` (what pywebpush calls internally) strips newlines and
base64url-decodes the *whole* input; a full PEM's `-----BEGIN/END-----`
header/footer isn't valid base64, so passing a PEM there fails with an
opaque "ASN.1 parsing error: invalid length" — it never even gets to
checking the actual key bytes. Regenerating the keypair invalidates every
existing browser subscription — see settings.example.env's warning.
"""

from __future__ import annotations

import base64
import json
import logging

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid02
from pywebpush import webpush

from jarvis.core.config import Settings

VAPID_CLAIMS_SUB = "mailto:jarvis@localhost"

logger = logging.getLogger(__name__)


def generate_vapid_keys() -> tuple[str, str]:
    """Generate a fresh VAPID keypair. Returns (private_key_for_env, public_key_b64url) —
    both bare base64url strings, no PEM armor (see module docstring for why).

    Call once during setup (see settings.example.env) — never regenerate
    after a browser has already subscribed to push.
    """
    vapid = Vapid02()
    vapid.generate_keys()

    private_value = vapid.private_key.private_numbers().private_value
    private_raw = private_value.to_bytes(32, "big")
    private_b64url = base64.urlsafe_b64encode(private_raw).decode("ascii").rstrip("=")

    public_raw = vapid.public_key.public_bytes(
        encoding=Encoding.X962, format=PublicFormat.UncompressedPoint
    )
    public_b64url = base64.urlsafe_b64encode(public_raw).decode("ascii").rstrip("=")

    return private_b64url, public_b64url


def send_push(subscription: dict, title: str, message: str, settings: Settings) -> bool:
    """Send one Web Push notification. Returns True on success, False if the
    push service rejected it (e.g. the subscription expired) — callers
    should drop a subscription that keeps failing, not retry forever.

    `headers={"Urgency": "high"}` and a non-zero `ttl` were added after a
    real live-testing finding: pywebpush defaults to no explicit urgency
    and `ttl=0` (deliver right now or drop). The push still reached
    Google's FCM successfully either way, but on Android, Doze mode can
    defer a non-urgent message indefinitely rather than waking the device
    — confirmed live on a Pixel 8 (delivered to a laptop instantly, never
    surfaced on the phone, even though the server-side send genuinely
    succeeded for both). "Urgency: high" tells FCM/Android to wake the
    device immediately; the TTL gives it an hour to retry delivery if the
    device is briefly offline instead of dropping the message outright.
    """
    payload = json.dumps({"title": title, "body": message})

    try:
        webpush(
            subscription_info=subscription,
            data=payload,
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": VAPID_CLAIMS_SUB},
            ttl=3600,
            headers={"Urgency": "high"},
        )
        return True
    except Exception:
        # Broad on purpose: a bad subscription, a malformed VAPID key, a
        # network hiccup to the push service, etc. should never crash the
        # caller (the background scheduler) — but silently returning False
        # with no trace made a real delivery failure impossible to debug,
        # so this always logs the full exception first.
        logger.exception("send_push failed for endpoint %s", subscription.get("endpoint"))
        return False


if __name__ == "__main__":
    private_for_env, public_b64url = generate_vapid_keys()
    print(f"VAPID_PRIVATE_KEY={private_for_env}")
    print(f"VAPID_PUBLIC_KEY={public_b64url}")
