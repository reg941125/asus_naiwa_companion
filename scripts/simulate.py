"""Run from repository root: python -m scripts.simulate"""
import tempfile
from pathlib import Path
from milk_frog.engine import Engine
from milk_frog.models import Command, Workflow
from milk_frog.storage import Store

with tempfile.TemporaryDirectory() as directory:
    store = Store(Path(directory) / "demo.sqlite")
    workflow = Workflow.model_validate_json(Path("milk_frog/workflows/study_25_5.json").read_text())
    now = [0]
    engine = Engine({workflow.id: workflow}, store, print, lambda: now[0])
    engine.command(Command(action="start", workflow_id=workflow.id), set())
    now[0] += 1500
    engine.tick()
    engine.command(Command(action="confirm"), set())
    now[0] += 300
    engine.tick()
    engine.command(Command(action="confirm"), set())
    engine.command(Command(action="confirm"), set())
    store.close()
