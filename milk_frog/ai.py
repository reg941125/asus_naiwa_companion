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
            cancelled = False
            while True:
                try:
                    result = await asyncio.shield(worker)
                    break
                except asyncio.CancelledError:
                    # Repeated cancellation must not interrupt the thread's
                    # resource cleanup or let another model start early.
                    if worker.cancelled():
                        raise
                    cancelled = True
                except BaseException:
                    if cancelled:
                        raise asyncio.CancelledError() from None
                    raise
            if cancelled:
                raise asyncio.CancelledError()
            return result

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
