import asyncio
import hashlib
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from .ai import ConsoleSpeaker
from .engine import Engine
from .entitlements import verify
from .models import Command, Entitlement, PairRequest, Workflow
from .storage import Store

ROOT = Path(__file__).resolve().parent

def create_app(data_dir=None, workflow_dir=None, speaker=None):
    store = Store(Path(data_dir or os.environ.get("MILK_FROG_DATA", "data")) / "device.sqlite")
    workflows = {}
    for path in Path(workflow_dir or ROOT / "workflows").glob("*.json"):
        value = Workflow.model_validate_json(path.read_text())
        if value.id in workflows:
            raise ValueError("Duplicate workflow ID")
        workflows[value.id] = value
    if not workflows:
        store.close()
        raise ValueError("No approved workflows found")
    # Audio playback cannot block host timer processing.
    audio = asyncio.Queue(maxsize=32)
    def enqueue(text):
        try:
            audio.put_nowait(text)
        except asyncio.QueueFull:
            logging.warning("Voice queue full; prompt remains in local event log")
    engine = Engine(workflows, store, enqueue)
    device_id = store.get("device_id") or secrets.token_hex(16)
    store.set("device_id", device_id)
    pairing = {"code": f"{secrets.randbelow(1000000):06}", "expires": time.monotonic() + 300, "attempts": 0}
    bearer = HTTPBearer(auto_error=False)

    async def ticker():
        while True:
            engine.tick()
            await asyncio.sleep(0.2)

    async def playback():
        while True:
            message = await audio.get()
            if engine.quiet or engine.muted:
                continue
            try:
                await asyncio.to_thread(speaker or ConsoleSpeaker(), message)
            except Exception:
                logging.exception("Local voice output failed")

    @asynccontextmanager
    async def lifespan(app):
        logging.warning("Physical pairing code: %s (valid for 5 minutes)", pairing["code"])
        tasks = [asyncio.create_task(ticker()), asyncio.create_task(playback())]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            store.close()

    app = FastAPI(title="Milk Frog local command API", lifespan=lifespan)
    app.state.engine, app.state.store, app.state.pairing = engine, store, pairing

    async def auth(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        expected = store.get("token_hash")
        actual = hashlib.sha256(credentials.credentials.encode()).hexdigest() if credentials else ""
        if not expected or not secrets.compare_digest(expected, actual):
            raise HTTPException(401, "Pair the device first")

    @app.post("/pair")
    async def pair(request: PairRequest):
        pairing["attempts"] += 1
        if pairing["attempts"] > 5 or time.monotonic() > pairing["expires"] or not secrets.compare_digest(request.code, pairing["code"]):
            raise HTTPException(403, "Invalid, locked or expired pairing code; restart locally")
        token = secrets.token_urlsafe(32)
        store.set("token_hash", hashlib.sha256(token.encode()).hexdigest())
        pairing["expires"] = 0
        return {"token": token, "device_id": device_id}

    @app.get("/catalog", dependencies=[Depends(auth)])
    async def catalog():
        # Static approved plans only; never return live session or monitoring data.
        return {"workflows": [w.model_dump() for w in workflows.values()]}

    @app.post("/commands", status_code=204, dependencies=[Depends(auth)])
    async def command(value: Command):
        packs = set()
        key = os.environ.get("MILK_FROG_ENTITLEMENT_PUBLIC_KEY")
        if key:
            for raw in store.get("entitlements", []):
                try:
                    item = Entitlement.model_validate(raw)
                    verify(item, bytes.fromhex(key), device_id)
                    packs.add(item.pack)
                except ValueError:
                    continue
        try:
            engine.command(value, packs)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/entitlements", status_code=204, dependencies=[Depends(auth)])
    async def entitlement(value: Entitlement):
        try:
            verify(value, bytes.fromhex(os.environ["MILK_FROG_ENTITLEMENT_PUBLIC_KEY"]), device_id)
        except (ValueError, KeyError) as exc:
            raise HTTPException(403, "Entitlement rejected") from exc
        saved = [e for e in store.get("entitlements", []) if e["pack"] != value.pack]
        store.set("entitlements", saved + [value.model_dump()])

    @app.delete("/local-data", status_code=204, dependencies=[Depends(auth)])
    async def delete_data():
        engine.workflow = None
        engine.status = "idle"
        engine.timers.clear()
        engine.quiet = False
        engine.absent_since = None
        engine.index = 0
        engine.next_reminder = 0.0
        while not audio.empty():
            audio.get_nowait()
        store.delete_all()
        store.set("device_id", device_id)
        # Deletion revokes all app credentials; physical restart enables pairing.

    return app
