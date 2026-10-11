"""Receipt verification seam. Disabled unless a real store verifier is supplied."""
import base64
import time
from fastapi import FastAPI, HTTPException
from pydantic import Field
from .models import StrictModel
from .entitlements import payload

class Purchase(StrictModel):
    device_id: str = Field(min_length=1, max_length=128)
    pack: str = Field(pattern=r"^[a-z0-9_-]{1,64}$")
    receipt: str = Field(min_length=1, max_length=16384)

def create_app(private_key=None, receipt_verifier=None):
    app = FastAPI(title="Milk Frog account entitlement service")

    @app.post("/entitlements")
    def purchase(value: Purchase):
        if private_key is None or receipt_verifier is None:
            raise HTTPException(503, "Store receipt verification is not configured")
        # Provider integration must verify product, ownership, revocation and replay.
        if not receipt_verifier(value):
            raise HTTPException(403, "Receipt verification failed")
        expires = int(time.time()) + 365 * 86400
        signature = private_key.sign(payload(value.device_id, value.pack, expires))
        return {"device_id": value.device_id, "pack": value.pack, "expires_at": expires, "signature": base64.b64encode(signature).decode()}

    return app
