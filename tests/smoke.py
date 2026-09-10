import contextlib
import importlib.util
import io
import json
import shutil
import tempfile
import sys
from unittest.mock import patch
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tests'))
from test_regressions import PageClient
with tempfile.TemporaryDirectory(prefix='mapproj-test-') as directory:
    target = Path(directory)
    shutil.copy(root / 'app.py', target / 'app.py')
    shutil.copytree(root / 'templates', target / 'templates')
    spec = importlib.util.spec_from_file_location('release_app', target / 'app.py')
    module = importlib.util.module_from_spec(spec)
    output = io.StringIO()
    with contextlib.redirect_stdout(output), patch.dict('os.environ', {'MAPPROJ_DEMO_MODE': '1'}):
        spec.loader.exec_module(module)
    module.app.test_client_class = PageClient
    credentials = {}
    for line in output.getvalue().splitlines()[1:]:
        name, password = line.strip().split(': ', 1)
        credentials[name.split()[0]] = password
    assert credentials == {'admin': 'admin123'}
    assert all('password' not in value and 'password_hash' in value for value in module.USERS.values())
    client = module.app.test_client()
    assert client.post('/api/login', json={'username': 'admin', 'password': 'admin123'}).status_code == 200
    for name, role in {'maintenance': 'user', 'technology': 'technology', 'viewer': 'readonly'}.items():
        credentials[name] = name + '123'
        assert client.post('/api/user/add', json={'username': name, 'password': credentials[name], 'role': role}).status_code == 200
    for username, password in credentials.items():
        assert client.post('/api/login', json={'username': username, 'password': password}).status_code == 200
        assert client.get('/admin' if username == 'admin' else '/user').status_code == 200
        if username == 'viewer':
            assert client.post('/api/building/Test/notes', json={'room_id':'1','text':'no'}).status_code == 403
            assert client.post('/api/building/Test/calibration/save', json={}).status_code == 403
        client.post('/logout')
    assert client.post('/api/login', json={'username':'admin','password':'wrong'}).status_code == 401
    client.post('/api/login', json={'username':'admin','password':credentials['admin']})
    assert client.post('/api/user/add', json={'username':'tester','password':'original','role':'user'}).status_code == 200
    assert client.post('/api/user/tester/edit', json={'password':'replacement'}).status_code == 200
    for suffix in ['json', 'text']:
        data = client.get('/api/users/export/' + suffix).get_data(as_text=True)
        assert 'password_hash' not in data and 'replacement' not in data
        assert not any(password in data for password in credentials.values())
    assert client.post('/api/building/upload', data={'name':'Example','image':(io.BytesIO(b'example'),'image.jpg')}).status_code == 200
    rooms = {'101': {'x':10,'y':10,'w':40,'h':40,'color':'#A53E2F'}}
    assert client.post('/api/building/Example/calibration/save', json=rooms).status_code == 200
    assert client.get('/api/building/Example/calibration').json == rooms
    assert client.post('/api/building/Example/notes', json={'room_id':'101','text':'Example note'}).status_code == 200
    assert client.post('/api/building/Example/duplicate', json={'new_name':'Copy'}).status_code == 200
    assert client.post('/api/building/Copy/delete').status_code == 200
    before = module.load_users()
    with contextlib.redirect_stdout(io.StringIO()) as restart:
        module.initialize_users()
    assert module.load_users() == before and not restart.getvalue()
    client.post('/logout')
    assert client.post('/api/login', json={'username':'tester','password':'replacement'}).status_code == 200
    assert client.get('/api/users').status_code == 302
    client.post('/logout')
    client.post('/api/login', json={'username':'admin','password':credentials['admin']})
    assert client.post('/api/user/tester/delete').status_code == 200
print('PASS: fresh startup, all roles, password changes, exports, read-only restrictions, building APIs, and restart persistence.')
