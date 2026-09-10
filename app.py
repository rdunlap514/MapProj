# MapProj backend: browser requests come here; Flask checks access, reads/writes
# local JSON files, and returns either an HTML page or JSON for JavaScript.
# Reading order: startup/settings -> storage helpers -> access checks -> routes.

from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for, Response
from functools import wraps
import json
import os
from pathlib import Path
import datetime

import secrets
from werkzeug.security import generate_password_hash, check_password_hash

# Use this file's folder, so storage does not move when you launch from another directory.
BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__)
# Flask signs the session cookie with this key so a browser cannot alter its role.
# Signing is not encryption: never put passwords or password hashes in the session.
app.secret_key = os.environ.get('MAPPROJ_SECRET_KEY') or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')
BUILDINGS_DIR = str(BASE_DIR / 'buildings')
os.makedirs(BUILDINGS_DIR, exist_ok=True)

USERS_FILE = str(BASE_DIR / 'users.json')
USERS_LIST_FILE = str(BASE_DIR / 'users_list.txt')

def get_building_legend_path(building_name):
    return os.path.join(get_building_path(building_name), 'legend.json')

def get_building_notes_path(building_name):
    return os.path.join(get_building_path(building_name), 'notes.json')

def get_building_history_path(building_name):
    return os.path.join(get_building_path(building_name), 'history.json')

# The legend maps status keys (like red) to labels and display colors.
# Older files use a dictionary; the browser receives a list to preserve display order.
def load_legend(building_name=None):
    if building_name:
        legend_path = get_building_legend_path(building_name)
        if os.path.exists(legend_path):
            with open(legend_path, 'r') as f:
                data = json.load(f)

            # Normalize: convert object to ordered array of entries for consistent ordering
            if isinstance(data, dict):
                return [{'key': k, **v} for k, v in data.items()]
            return data

    # Default legend as ordered array
    return [
        {'key': 'red',   'label': 'RoomState1', 'color': '#A53E2F'},
        {'key': 'yellow','label': 'RoomState2', 'color': '#E8A830'},
        {'key': 'green', 'label': 'Roomstate3', 'color': '#5a9f4a'},
        {'key': 'modifier', 'label': 'Modifier', 'color': '#0066ff', 'enabled': True}
    ]

# Convert the browser's list of legend entries into the format stored on disk.
def save_legend(building_name, legend):
    # Normalize: convert ordered array back to dict for JSON storage
    if isinstance(legend, list):
        data = {}
        for entry in legend:
            key = entry.get('key')
            if key is not None:
                data[key] = {k: v for k, v in entry.items() if k != 'key'}
        legend_path = get_building_legend_path(building_name)
        with open(legend_path, 'w') as f:
            json.dump(data, f, indent=2)
    else:
        legend_path = get_building_legend_path(building_name)
        with open(legend_path, 'w') as f:
            json.dump(legend, f, indent=2)

# Account names are friendly labels; role values are what permission checks use.
# The maintenance account uses the internal role user; viewer uses readonly.
STARTER_ROLES = {'admin': 'admin', 'maintenance': 'user', 'technology': 'technology', 'viewer': 'readonly'}

# Load the current account records, including password hashes and session tokens.
def load_users():
    with open(USERS_FILE, encoding='utf-8') as f:
        return json.load(f)

# Produce a shareable account list that deliberately excludes login secrets.
def generate_users_list(users):
    lines = ['MapProj user accounts (passwords are never exported)\n\n']
    for username, info in sorted(users.items()):
        lines.append(f"{username}: {info['role']}\n")
    Path(USERS_LIST_FILE).write_text(''.join(lines), encoding='utf-8')

# Keep the JSON account store and the human-readable export in sync.
def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2)
    generate_users_list(users)

# Public demo passwords require an explicit opt-in; ordinary installs get random passwords.
# This setting only affects first-time setup, never overwrites existing accounts.
# A password hash lets us verify a password without storing the original password.
def initialize_users():
    if not os.path.exists(USERS_FILE):
        users = {}
        demo = os.environ.get('MAPPROJ_DEMO_MODE') == '1'
        print('MapProj initial accounts (save these passwords; shown only on first startup):')
        for username, role in STARTER_ROLES.items():
            password = username + '123' if demo else secrets.token_urlsafe(18)
            users[username] = {
                'password_hash': generate_password_hash(password),
                'role': role,
                'session_token': secrets.token_hex(32),
                'created_at': datetime.datetime.now().isoformat()
            }
            print(f'  {username} ({role}): {password}')
        save_users(users)
    else:
        users = load_users()
        # Migrate older local installations without retaining plaintext passwords.
        for info in users.values():
            info.setdefault('session_token', secrets.token_hex(32))
            if 'password' in info:
                info['password_hash'] = generate_password_hash(info.pop('password'))
        save_users(users)

