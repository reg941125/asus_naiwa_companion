import asyncio
import base64
import tempfile
import time
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from milk_frog.account import create_app as account_app
from milk_frog.ai import ModelManager
from milk_frog.device import create_app
from milk_frog.engine import Engine
from milk_frog.entitlements import payload, verify
from milk_frog.models import Command, Entitlement, Step, Workflow
from milk_frog.storage import Store

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / 'test.sqlite')
        self.now = 0
        self.messages = []
        self.workflow = Workflow(id='demo', title='Demo', mode='study', approved_by='Reviewer', steps=[Step(text='Work', timer_seconds=10), Step(text='Break', timer_seconds=5)])
        self.engine = Engine({'demo': self.workflow}, self.store, self.messages.append, lambda: self.now)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def send(self, action, **kwargs):
        self.engine.command(Command(action=action, **kwargs), set())

    def test_timers_require_confirmation_and_pause_freezes_remaining(self):
        self.send('start', workflow_id='demo')
        self.now = 3
        self.send('pause')
        self.now = 100
        self.engine.tick()
        self.assertEqual(len(self.messages), 1)
        self.send('resume')
        self.now = 107
        self.engine.tick()
        self.assertEqual(self.engine.index, 0)
        self.assertIn('Timer finished', self.messages[-1])
        self.send('confirm')
        self.assertEqual(self.engine.index, 1)
        self.send('confirm')
        self.assertEqual(self.engine.status, 'completed')

    def test_parallel_timers_and_switch_guard(self):
        self.send('start', workflow_id='demo')
        self.send('confirm')
        self.assertEqual(len(self.engine.timers), 2)
        with self.assertRaises(ValueError):
            self.send('start', workflow_id='demo')
        self.now = 10
        self.engine.tick()
        self.assertEqual(len(self.engine.timers), 0)

    def test_absence_unknown_cooldown_snooze_quiet(self):
        self.send('start', workflow_id='demo')
        self.engine.presence(None)
        self.assertIsNone(self.engine.absent_since)
        self.engine.presence(False)
        self.now = 61
        self.engine.tick()
        self.assertIn('away', self.messages[-1])
        count = len(self.messages)
        self.now = 62
        self.engine.tick()
        self.assertEqual(len(self.messages), count)
        self.send('snooze', seconds=1000)
        self.now = 400
        self.engine.tick()
        self.assertEqual(len(self.messages), count)
        self.send('quiet')
        self.engine.say('Silent')
        self.assertEqual(len(self.messages), count)

    def test_unknown_presence_resets_absence_evidence(self):
        self.send('start', workflow_id='demo')
        self.engine.presence(False)
        self.now = 30
        self.engine.presence(None)
        self.assertIsNone(self.engine.absent_since)
        self.now = 90
        self.engine.tick()
        self.assertFalse(any('away' in message for message in self.messages))

    def test_pack_permission_and_confirmation_guards(self):
        self.workflow.mode = 'experiment'
        with self.assertRaises(ValueError):
            self.send('start', workflow_id='demo')
        self.workflow.pack = 'course'
        with self.assertRaises(PermissionError):
            self.send('start', workflow_id='demo', permission_confirmed=True)
        with self.assertRaises(ValueError):
            self.send('confirm')

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.app = create_app(self.directory.name)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.directory.cleanup()

    def pair(self):
        result = self.client.post('/pair', json={'code': self.app.state.pairing['code']})
        self.assertEqual(result.status_code, 200)
        data = result.json()
        self.headers = {'Authorization': 'Bearer ' + data['token']}
        return data

    def test_pair_privacy_commands_deletion(self):
        self.assertEqual(self.client.get('/catalog').status_code, 401)
        data = self.pair()
        self.assertEqual(self.client.post('/pair', json={'code': self.app.state.pairing['code']}).status_code, 403)
        self.assertEqual(self.client.get('/catalog', headers=self.headers).status_code, 200)
        response = self.client.post('/commands', headers=self.headers, json={'action': 'start', 'workflow_id': 'study_25_5'})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b'')
        self.assertEqual(self.client.get('/session', headers=self.headers).status_code, 404)
        self.assertEqual(self.client.post('/commands', headers=self.headers, json={'action':'confirm', 'camera': 'secret'}).status_code, 422)
        self.assertEqual(self.client.delete('/local-data', headers=self.headers).status_code, 204)
        self.assertEqual(self.client.get('/catalog', headers=self.headers).status_code, 401)
        self.assertEqual(self.app.state.store.db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 0)

    def test_pair_lockout(self):
        for _ in range(6):
            self.client.post('/pair', json={'code': 'xxxxxx'})
        self.assertEqual(self.client.post('/pair', json={'code': self.app.state.pairing['code']}).status_code, 403)

    def test_entitlement_signature_expiry_binding(self):
        data = self.pair()
        key = Ed25519PrivateKey.generate()
        expires = int(time.time()) + 600
        signature = base64.b64encode(key.sign(payload(data['device_id'], 'course', expires))).decode()
        value = Entitlement(device_id=data['device_id'], pack='course', expires_at=expires, signature=signature)
        with patch.dict('os.environ', {'MILK_FROG_ENTITLEMENT_PUBLIC_KEY': key.public_key().public_bytes_raw().hex()}):
            self.assertEqual(self.client.post('/entitlements', headers=self.headers, json=value.model_dump()).status_code, 204)
            value.pack = 'tampered'
            self.assertEqual(self.client.post('/entitlements', headers=self.headers, json=value.model_dump()).status_code, 403)
        with self.assertRaises(ValueError):
            verify(value, key.public_key().public_bytes_raw(), 'other-device')
        value.expires_at = 1
        with self.assertRaises(ValueError):
            verify(value, key.public_key().public_bytes_raw(), data['device_id'])

    def test_host_timer_survives_blocked_audio(self):
        started = threading.Event()
        release = threading.Event()
        def speaker(message):
            started.set()
            release.wait(timeout=3)
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory, speaker=speaker)
            with TestClient(app) as client:
                paired = client.post('/pair', json={'code': app.state.pairing['code']}).json()
                headers = {'Authorization': 'Bearer ' + paired['token']}
                client.post('/commands', headers=headers, json={'action':'start','workflow_id':'study_25_5'})
                self.assertTrue(started.wait(timeout=1))
                app.state.engine.timers[0].deadline = time.monotonic() + .05
                time.sleep(.4)
                self.assertEqual(app.state.engine.timers, [])
                self.assertEqual(app.state.engine.index, 0)
                release.set()

    def test_expired_pairing_rejected(self):
        self.app.state.pairing['expires'] = 0
        self.assertEqual(self.client.post('/pair', json={'code': self.app.state.pairing['code']}).status_code, 403)

    def test_signed_pack_unlocks_only_its_workflow(self):
        data = self.pair()
        self.app.state.engine.workflows['cooking_demo'].pack = 'recipe'
        start = {'action':'start', 'workflow_id':'cooking_demo', 'permission_confirmed': True}
        self.assertEqual(self.client.post('/commands', headers=self.headers, json=start).status_code, 403)
        key = Ed25519PrivateKey.generate()
        with TestClient(account_app(key, lambda purchase: purchase.receipt == 'verified-provider-receipt')) as account:
            self.assertEqual(account.post('/entitlements', json={'device_id':data['device_id'],'pack':'recipe','receipt':'invalid'}).status_code, 403)
            signed = account.post('/entitlements', json={'device_id':data['device_id'],'pack':'recipe','receipt':'verified-provider-receipt'}).json()
        with patch.dict('os.environ', {'MILK_FROG_ENTITLEMENT_PUBLIC_KEY': key.public_key().public_bytes_raw().hex()}):
            self.assertEqual(self.client.post('/entitlements', headers=self.headers, json=signed).status_code, 204)
            self.assertEqual(self.client.post('/commands', headers=self.headers, json=start).status_code, 204)

    def test_account_fails_closed(self):
        with TestClient(account_app()) as client:
            self.assertEqual(client.post('/entitlements', json={'device_id':'demo','pack':'course','receipt':'unverified'}).status_code, 503)
            self.assertEqual(client.post('/entitlements', json={'device_id':'demo','pack':'course','receipt':'x','audio':'secret'}).status_code, 422)

class ModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_job_retains_accelerator_lock(self):
        manager = ModelManager()
        started = threading.Event()
        release = threading.Event()
        second_started = threading.Event()
        def first_adapter(_):
            started.set()
            release.wait(timeout=3)
        first = asyncio.create_task(manager.run(first_adapter, None))
        await asyncio.to_thread(started.wait, 1)
        first.cancel()
        second = asyncio.create_task(manager.run(lambda _: second_started.set(), None))
        await asyncio.sleep(.02)
        self.assertFalse(second_started.is_set())
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await first
        await second
        self.assertTrue(second_started.is_set())

    async def test_inference_serialized_and_event_loop_free(self):
        manager = ModelManager()
        activity = []
        def adapter(value):
            activity.append(('start', value))
            time.sleep(.05)
            activity.append(('end', value))
            return value
        first = asyncio.create_task(manager.run(adapter, 1))
        second = asyncio.create_task(manager.run(adapter, 2))
        await asyncio.sleep(.01)
        self.assertFalse(first.done())
        self.assertEqual(await asyncio.gather(first, second), [1, 2])
        self.assertEqual(activity, [('start',1),('end',1),('start',2),('end',2)])

if __name__ == '__main__':
    unittest.main()
