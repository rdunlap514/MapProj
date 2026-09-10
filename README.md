# MapProj

**Interactive floor plans. Clear room statuses. A shared view of the work.**

MapProj is a free, self-hosted tool for facilities, maintenance, and technology teams. Upload a floor plan, outline rooms, and use customizable colors and notes to track work across a building. It grew out of a practical need: making room-by-room progress easier to see.

## What you can do

<a href="https://youtu.be/-dAHxD8eRYA"><img src="logo.png" alt="Watch the MapProj walkthrough" width="240"></a>

**[Watch the walkthrough on YouTube](https://youtu.be/-dAHxD8eRYA)** — logo setup, building creation, room calibration, legends, and users. See [the tutorial guide](Videos/README.md) for the individual recordings.

- Manage multiple buildings and upload floor plan images.
- Draw and adjust room boundaries with a visual editor.
- Set room statuses with customizable labels, colors, and a striped modifier.
- Zoom, pan, and selectively display room numbers.
- Add room notes; administrators can resolve or delete them.
- Manage administrator, maintenance, technology, and read-only accounts.

## Run locally

Install Python 3.12 or newer, clone or download this repository, and open a terminal in its folder:

```sh
python -m venv .venv
```

Activate the environment on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Or on macOS/Linux:

```sh
source .venv/bin/activate
```

Then install and start:

```sh
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. A fresh installation creates administrator, maintenance, technology, and viewer accounts with **random passwords printed once in the terminal**. Save those passwords privately.

For a disposable local demo, set this before the first startup in PowerShell:

```powershell
$env:MAPPROJ_DEMO_MODE = '1'
python app.py
```

On macOS/Linux, use `MAPPROJ_DEMO_MODE=1 python app.py`. This explicitly enables these **public demo accounts**:

- Administrator: `admin` / `admin123`
- Maintenance: `maintenance` / `maintenance123`
- Technology: `technology` / `technology123`
- Read-only: `viewer` / `viewer123`

These credentials are for local testing. Change every demo password in the administrator Users panel before shared use. Passwords are stored as hashes and are not included in exports. Existing installations retain their saved accounts: switching off demo mode does not replace passwords already stored.

A fresh download includes **Building1**, the fictional Demo Center floor plan with eight saved rooms and the customized legend shown in the tutorials. Select it after signing in, or upload another floor plan and define your own rooms. New buildings start with RoomState1, RoomState2, Roomstate3, and Modifier. Building images and setups are included in Git; review any added building data before publishing. Accounts remain excluded. The public version includes the MapProj logo.

## Storage and scope

MapProj uses Flask, browser canvas rendering, and local JSON files. The `buildings/` folder contains images, room boundaries, legends, notes, and resolved note history. `users.json` stores local accounts. Back these up privately.

This release is intended for local evaluation and small-team workflows. Changes are not pushed live between browsers; reload to see another user's updates. JSON writes are not coordinated for concurrent editing, so simultaneous changes can overwrite one another. Do not use multiple server workers with this storage design.

The included server binds to localhost. An optional `MAPPROJ_SECRET_KEY` environment variable keeps sessions stable across restarts; otherwise a fresh random key signs sessions on each startup. Write requests require a session-specific CSRF token, supplied automatically by the included pages. Administrators edit room boundaries; maintenance and technology users update statuses and add notes; viewers cannot write. A public internet deployment needs a separate security and deployment review, including HTTPS, login rate limiting, and tighter filesystem permissions. This release is not presented as a hardened hosted service.

## Contributing

Bug reports and focused improvements are welcome. Include steps to reproduce and use fictional or redacted floor plans in public issues. See [the test guide](tests/README.md) for verification commands.

## Project layout

- `app.py`: Flask routes, permissions, and JSON storage.
- `templates/`: login, administrator, and team pages, plus shared request protection.
- `examples/`: fictional floor plan for trying the app.
- `docs/`: room creation walkthrough.
- `tests/`: isolated backend checks and focused browser checks.
- `Videos/`: five recorded tutorials and a viewing guide.

`buildings/` contains the included building images, saved room setups, and legends. `users.json` and `users_list.txt` are created locally and ignored by Git.

## How it was built

MapProj began as a hands-on project while learning Python. I wrote parts of the code and developed it with Claude Code, which helped with much of the more complex implementation. Codex later helped prepare this release, review security, and add regression checks. The current release focuses on manual mapping; automated vision features are future work.

## License

Licensed under the MIT License. See [LICENSE](LICENSE).

## Try the demo floor plan

Upload [demo-floor-plan.png](examples/demo-floor-plan.png), a fictional eight-room building generated for this project. Follow [the room creation walkthrough](docs/ROOM_WALKTHROUGH.md) to trace rooms and capture your own demo.
