"""Real Uvicorn subprocess and TLS socket tests; no device or internet needed."""
import concurrent.futures
import datetime
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

class HttpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now-datetime.timedelta(minutes=1))
                .not_valid_after(now+datetime.timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
                .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True)
                .sign(key,hashes.SHA256()))
        (root/'cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (root/'key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        cls.context = ssl.create_default_context(cafile=str(root/'cert.pem'))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            port = sock.getsockname()[1]
        cls.url = f'https://127.0.0.1:{port}'
        plans = root/'plans'
        plans.mkdir()
        (plans/'network.json').write_text(json.dumps({'id':'network','title':'Network timer','mode':'study','approved_by':'Test fixture','steps':[{'text':'Network task','timer_seconds':1},{'text':'Finish by confirmation'}]}))
        cls.log = root/'host.log'
        cls.output = cls.log.open('w')
        env = dict(os.environ,MILK_FROG_DATA=str(root/'data'),MILK_FROG_WORKFLOWS=str(plans))
        cls.process = subprocess.Popen([sys.executable,'-m','uvicorn','milk_frog.device:create_app','--factory','--host','127.0.0.1','--port',str(port),'--ssl-keyfile',str(root/'key.pem'),'--ssl-certfile',str(root/'cert.pem')],env=env,stdout=cls.output,stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic()+15
            while time.monotonic()<deadline:
                if cls.process.poll() is not None:
                    raise AssertionError('Service failed to start: '+cls.log.read_text())
                try:
                    cls.fetch('/catalog')
                    break
                except (OSError, urllib.error.URLError):
                    time.sleep(.05)
            else:
                raise AssertionError('Timed out waiting for HTTPS startup')
            code = re.search(r'Physical pairing code: (\d{6})',cls.log.read_text()).group(1)
            status, paired = cls.fetch('/pair','POST',{'code':code})
            assert status == 200
            cls.token = paired['token']
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5)
        cls.output.close()
        cls.directory.cleanup()

    @classmethod
    def fetch(cls,path,method='GET',body=None,token=None,context=None):
        headers = {'Content-Type':'application/json'}
        if token is not None:
            headers['Authorization'] = 'Bearer '+token
        request = urllib.request.Request(cls.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
        # No proxies: device requests must use a direct local connection.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context or cls.context))
        try:
            response = opener.open(request,timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            return response.status,json.loads(raw) if raw else None

    def test_certificate_trust_is_required(self):
        with self.assertRaises(urllib.error.URLError) as failure:
            self.fetch('/catalog',context=ssl.create_default_context())
        self.assertIsInstance(failure.exception.reason,ssl.SSLCertVerificationError)

    def test_static_catalog_and_bad_credentials(self):
        self.assertEqual(self.fetch('/catalog')[0],401)
        self.assertEqual(self.fetch('/catalog',token='invalid')[0],401)
        status,data = self.fetch('/catalog',token=self.token)
        self.assertEqual(status,200)
        self.assertEqual(set(data),{'workflows'})
        self.assertEqual(data['workflows'][0]['id'],'network')
        self.assertEqual(self.fetch('/session',token=self.token)[0],404)

    def test_concurrent_authenticated_requests(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            statuses=list(pool.map(lambda _:self.fetch('/catalog',token=self.token)[0],range(32)))
        self.assertEqual(statuses,[200]*32)

    def test_concurrent_confirmations_cannot_advance_beyond_last_step(self):
        self.assertEqual(self.fetch('/commands','POST',{'action':'start','workflow_id':'network'},self.token)[0],204)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            statuses=list(pool.map(lambda _:self.fetch('/commands','POST',{'action':'confirm'},self.token)[0],range(16)))
        self.assertEqual(statuses.count(204),2)
        self.assertEqual(statuses.count(409),14)

    def test_invalid_payload_does_not_create_session(self):
        self.assertEqual(self.fetch('/commands','POST',{'action':'start','workflow_id':'network','audio':'private'},self.token)[0],422)
        self.assertEqual(self.fetch('/commands','POST',{'action':'confirm'},self.token)[0],409)

    def test_timer_runs_with_no_phone_requests(self):
        self.assertEqual(self.fetch('/commands','POST',{'action':'start','workflow_id':'network'},self.token),(204,None))
        # No HTTP requests while the timer is running.
        deadline=time.monotonic()+4
        while 'Timer finished: Network timer' not in self.log.read_text() and time.monotonic()<deadline:
            time.sleep(.05)
        self.assertIn('Timer finished: Network timer',self.log.read_text())
        self.assertEqual(self.fetch('/commands','POST',{'action':'confirm'},self.token),(204,None))
        self.assertEqual(self.fetch('/commands','POST',{'action':'confirm'},self.token),(204,None))
        self.assertEqual(self.fetch('/commands','POST',{'action':'confirm'},self.token)[0],409)
