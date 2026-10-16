"""Verify a built wheel from an isolated installation, outside the source tree."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv
import zipfile

root = Path(__file__).resolve().parents[1]
wheels = list((root / 'dist').glob('*.whl'))
if len(wheels) != 1:
    raise SystemExit('Expected one wheel in dist/. Clean dist/ and run python -m build.')
wheel = wheels[0]
with zipfile.ZipFile(wheel) as archive:
    names = archive.namelist()
    assert 'spavik/py.typed' in names
    assert any(name.endswith('/licenses/LICENSE') for name in names)
    assert any(name.endswith('/licenses/NOTICE') for name in names)
    assert not any(Path(name).name.startswith('.env') for name in names)
    metadata = archive.read(next(name for name in names if name.endswith('.dist-info/METADATA'))).decode()
    assert 'License-Expression: Apache-2.0' in metadata

with tempfile.TemporaryDirectory(prefix='spavik-wheel-') as directory:
    work = Path(directory)
    venv.EnvBuilder(with_pip=True).create(work / 'venv')
    python = work / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', str(wheel)], check=True)
    consumer = work / 'consumer.py'
    consumer.write_text('''import asyncio
import hashlib
import hmac
from pathlib import Path
import httpx
import spavik
from spavik import Spavik, AsyncSpavik, SpavikSignatureError
from spavik.webhooks import verifier

assert Path(spavik.__file__).resolve().is_relative_to((Path(__file__).parent / "venv").resolve())
calls = []
def handler(request):
    calls.append(request)
    assert request.headers["X-Spavik-Api-Key"] == "sk-spv-api-fixture"
    assert str(request.url) == "https://fixture.invalid/v1/usage"
    return httpx.Response(200, json={"credit_balance": 7})

with Spavik("sk-spv-api-fixture", base_url="https://fixture.invalid",
            client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
    assert client.usage()["credit_balance"] == 7

async def check_async():
    async with AsyncSpavik("sk-spv-api-fixture", base_url="https://fixture.invalid",
                          client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as client:
        assert (await client.usage())["credit_balance"] == 7
asyncio.run(check_async())
assert len(calls) == 2
body = b'{"event":"model.trained"}'
signature = hmac.new(b"fixture", body, hashlib.sha256).hexdigest()
assert verifier(body, {"X-Spavik-Signature": signature}, "fixture")["event"] == "model.trained"
try:
    verifier(body, {}, "fixture")
except SpavikSignatureError:
    pass
else:
    raise AssertionError("Missing signature accepted")
print("Installed wheel verified: sync/async requests, shared errors and webhooks.")
''', encoding='utf-8')
    subprocess.run([str(python), '-I', str(consumer)], cwd=work, check=True)
