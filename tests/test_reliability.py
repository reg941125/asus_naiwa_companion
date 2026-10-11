"""Hardware-free persistence, failure, and state-machine regression checks."""
import asyncio
import base64
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from milk_frog.ai import ModelManager, PiperSpeaker
from milk_frog.device import create_app
from milk_frog.entitlements import payload
from milk_frog.models import Command

class ReliabilityTests(unittest.TestCase):
    def test_restart_retains_identity_credentials_preferences_but_not_session(self):
        with tempfile.TemporaryDirectory() as directory:
            first = create_app(directory, speaker=lambda text: None)
            with TestClient(first) as client:
                paired = client.post('/pair', json={'code': first.state.pairing['code']}).json()
                headers = {'Authorization': 'Bearer ' + paired['token']}
                client.post('/commands', headers=headers, json={'action':'quiet'})
                client.post('/commands', headers=headers, json={'action':'start','workflow_id':'study_25_5'})
                self.assertTrue(first.state.engine.timers)
            second = create_app(directory, speaker=lambda text: None)
            with TestClient(second) as client:
                self.assertEqual(second.state.store.get('device_id'), paired['device_id'])
                self.assertEqual(client.get('/catalog', headers=headers).status_code, 200)
                self.assertTrue(second.state.engine.quiet)
                self.assertEqual(second.state.engine.status, 'idle')
                self.assertEqual(second.state.engine.timers, [])
                newly_paired = client.post('/pair', json={'code':second.state.pairing['code']}).json()
                self.assertNotEqual(newly_paired['token'], paired['token'])
                self.assertEqual(client.get('/catalog', headers=headers).status_code, 401)

    def test_deletion_remains_deleted_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory, speaker=lambda text: None)
            with TestClient(app) as client:
                token = client.post('/pair', json={'code':app.state.pairing['code']}).json()['token']
                headers = {'Authorization':'Bearer '+token}
                client.post('/commands', headers=headers, json={'action':'quiet'})
                client.delete('/local-data', headers=headers)
            restarted = create_app(directory, speaker=lambda text: None)
            with TestClient(restarted) as client:
                self.assertEqual(client.get('/catalog', headers=headers).status_code, 401)
                self.assertFalse(restarted.state.engine.quiet)
                self.assertEqual(restarted.state.store.get('entitlements', []), [])
                self.assertEqual(restarted.state.store.db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 0)

    def test_expiry_is_rechecked_when_starting_pack_not_only_when_installing(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory, speaker=lambda text: None)
            app.state.engine.workflows['cooking_demo'].pack = 'recipe'
            with TestClient(app) as client:
                paired = client.post('/pair', json={'code':app.state.pairing['code']}).json()
                headers = {'Authorization':'Bearer '+paired['token']}
                key = Ed25519PrivateKey.generate()
                expiry = int(time.time())+3600
                item = {'device_id':paired['device_id'],'pack':'recipe','expires_at':expiry,
                        'signature':base64.b64encode(key.sign(payload(paired['device_id'],'recipe',expiry))).decode()}
                with patch.dict('os.environ', {'MILK_FROG_ENTITLEMENT_PUBLIC_KEY':key.public_key().public_bytes_raw().hex()}):
                    self.assertEqual(client.post('/entitlements', headers=headers, json=item).status_code, 204)
                    with patch('milk_frog.entitlements.time.time', return_value=expiry+1):
                        response = client.post('/commands', headers=headers, json={'action':'start','workflow_id':'cooking_demo','permission_confirmed':True})
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(app.state.engine.status, 'idle')

    def test_speaker_failure_does_not_stop_timer_or_future_commands(self):
        called = threading.Event()
        def broken_speaker(text):
            called.set()
            raise RuntimeError('Simulated disconnected USB speaker')
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory, speaker=broken_speaker)
            with TestClient(app) as client:
                paired = client.post('/pair', json={'code':app.state.pairing['code']}).json()
                headers = {'Authorization':'Bearer '+paired['token']}
                with self.assertLogs(level='ERROR'):
                    client.post('/commands', headers=headers, json={'action':'start','workflow_id':'study_25_5'})
                    self.assertTrue(called.wait(1))
                    app.state.engine.timers[0].deadline = time.monotonic()+.05
                    time.sleep(.4)
                    self.assertEqual(app.state.engine.timers, [])
                    self.assertEqual(client.post('/commands', headers=headers, json={'action':'confirm'}).status_code, 204)

    def test_invalid_transitions_leave_state_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory, speaker=lambda text: None)
            with TestClient(app) as client:
                engine = app.state.engine
                for action in ['pause','resume','confirm']:
                    with self.assertRaises(ValueError):
                        engine.command(Command(action=action), set())
                    self.assertEqual(engine.status, 'idle')
                engine.command(Command(action='start',workflow_id='study_25_5'), set())
                for action in ['resume','start']:
                    with self.assertRaises(ValueError):
                        engine.command(Command(action=action,workflow_id='cooking_demo',permission_confirmed=True), set())
                    self.assertEqual(engine.workflow.id, 'study_25_5')
                    self.assertEqual(engine.index, 0)
                engine.command(Command(action='stop'), set())
                self.assertEqual(engine.timers, [])

    def test_workflow_validation_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            plans = Path(directory)/'plans'
            plans.mkdir()
            with self.assertRaisesRegex(ValueError, 'No approved workflows'):
                create_app(Path(directory)/'empty', plans)
            (plans/'bad.json').write_text(json.dumps({'id':'bad','title':'bad','mode':'experiment','approved_by':'','steps':[]}))
            with self.assertRaises(ValueError):
                create_app(Path(directory)/'invalid', plans)

    def test_piper_failure_removes_temporary_speech(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'speech.wav'
            output.write_bytes(b'generated speech')
            with patch('milk_frog.ai.subprocess.run', side_effect=RuntimeError('Piper unavailable')):
                with self.assertRaises(RuntimeError):
                    PiperSpeaker('local.onnx',str(output))('Hello')
            self.assertFalse(output.exists())

class InferenceFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_adapter_failure_releases_lock_for_next_task(self):
        manager = ModelManager()
        def broken(value):
            raise RuntimeError('Simulated accelerator failure')
        with self.assertRaises(RuntimeError):
            await manager.run(broken, None)
        self.assertEqual(await asyncio.wait_for(manager.run(lambda value:value, 'recovered'), timeout=1), 'recovered')

    async def test_repeated_cancellation_does_not_overlap_adapters(self):
        manager = ModelManager()
        started = threading.Event()
        release = threading.Event()
        next_started = threading.Event()
        def blocked(_):
            started.set()
            release.wait(3)
        task = asyncio.create_task(manager.run(blocked,None))
        self.assertTrue(await asyncio.to_thread(started.wait,1))
        task.cancel()
        await asyncio.sleep(.01)
        task.cancel()
        next_task = asyncio.create_task(manager.run(lambda _:next_started.set(),None))
        try:
            await asyncio.sleep(.02)
            self.assertFalse(next_started.is_set())
        finally:
            release.set()
            await asyncio.gather(task,next_task,return_exceptions=True)