initialize_users()
USERS = load_users()

# Ensure buildings directory exists
Path(BUILDINGS_DIR).mkdir(exist_ok=True)

# A dedicated exception lets invalid names become a clear HTTP 400 response.
class InvalidBuildingName(ValueError):
    pass


@app.errorhandler(InvalidBuildingName)
def invalid_building_name(error):
    return jsonify({'error': str(error)}), 400


# Every building file operation goes through this boundary check.
# Reject path syntax rather than silently renaming input: renaming could target another building.
def get_building_path(building_name):
    # A name is one directory component, never a caller-supplied path.
    if (not isinstance(building_name, str) or not building_name
            or building_name in ('.', '..')
            or building_name.endswith((' ', '.'))
            or any(c in building_name for c in '/\\:<>"|?*')
            or any(ord(c) < 32 for c in building_name)
            or building_name.split('.')[0].upper() in
               {'CON', 'PRN', 'AUX', 'NUL', *('COM' + str(i) for i in range(1, 10)),
                *('LPT' + str(i) for i in range(1, 10))}):
        raise InvalidBuildingName('Use a building name without path separators or reserved characters.')
    base = Path(BUILDINGS_DIR).resolve()
    target = (base / building_name).resolve()
    # Resolving also detects existing symlinks/junctions pointing elsewhere.
    if target.parent != base:
        raise InvalidBuildingName('Building must remain inside the buildings directory.')
    return str(target)

def get_building_image_path(building_name):
    return os.path.join(get_building_path(building_name), 'image.jpg')

def get_building_calibration_path(building_name):
    return os.path.join(get_building_path(building_name), 'calibration.json')

# Calibration means the saved room map: room IDs mapped to geometry and status.
# An empty dictionary means this building has no traced rooms yet.
def load_building_calibration(building_name):
    calib_path = get_building_calibration_path(building_name)
    if os.path.exists(calib_path):
        with open(calib_path, 'r') as f:
            return json.load(f)
    return {}

# This writes the whole room map, not just one changed room.
# Two browsers saving stale copies can overwrite each other; this is not a database transaction.
def save_building_calibration(building_name, calibration):
    building_path = get_building_path(building_name)
    os.makedirs(building_path, exist_ok=True)
    calib_path = get_building_calibration_path(building_name)
    with open(calib_path, 'w') as f:
        json.dump(calibration, f, indent=2)

# Only folders with a floor-plan image count as selectable buildings.
def list_buildings():
    if not os.path.exists(BUILDINGS_DIR):
        return []
    buildings = []
    for item in os.listdir(BUILDINGS_DIR):
        item_path = os.path.join(BUILDINGS_DIR, item)
        if os.path.isdir(item_path) and os.path.exists(get_building_image_path(item)):
            buildings.append(item)
    return sorted(buildings)

@app.before_request
# Flask runs this before each request, including before the route's decorators.
# Refresh roles from disk; a deleted account or changed token invalidates its old cookie.
def refresh_session_user():
    global USERS
    USERS = load_users()
    username = session.get('username')
    if username:
        account = USERS.get(username)
        if not account or session.get('session_token') != account.get('session_token'):
            session.clear()
        else:
            session['role'] = account['role']


def csrf_token():
    # A separate random token proves a write came from a page opened in this session.
    # Cookies alone are insufficient: browsers can attach them to unwanted requests.
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']


@app.context_processor
def template_security():
    return {'csrf_token': csrf_token}


@app.before_request
def protect_writes():
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        expected = session.get('csrf_token')
        supplied = request.headers.get('X-CSRF-Token', '')
        if not expected or not secrets.compare_digest(expected, supplied):
            return jsonify({'error': 'Page expired. Reload and try again.'}), 403


