import base64
import json
import time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from .models import Entitlement

def payload(device_id, pack, expires_at):
    return json.dumps({"device_id": device_id, "pack": pack, "expires_at": expires_at}, sort_keys=True, separators=(",", ":")).encode()

def verify(value: Entitlement, public_key: bytes, device_id: str):
    if value.device_id != device_id or value.expires_at <= time.time():
        raise ValueError("Expired entitlement or incorrect device")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(base64.b64decode(value.signature, validate=True), payload(value.device_id, value.pack, value.expires_at))
    except Exception as exc:
        raise ValueError("Invalid entitlement signature") from exc
