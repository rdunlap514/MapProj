import contextlib
import importlib.util
import io
import shutil
import tempfile
import unittest
from unittest.mock import patch
from flask.testing import FlaskClient
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


class PageClient(FlaskClient):
    # Simulate opening a page and sending the token its shared script would attach.
    # Explicit headers bypass this helper for negative CSRF tests below.
    def open(self, *args, **kwargs):
        if kwargs.get('method', 'GET').upper() not in ('GET', 'HEAD', 'OPTIONS') and 'headers' not in kwargs:
            self.get('/login')
            with self.session_transaction() as session:
                kwargs['headers'] = {'X-CSRF-Token': session['csrf_token']}
        return super().open(*args, **kwargs)


class ReleaseRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mapproj-regression-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copy(ROOT / "app.py", self.root / "app.py")
        shutil.copytree(ROOT / "templates", self.root / "templates")
        spec = importlib.util.spec_from_file_location("test_app", self.root / "app.py")
        self.module = importlib.util.module_from_spec(spec)
        with contextlib.redirect_stdout(io.StringIO()), patch.dict('os.environ', {'MAPPROJ_DEMO_MODE': '1'}):
            spec.loader.exec_module(self.module)
        self.module.app.test_client_class = PageClient
        self.client = self.module.app.test_client()
        self.login(self.client, "admin", "admin123")
        # Additional roles are test fixtures, not accounts shipped with a fresh install.
        for name, role in {'maintenance': 'user', 'technology': 'technology', 'viewer': 'readonly'}.items():
            self.assertEqual(self.client.post('/api/user/add', json={'username': name, 'password': name + '123', 'role': role}).status_code, 200)

    def login(self, client, username, password):
        self.assertEqual(client.post("/api/login", json={"username": username, "password": password}).status_code, 200)

    def upload(self, name, image=b"original"):
        return self.client.post("/api/building/upload", data={"name": name, "image": (io.BytesIO(image), "plan.jpg")})

    def test_paths_cannot_escape_and_normal_buildings_work(self):
        sentinel = self.root / "outside"
        sentinel.mkdir()
        (sentinel / "keep.txt").write_text("safe")
        for name in ["..", "../outside", "..\\outside", str(sentinel), "C:\\outside", "CON", "trailing."]:
            with self.subTest(name=name):
                self.assertEqual(self.upload(name).status_code, 400)
        self.assertEqual(self.client.post("/api/building/..%5Coutside/delete").status_code, 400)
        self.assertEqual((sentinel / "keep.txt").read_text(), "safe")
        self.assertEqual(self.upload("Demo Center").status_code, 200)
        self.assertEqual(self.client.post("/api/building/Demo%20Center/duplicate", json={"new_name": "../outside"}).status_code, 400)
        self.assertEqual(self.client.post("/api/building/Demo%20Center/duplicate", json={"new_name": "Copy"}).status_code, 200)
        self.assertEqual(self.client.post("/api/building/Copy/delete").status_code, 200)

    def test_duplicate_upload_preserves_image_rooms_and_notes(self):
        self.assertEqual(self.upload("Demo").status_code, 200)
        rooms = {"101": {"color": "red", "nodes": [[0, 0], [10, 0], [10, 10]]}}
        self.assertEqual(self.client.post("/api/building/Demo/calibration/save", json=rooms).status_code, 200)
        self.client.post("/api/building/Demo/notes", json={"room_id": "101", "text": "Keep me"})
        self.assertEqual(self.upload("Demo", b"replacement").status_code, 409)
        self.assertEqual(self.client.get("/api/building/Demo/calibration").json, rooms)
        self.assertEqual((self.root / "buildings/Demo/image.jpg").read_bytes(), b"original")
        self.assertEqual(self.client.get("/api/building/Demo/notes").json["101"][0]["text"], "Keep me")

    def test_revocation_password_reset_and_recreated_accounts(self):
        self.client.post("/api/user/add", json={"username": "second", "password": "test", "role": "admin"})
        second = self.module.app.test_client()
        self.login(second, "second", "test")
        self.client.post("/api/user/second/edit", json={"role": "readonly"})
        self.assertEqual(second.get("/api/users").status_code, 302)
        self.assertEqual(second.post("/api/building/Demo/calibration/save", json={}).status_code, 403)
        self.client.post("/api/user/second/edit", json={"password": "new"})
        self.assertEqual(second.get("/api/buildings").status_code, 302)
        self.login(second, "second", "new")
        self.client.post("/api/user/second/delete")
        self.client.post("/api/user/add", json={"username": "second", "password": "new", "role": "admin"})
        self.assertEqual(second.get("/api/users").status_code, 302)
        exported = self.client.get("/api/users/export/json").get_data(as_text=True)
        self.assertNotIn("session_token", exported)
        self.assertNotIn("password_hash", exported)

    def test_viewer_cannot_write_and_templates_render(self):
        self.assertEqual(self.client.get("/admin").status_code, 200)
        viewer = self.module.app.test_client()
        self.login(viewer, "viewer", "viewer123")
        self.assertIn("const canEdit = false;", viewer.get("/user").get_data(as_text=True))
        self.assertEqual(viewer.post("/api/building/Demo/calibration/save", json={}).status_code, 403)
        self.assertEqual(viewer.post("/api/building/Demo/notes", json={"room_id": "101", "text": "test"}).status_code, 403)

    def test_status_permissions_and_geometry_preservation(self):
        self.upload('Demo')
        rooms = {'101': {'color': 'red', 'nodes': [[0, 0], [10, 0], [10, 10]]},
                 '102': {'color': 'green', 'x': 20}}
        self.client.post('/api/building/Demo/calibration/save', json=rooms)
        for role in ('maintenance', 'technology', 'viewer'):
            client = self.module.app.test_client()
            self.login(client, role, role + '123')
            self.assertEqual(client.post('/api/building/Demo/calibration/save', json={}).status_code, 403)
            response = client.post('/api/building/Demo/status', json={'room_id': '101', 'changes': {'color': 'yellow', 'leftConnected': True}})
            self.assertEqual(response.status_code, 403 if role == 'viewer' else 200)
            if role != 'viewer':
                for changes in ({'nodes': []}, {'color': '<script>'}, {'leftConnected': 'false'}):
                    self.assertEqual(client.post('/api/building/Demo/status', json={'room_id': '101', 'changes': changes}).status_code, 400)
                self.assertEqual(client.post('/api/building/Demo/status', json={'room_id': 'missing', 'changes': {'color': 'red'}}).status_code, 404)
                self.assertEqual(client.post('/api/building/Demo/notes', json={'room_id': '101', 'text': 'Still works'}).status_code, 200)
        saved = self.client.get('/api/building/Demo/calibration').json
        self.assertEqual(saved['101']['nodes'], rooms['101']['nodes'])
        self.assertEqual(saved['102'], rooms['102'])
        self.assertEqual(saved['101']['color'], 'yellow')

    def test_csrf_required_for_login_upload_and_logout(self):
        anonymous = self.module.app.test_client()
        self.assertEqual(anonymous.post('/api/login', json={'username': 'admin', 'password': 'admin123'}, headers={}).status_code, 403)
        for headers in ({}, {'X-CSRF-Token': 'wrong'}):
            self.assertEqual(self.client.post('/api/building/upload', data={'name': 'Blocked', 'image': (io.BytesIO(b'x'), 'x.jpg')}, headers=headers).status_code, 403)
            self.assertEqual(self.client.post('/logout', headers=headers).status_code, 403)
        self.assertFalse((self.root / 'buildings/Blocked').exists())
        self.assertEqual(self.client.get('/logout').status_code, 405)
        self.assertEqual(self.client.post('/logout').status_code, 302)
        self.assertEqual(self.client.get('/admin').status_code, 302)

    def test_starter_admin_can_be_replaced_without_reappearing(self):
        self.module.USERS_FILE = str(self.root / 'fresh-users.json')
        output = io.StringIO()
        with patch.dict('os.environ', {'MAPPROJ_DEMO_MODE': '0'}), contextlib.redirect_stdout(output):
            self.module.initialize_users()
        users = self.module.load_users()
        self.assertEqual(set(users), {'admin'})
        self.assertTrue(self.module.check_password_hash(users['admin']['password_hash'], 'admin123'))
        self.assertNotIn('password', users['admin'])
        client = self.module.app.test_client()
        self.login(client, 'admin', 'admin123')
        self.assertEqual(client.post('/api/user/add', json={'username':'owner', 'password':'personal-test-password', 'role':'admin'}).status_code, 200)
        client.post('/logout')
        self.login(client, 'owner', 'personal-test-password')
        self.assertEqual(client.get('/api/users').status_code, 200)
        self.assertEqual(client.post('/api/user/admin/delete').status_code, 200)
        before = self.module.load_users()
        with contextlib.redirect_stdout(io.StringIO()):
            self.module.initialize_users()
        self.assertEqual(self.module.load_users(), before)
        self.assertEqual(set(before), {'owner'})
        client.post('/logout')
        self.assertEqual(client.post('/api/login', json={'username':'admin','password':'admin123'}).status_code, 401)
        self.login(client, 'owner', 'personal-test-password')


if __name__ == "__main__":
    unittest.main()