# A decorator wraps a route: check login first, then call the original function.
# wraps preserves the original function name, which Flask uses to identify routes.
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Being logged in is not enough here: account management needs the current admin role.
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            return redirect(url_for('user'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
# The home page sends each signed-in user to the interface for their role.
def index():
    if 'username' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('admin'))
        else:
            return redirect(url_for('user'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET'])
def login():
    return render_template('login.html')

@app.route('/api/login', methods=['POST'])
# Check the submitted password against its stored hash, then issue a fresh session.
# The random session token is an account-session identifier, not the password.
def api_login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if username in USERS and check_password_hash(USERS[username].get('password_hash', ''), password):
        session.clear()
        session['session_token'] = USERS[username]['session_token']
        session['username'] = username
        session['role'] = USERS[username]['role']
        return jsonify({'success': True, 'role': USERS[username]['role']})
    else:
        return jsonify({'success': False, 'error': 'Invalid username or password'}), 401

@app.route('/logout', methods=['POST'])
# Clearing this browser's session logs it out without changing the account.
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/api/users')
@admin_required
# Return only the fields needed by the Users panel, never authentication secrets.
def get_users():
    global USERS
    USERS = load_users()
    return jsonify({
        'users': [{'username': u, 'role': USERS[u]['role']} for u in USERS]
    })

@app.route('/api/user/add', methods=['POST'])
@admin_required
# Validate the role on the server; browser dropdowns alone cannot enforce permissions.
def add_user():
    global USERS
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')
    role = data.get('role', 'user')

    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400

    if username in USERS:
        return jsonify({'error': 'User already exists'}), 400

    if role not in ['admin', 'user', 'technology', 'readonly']:
        return jsonify({'error': 'Invalid role'}), 400

    USERS[username] = {
        'password_hash': generate_password_hash(password),
        'session_token': secrets.token_hex(32),
        'role': role,
        'created_at': datetime.datetime.now().isoformat(),
        'updated_at': datetime.datetime.now().isoformat()
    }
    save_users(USERS)
    return jsonify({'success': True})

@app.route('/api/user/<username>/edit', methods=['POST'])
@admin_required
# Changing the token on a password reset makes previously issued sessions stop working.
# Role-only changes take effect on the next request through refresh_session_user.
def edit_user(username):
    global USERS
    data = request.json
    password = data.get('password', '').strip()
    role = data.get('role', '').strip()

    if username not in USERS:
        return jsonify({'error': 'User not found'}), 404

    if password:
        USERS[username]['password_hash'] = generate_password_hash(password)
        USERS[username]['session_token'] = secrets.token_hex(32)
    if role and role in ['admin', 'user', 'technology', 'readonly']:
        USERS[username]['role'] = role

    USERS[username]['updated_at'] = datetime.datetime.now().isoformat()
    save_users(USERS)
    return jsonify({'success': True})

@app.route('/api/user/<username>/delete', methods=['POST'])
@admin_required
def delete_user(username):
    global USERS
    if username not in USERS:
        return jsonify({'error': 'User not found'}), 404

    # Don't allow deleting the current user
    if username == session.get('username'):
        return jsonify({'error': 'Cannot delete your own account'}), 400

    del USERS[username]
    save_users(USERS)
    return jsonify({'success': True})

@app.route('/api/users/export/text')
@admin_required
def export_users_text():
    if os.path.exists(USERS_LIST_FILE):
        with open(USERS_LIST_FILE, 'r') as f:
            content = f.read()
        return Response(content, mimetype='text/plain', headers={
            'Content-Disposition': 'attachment;filename=users_list.txt'
        })
    return jsonify({'error': 'User list not found'}), 404

@app.route('/api/users/export/json')
@admin_required
# Use an explicit secret exclusion here so account exports cannot restore a login session.
def export_users_json():
    global USERS
    USERS = load_users()
    return Response(
        json.dumps({name: {k: v for k, v in info.items() if k not in ('password', 'password_hash', 'session_token')} for name, info in USERS.items()}, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment;filename=users.json'}
    )

@app.route('/api/building/<building_name>/legend')
@login_required
def get_legend(building_name):
    return jsonify(load_legend(building_name))

@app.route('/api/building/<building_name>/legend/save', methods=['POST'])
@admin_required
def save_legend_api(building_name):
    data = request.json
    save_legend(building_name, data)
    return jsonify({'success': True})

@app.route('/api/building/<building_name>/notes', methods=['GET'])
@login_required
# Notes are grouped by room ID; each room holds a list of active notes.
def get_notes(building_name):
    notes_path = get_building_notes_path(building_name)
    if os.path.exists(notes_path):
        with open(notes_path, 'r') as f:
            return jsonify(json.load(f))
    return jsonify({})

@app.route('/api/building/<building_name>/notes', methods=['POST'])
@login_required
# Keep note text as data in JSON. The browser escapes it when displaying it.
# Read-only access is enforced here even if someone bypasses the page controls.
def add_note(building_name):
    if session.get('role') == 'readonly':
        return jsonify({'error': 'Permission denied'}), 403
    data = request.json
    room_id = data.get('room_id')
    text = data.get('text', '').strip()

    if not room_id or not text:
        return jsonify({'error': 'Room ID and text required'}), 400

    notes_path = get_building_notes_path(building_name)
    notes = {}

    if os.path.exists(notes_path):
        with open(notes_path, 'r') as f:
            notes = json.load(f)

    if room_id not in notes:
        notes[room_id] = []

    import datetime
    note = {
        'id': len(notes[room_id]),
        'text': text,
        'author': session.get('username'),
        'timestamp': datetime.datetime.now().isoformat(),
        'resolved': False
    }

    notes[room_id].append(note)

    building_path = get_building_path(building_name)
    os.makedirs(building_path, exist_ok=True)

    with open(notes_path, 'w') as f:
        json.dump(notes, f, indent=2)

    return jsonify({'success': True, 'note': note})

@app.route('/api/building/<building_name>/notes/<room_id>/<int:note_id>/resolve', methods=['POST'])
@admin_required
# Move a note into history with resolution details, then remove it from active notes.
# note_id is the current list position used by the UI, not a permanent database ID.
def resolve_note(building_name, room_id, note_id):
    notes_path = get_building_notes_path(building_name)
    if not os.path.exists(notes_path):
        return jsonify({'error': 'No notes found'}), 404

    with open(notes_path, 'r') as f:
        notes = json.load(f)

    if room_id not in notes or note_id >= len(notes[room_id]):
        return jsonify({'error': 'Note not found'}), 404

    note = notes[room_id][note_id]
    note['resolved'] = True
    note['resolved_at'] = datetime.datetime.now().isoformat()
    note['resolved_by'] = session.get('username')

    # Save to history
    history_path = get_building_history_path(building_name)
    history = []
    if os.path.exists(history_path):
        with open(history_path, 'r') as f:
            history = json.load(f)

    history.append(note)

    with open(history_path, 'w') as f:
        json.dump(history, f, indent=2)

    # Remove from active notes
    notes[room_id].pop(note_id)
    if not notes[room_id]:
        del notes[room_id]

    with open(notes_path, 'w') as f:
        json.dump(notes, f, indent=2)

    return jsonify({'success': True})

@app.route('/api/building/<building_name>/notes/<room_id>/<int:note_id>', methods=['DELETE'])
@admin_required
# Delete an active note outright; unlike resolving, this does not archive it.
def delete_note(building_name, room_id, note_id):
    notes_path = get_building_notes_path(building_name)
    if not os.path.exists(notes_path):
        return jsonify({'error': 'No notes found'}), 404

    with open(notes_path, 'r') as f:
        notes = json.load(f)

    if room_id not in notes or note_id >= len(notes[room_id]):
        return jsonify({'error': 'Note not found'}), 404

    notes[room_id].pop(note_id)
    if not notes[room_id]:
        del notes[room_id]

    with open(notes_path, 'w') as f:
        json.dump(notes, f, indent=2)

    return jsonify({'success': True})

@app.route('/admin')
@admin_required
# render_template sends HTML; the page's JavaScript later fetches its building data.
def admin():
    return render_template('admin.html')

@app.route('/user')
@login_required
def user():
    return render_template('user.html')

@app.route('/api/buildings')
@login_required
def get_buildings():
    return jsonify({'buildings': list_buildings()})

@app.route('/api/logo')
def get_logo():
    possible_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logo.png'),
        os.path.join(os.getcwd(), 'logo.png'),
        'logo.png'
    ]

    for logo_path in possible_paths:
        if os.path.exists(logo_path) and os.path.getsize(logo_path) > 0:
            try:
                with open(logo_path, 'rb') as f:
                    image_data = f.read()
                return Response(image_data, mimetype='image/png')
            except Exception as e:
                print(f"Error loading logo: {e}")

    return '', 404

@app.route('/api/building/<building_name>/image')
@login_required
# Return image bytes rather than JSON so the browser can draw the floor plan.
def get_building_image(building_name):
    image_path = get_building_image_path(building_name)
    if os.path.exists(image_path):
        return send_file(image_path, mimetype='image/jpeg')
    return jsonify({'error': 'Image not found'}), 404

@app.route('/api/building/<building_name>/calibration')
@login_required
def get_building_calibration_api(building_name):
    return jsonify(load_building_calibration(building_name))

@app.route('/api/building/upload', methods=['POST'])
@admin_required
# Uploads use multipart form data because the request contains an image file.
# Create a new directory exclusively: an existing name must never erase saved rooms.
def upload_building():
    building_name = request.form.get('name', '').strip()
    if not building_name:
        return jsonify({'error': 'Building name required'}), 400

    if 'image' not in request.files:
        return jsonify({'error': 'Image required'}), 400

    image_file = request.files['image']
    if not image_file:
        return jsonify({'error': 'No image'}), 400

    try:
        building_path = get_building_path(building_name)
        try:
            os.mkdir(building_path)
        except FileExistsError:
            return jsonify({'error': 'Building already exists. Choose a different name.'}), 409

        image_path = get_building_image_path(building_name)
        image_file.save(image_path)

        save_building_calibration(building_name, {})

        return jsonify({'success': True, 'building': building_name})
    except InvalidBuildingName:
        raise
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/building/<building_name>/calibration/save', methods=['POST'])
@login_required
# The browser sends its complete roomBounds object as JSON for this building.
def save_calibration(building_name):
    # Full map replacement includes geometry, so only admins may use this endpoint.
    if session.get('role') != 'admin':
        return jsonify({'error': 'Permission denied'}), 403

    data = request.json
    if not isinstance(data, dict) or any(not isinstance(room, dict) for room in data.values()):
        return jsonify({'error': 'Expected a room map'}), 400
    save_building_calibration(building_name, data)
    return jsonify({'success': True})


@app.route('/api/building/<building_name>/status', methods=['POST'])
@login_required
def save_room_status(building_name):
    # Maintenance and technology can update work status, never coordinates or room IDs.
    # Read the saved map and merge only allowed fields rather than trusting a browser copy.
    if session.get('role') not in ('admin', 'user', 'technology'):
        return jsonify({'error': 'Permission denied'}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'room_id', 'changes'}:
        return jsonify({'error': 'Expected room_id and changes'}), 400
    room_id, changes = data['room_id'], data['changes']
    if (not isinstance(room_id, str) or not isinstance(changes, dict)
            or not changes or set(changes) - {'color', 'leftConnected'}):
        return jsonify({'error': 'Only color and modifier changes are allowed'}), 400
    allowed_colors = {entry['key'] for entry in load_legend(building_name) if entry['key'] != 'modifier'}
    if 'color' in changes and (not isinstance(changes['color'], str) or changes['color'] not in allowed_colors):
        return jsonify({'error': 'Choose a status from the building legend'}), 400
    if 'leftConnected' in changes and not isinstance(changes['leftConnected'], bool):
        return jsonify({'error': 'Modifier must be true or false'}), 400
    rooms = load_building_calibration(building_name)
    if room_id not in rooms:
        return jsonify({'error': 'Room not found'}), 404
    rooms[room_id].update(changes)
    save_building_calibration(building_name, rooms)
    return jsonify({'success': True})

@app.route('/api/building/<building_name>/delete', methods=['POST'])
@admin_required
# Deleting a building removes its image, rooms, legend, notes, and history together.
# Path validation must happen before recursive deletion.
def delete_building(building_name):
    try:
        building_path = get_building_path(building_name)
        import shutil
        if os.path.exists(building_path):
            shutil.rmtree(building_path)
        return jsonify({'success': True})
    except InvalidBuildingName:
        raise
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/building/<building_name>/duplicate', methods=['POST'])
@admin_required
# Copy the whole building folder so its image and associated data travel together.
def duplicate_building(building_name):
    try:
        import shutil

        data = request.json
        new_name = data.get('new_name', '').strip()

        if not new_name:
            return jsonify({'error': 'New building name required'}), 400

        if new_name in list_buildings():
            return jsonify({'error': 'Building already exists'}), 400

        source_path = get_building_path(building_name)
        dest_path = get_building_path(new_name)

        if not os.path.exists(source_path):
            return jsonify({'error': 'Source building not found'}), 404

        shutil.copytree(source_path, dest_path)
        return jsonify({'success': True, 'building': new_name})
    except InvalidBuildingName:
        raise
    except Exception as e:
        return jsonify({'error': str(e)}), 500



# Start the local server only when executed directly, not when imported by tests.
if __name__ == '__main__':
    app.run(debug=False, port=5000, threaded=True)
