# Diamond Score ⚾
**Baseball scorekeeping app — no paper, no pencil.**

Built with Python + Flask. Works on any phone, tablet, or laptop.
Supports real-time sync across multiple devices over a local hotspot.

---

## Setup (do this once)

### 1. Make sure Python is installed
Open Terminal and type:
```
python3 --version
```
You should see something like `Python 3.11.x`. If not, download Python from python.org.

### 2. Install Flask
```
pip3 install flask
```

### 3. Run the app
Navigate to this folder in Terminal, then:
```
python3 app.py
```

You'll see:
```
==================================================
 Baseball Scorekeeper is running!
 Open your browser to: http://localhost:5000
 Other devices on your hotspot: http://<your-ip>:5000
==================================================
```

### 4. Open it in your browser
Go to: **http://localhost:5000**

---

## Using it at the field (multi-device)

1. Turn on your phone's **Personal Hotspot**
2. Run the app on a laptop connected to that hotspot:
   ```
   python3 app.py
   ```
3. Find your laptop's IP address:
   - Mac: System Settings → Wi-Fi → Details → IP Address
   - Windows: Run `ipconfig` in Command Prompt, look for "IPv4 Address"
4. On the coach's phone or iPad, open the browser and go to:
   **http://[your-laptop-ip]:5000**
5. Both devices will see the same live score, updated every 2 seconds.

### Install as an app on iPhone/iPad
1. Open Safari and go to the game URL
2. Tap the Share button (box with arrow)
3. Tap "Add to Home Screen"
4. Tap "Add" — it now acts like a native app

---

## Features
- Live score & inning tracker with linescore
- Ball/Strike/Out count with visual indicators
- Batting order with automatic rotation
- Pitch count tracking per pitcher
- Hit spray chart (tap the field to record hit locations)
- Game history
- Export game summary to CSV
- Real-time sync across devices on same network
- Works offline (last state stays visible if connection drops)

---

## How the code works (learning guide)

**app.py** — The Python server. Flask handles every URL.
- `@app.route("/")` → serves the homepage
- `@app.route("/api/games/<id>/action", methods=["POST"])` → processes scoring actions
- SQLite stores all data in `games.db` (created automatically)

**templates/** — HTML files with Jinja2 templating (Python fills in the data)
- `base.html` → shared nav, styles, and PWA setup
- `index.html` → homepage + new game form
- `game.html` → live scorecard (the main interface)
- `history.html` → past games

**static/**
- `manifest.json` → tells browsers this is a PWA
- `sw.js` → service worker, enables offline mode

**The core loop** (understand this and you understand the whole app):
1. Scorekeeper taps a button (e.g. "Strike")
2. JavaScript sends a POST request to `/api/games/1/action` with `{"action": "strike"}`
3. Flask receives it, updates the game state in SQLite, returns the new state as JSON
4. JavaScript receives the JSON and updates the scoreboard display
5. Other devices polling every 2 seconds also get the new state
---

## Next steps (v2 ideas)
- Player stats across the season (batting average, ERA)
- Push notifications when a run scores
- PDF export with spray chart image
- Season standings page
- Pitch velocity integration with your radar detector app
