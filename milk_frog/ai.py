"""Local adapter seam; accelerator builds must be validated on target hardware."""
import asyncio
import subprocess
from pathlib import Path

class ModelManager:
    def __init__(self):
        self.lock = asyncio.Lock()

    async def run(self, adapter, request):
        async with self.lock:
            # Inference runs off the event loop so host timers keep ticking.
            worker = asyncio.create_task(asyncio.to_thread(adapter, request))
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                # A Python thread cannot be interrupted. Hold the accelerator
                # lock until the adapter has released its resources.
                try:
                    await worker
                finally:
                    raise

class ConsoleSpeaker:
    def __call__(self, text):
        print(text, flush=True)

class PiperSpeaker:
    def __init__(self, model, output):
        self.model, self.output = model, output

    def __call__(self, text):
        try:
            subprocess.run(["piper", "--model", self.model, "--output_file", self.output], input=text, text=True, check=True, timeout=30)
            subprocess.run(["aplay", self.output], check=True, timeout=60)
        finally:
            Path(self.output).unlink(missing_ok=True)

# Only these exact local recognizer outputs become commands. Free dialogue and
# scene answers are advisory and cannot modify workflows or issue instructions.
VOICE_COMMANDS = {"next": "confirm", "confirm": "confirm", "pause": "pause", "resume": "resume", "stop": "stop"}
