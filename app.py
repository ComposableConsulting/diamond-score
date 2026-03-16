"""
Baseball Scorekeeper - Flask Backend
=====================================
This is the main server file. Flask is a Python web framework that lets us
respond to browser requests. Every function decorated with @app.route()
handles a specific URL that the browser visits or sends data to.
"""

from flask import Flask, render_template, request, jsonify, send_file
import sqlite3
import json
import os
from datetime import datetime
import csv
import io

# Create the Flask app. __name__ tells Flask where to find templates/static files.
app = Flask(__name__)

# The database file lives right next to this script
DB_PATH = os.path.join(os.path.dirname(__file__), "games.db")


# ---------------------------------------------------------------------------
# DATABASE SETUP
# ---------------------------------------------------------------------------

def get_db():
    """Open a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # lets us access columns by name, not index
    return conn


def init_db():
    """
    Create all tables if they don't exist yet.
    This runs once when the server starts.
    """
    conn = get_db()
    c = conn.cursor()

    # One row per game
    c.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            home_team   TEXT    NOT NULL,
            away_team   TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            location    TEXT,
            state       TEXT    NOT NULL DEFAULT 'active',
            created_at  TEXT    NOT NULL
        )
    """)

    # The full game state stored as JSON (score, inning, outs, count, etc.)
    # Storing as JSON makes it easy to sync to all devices in one payload
    c.execute("""
        CREATE TABLE IF NOT EXISTS game_state (
            game_id     INTEGER PRIMARY KEY,
            state_json  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL,
            FOREIGN KEY (game_id) REFERENCES games(id)
        )
    """)

    # One row per player per team per game
    c.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id     INTEGER NOT NULL,
            team        TEXT    NOT NULL,  -- 'home' or 'away'
            batting_order INTEGER NOT NULL,
            name        TEXT    NOT NULL,
            position    TEXT,
            FOREIGN KEY (game_id) REFERENCES games(id)
        )
    """)

    # Every pitch thrown, for pitch count tracking
    c.execute("""
        CREATE TABLE IF NOT EXISTS pitches (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id     INTEGER NOT NULL,
            inning      INTEGER NOT NULL,
            half        TEXT    NOT NULL,  -- 'top' or 'bottom'
            pitcher_name TEXT   NOT NULL,
            pitcher_team TEXT   NOT NULL,
            result      TEXT    NOT NULL,  -- 'ball', 'strike', 'foul', 'hit', 'out'
            timestamp   TEXT    NOT NULL,
            FOREIGN KEY (game_id) REFERENCES games(id)
        )
    """)

    # Hit location data for spray chart (x,y are percentages 0-100 of field diagram)
    c.execute("""
        CREATE TABLE IF NOT EXISTS hit_locations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id     INTEGER NOT NULL,
            inning      INTEGER NOT NULL,
            half        TEXT    NOT NULL,
            batter_name TEXT    NOT NULL,
            batter_team TEXT    NOT NULL,
            hit_type    TEXT    NOT NULL,  -- 'single','double','triple','hr','out'
            x_pct       REAL    NOT NULL,  -- 0-100
            y_pct       REAL    NOT NULL,  -- 0-100
            timestamp   TEXT    NOT NULL,
            FOREIGN KEY (game_id) REFERENCES games(id)
        )
    """)

    # Detailed pitch location tracking — zone 1-9 (3x3 grid), pitch type, result
    c.execute("""
        CREATE TABLE IF NOT EXISTS pitch_locations (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id      INTEGER NOT NULL,
            inning       INTEGER NOT NULL,
            half         TEXT    NOT NULL,
            pitcher_name TEXT    NOT NULL,
            batter_name  TEXT,
            pitch_type   TEXT    NOT NULL,  -- 'fastball','curveball','changeup','slider','sinker'
            zone         INTEGER NOT NULL,  -- 1-9 (3x3 grid, 1=top-left, 9=bottom-right)
            x_pct        REAL    NOT NULL,  -- exact tap position 0-100
            y_pct        REAL    NOT NULL,
            result       TEXT    NOT NULL,  -- 'ball','called_strike','swinging_strike','foul','hit'
            pitch_num    INTEGER NOT NULL,  -- pitch number in the game
            timestamp    TEXT    NOT NULL,
            FOREIGN KEY (game_id) REFERENCES games(id)
        )
    """)

    conn.commit()
    conn.close()


def default_game_state(game_id, home_team, away_team):
    """
    Return the initial state dictionary for a new game.
    This is the single source of truth that all devices sync from.
    """
    return {
        "game_id": game_id,
        "home_team": home_team,
        "away_team": away_team,
        "home_score": 0,
        "away_score": 0,
        "inning": 1,
        "half": "top",        # 'top' = away batting, 'bottom' = home batting
        "outs": 0,
        "balls": 0,
        "strikes": 0,
        "current_batter_idx": {"top": 0, "bottom": 0},
        "current_pitcher": {"top": "", "bottom": ""},
        "runners": {"first": None, "second": None, "third": None},
        "inning_scores": {},  # {"1_top": 0, "1_bottom": 2, ...}
        "game_over": False,
        "version": 1          # increments on every change so clients can detect staleness
    }


# ---------------------------------------------------------------------------
# ROUTES - PAGES
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Homepage: list of all games."""
    conn = get_db()
    games = conn.execute(
        "SELECT * FROM games ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return render_template("index.html", games=games)


@app.route("/game/<int:game_id>")
def game(game_id):
    """The live scorecard page for a specific game."""
    conn = get_db()
    g = conn.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    players = conn.execute(
        "SELECT * FROM players WHERE game_id=? ORDER BY team, batting_order",
        (game_id,)
    ).fetchall()
    conn.close()
    if not g:
        return "Game not found", 404
    home_players = [dict(p) for p in players if p["team"] == "home"]
    away_players = [dict(p) for p in players if p["team"] == "away"]
    return render_template("game.html", game=g,
                           home_players=home_players,
                           away_players=away_players)


@app.route("/history")
def history():
    """All completed games with summary stats."""
    conn = get_db()
    games = conn.execute(
        "SELECT * FROM games ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return render_template("history.html", games=games)


# ---------------------------------------------------------------------------
# API ROUTES - JSON endpoints called by JavaScript
# ---------------------------------------------------------------------------

@app.route("/api/games", methods=["POST"])
def create_game():
    """Create a new game and return its id."""
    data = request.json
    now = datetime.now().isoformat()
    conn = get_db()
    c = conn.cursor()

    c.execute(
        "INSERT INTO games (home_team, away_team, date, location, state, created_at) VALUES (?,?,?,?,?,?)",
        (data["home_team"], data["away_team"], data.get("date", now[:10]),
         data.get("location", ""), "active", now)
    )
    game_id = c.lastrowid

    # Insert players
    for p in data.get("home_players", []):
        c.execute(
            "INSERT INTO players (game_id, team, batting_order, name, position) VALUES (?,?,?,?,?)",
            (game_id, "home", p["order"], p["name"], p.get("position", ""))
        )
    for p in data.get("away_players", []):
        c.execute(
            "INSERT INTO players (game_id, team, batting_order, name, position) VALUES (?,?,?,?,?)",
            (game_id, "away", p["order"], p["name"], p.get("position", ""))
        )

    # Set initial pitcher names
    home_pitcher = next((p["name"] for p in data.get("home_players", []) if p.get("position") == "P"), "")
    away_pitcher = next((p["name"] for p in data.get("away_players", []) if p.get("position") == "P"), "")

    state = default_game_state(game_id, data["home_team"], data["away_team"])
    state["current_pitcher"]["top"] = home_pitcher    # home pitches in top (away bats)
    state["current_pitcher"]["bottom"] = away_pitcher  # away pitches in bottom (home bats)

    c.execute(
        "INSERT INTO game_state (game_id, state_json, updated_at) VALUES (?,?,?)",
        (game_id, json.dumps(state), now)
    )
    conn.commit()
    conn.close()
    return jsonify({"game_id": game_id})


@app.route("/api/games/<int:game_id>/state")
def get_state(game_id):
    """Return the current game state. Clients poll this to stay in sync."""
    conn = get_db()
    row = conn.execute(
        "SELECT state_json, updated_at FROM game_state WHERE game_id=?",
        (game_id,)
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "not found"}), 404
    state = json.loads(row["state_json"])
    state["updated_at"] = row["updated_at"]
    return jsonify(state)


@app.route("/api/games/<int:game_id>/action", methods=["POST"])
def game_action(game_id):
    """
    Handle a scoring action. The browser sends an action name and we update
    the game state accordingly. This is the core game logic.
    """
    data = request.json
    action = data.get("action")
    now = datetime.now().isoformat()

    conn = get_db()
    row = conn.execute(
        "SELECT state_json FROM game_state WHERE game_id=?", (game_id,)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "game not found"}), 404

    state = json.loads(row["state_json"])
    players = conn.execute(
        "SELECT * FROM players WHERE game_id=? ORDER BY batting_order",
        (game_id,)
    ).fetchall()

    half = state["half"]
    batting_team = "away" if half == "top" else "home"
    fielding_team = "home" if half == "top" else "away"
    score_key = f"{batting_team}_score"

    def current_batter_name():
        team_players = [p for p in players if p["team"] == batting_team]
        if not team_players:
            return "Unknown"
        idx = state["current_batter_idx"][half] % len(team_players)
        return team_players[idx]["name"]

    def next_batter():
        team_players = [p for p in players if p["team"] == batting_team]
        if team_players:
            state["current_batter_idx"][half] = (
                state["current_batter_idx"][half] + 1
            ) % len(team_players)
        state["balls"] = 0
        state["strikes"] = 0

    def record_pitch(result):
        pitcher = state["current_pitcher"][half]
        conn.execute(
            "INSERT INTO pitches (game_id, inning, half, pitcher_name, pitcher_team, result, timestamp) VALUES (?,?,?,?,?,?,?)",
            (game_id, state["inning"], half, pitcher, fielding_team, result, now)
        )

    def end_half_inning():
        state["outs"] = 0
        state["balls"] = 0
        state["strikes"] = 0
        state["runners"] = {"first": None, "second": None, "third": None}
        if half == "top":
            state["half"] = "bottom"
        else:
            state["inning"] += 1
            state["half"] = "top"
            if state["inning"] > 7:  # JV games often 7 innings
                state["game_over"] = True

    # ---- Action handlers ----

    if action == "ball":
        record_pitch("ball")
        state["balls"] += 1
        if state["balls"] >= 4:  # walk
            batter = current_batter_name()
            # Advance runners if forced
            if state["runners"]["third"] and state["runners"]["second"] and state["runners"]["first"]:
                state[score_key] += 1
                key = f"{state['inning']}_{half}"
                state["inning_scores"][key] = state["inning_scores"].get(key, 0) + 1
            if state["runners"]["second"] and state["runners"]["first"]:
                state["runners"]["third"] = state["runners"]["second"]
            if state["runners"]["first"]:
                state["runners"]["second"] = state["runners"]["first"]
            state["runners"]["first"] = batter
            next_batter()

    elif action == "strike":
        record_pitch("strike")
        state["strikes"] += 1
        if state["strikes"] >= 3:  # strikeout
            state["outs"] += 1
            next_batter()
            if state["outs"] >= 3:
                end_half_inning()

    elif action == "foul":
        record_pitch("foul")
        if state["strikes"] < 2:
            state["strikes"] += 1

    elif action == "out":
        record_pitch("out")
        state["outs"] += 1
        next_batter()
        if state["outs"] >= 3:
            end_half_inning()

    elif action == "single":
        record_pitch("hit")
        batter = current_batter_name()
        # Score runners from 2nd and 3rd
        for base in ["third", "second"]:
            if state["runners"][base]:
                state[score_key] += 1
                key = f"{state['inning']}_{half}"
                state["inning_scores"][key] = state["inning_scores"].get(key, 0) + 1
                state["runners"][base] = None
        state["runners"]["second"] = state["runners"].get("first")
        state["runners"]["first"] = batter
        next_batter()

    elif action == "double":
        record_pitch("hit")
        batter = current_batter_name()
        for base in ["third", "second", "first"]:
            if state["runners"][base]:
                state[score_key] += 1
                key = f"{state['inning']}_{half}"
                state["inning_scores"][key] = state["inning_scores"].get(key, 0) + 1
                state["runners"][base] = None
        state["runners"]["second"] = batter
        next_batter()

    elif action == "triple":
        record_pitch("hit")
        batter = current_batter_name()
        for base in ["third", "second", "first"]:
            if state["runners"][base]:
                state[score_key] += 1
                key = f"{state['inning']}_{half}"
                state["inning_scores"][key] = state["inning_scores"].get(key, 0) + 1
                state["runners"][base] = None
        state["runners"]["third"] = batter
        next_batter()

    elif action == "homerun":
        record_pitch("hit")
        batter = current_batter_name()
        runs = 1
        for base in ["third", "second", "first"]:
            if state["runners"][base]:
                runs += 1
                state["runners"][base] = None
        state[score_key] += runs
        key = f"{state['inning']}_{half}"
        state["inning_scores"][key] = state["inning_scores"].get(key, 0) + runs
        next_batter()

    elif action == "end_inning":
        end_half_inning()

    elif action == "end_game":
        state["game_over"] = True
        conn.execute("UPDATE games SET state='completed' WHERE id=?", (game_id,))

    elif action == "change_pitcher":
        new_pitcher = data.get("pitcher_name", "")
        state["current_pitcher"][half] = new_pitcher

    elif action == "undo":
        # Simple undo: just reset the count, not full event sourcing in v1
        state["balls"] = 0
        state["strikes"] = 0

    state["version"] = state.get("version", 1) + 1

    conn.execute(
        "UPDATE game_state SET state_json=?, updated_at=? WHERE game_id=?",
        (json.dumps(state), now, game_id)
    )
    conn.commit()
    conn.close()
    return jsonify(state)


@app.route("/api/games/<int:game_id>/hit", methods=["POST"])
def record_hit(game_id):
    """Record a hit location for the spray chart."""
    data = request.json
    now = datetime.now().isoformat()
    conn = get_db()
    row = conn.execute(
        "SELECT state_json FROM game_state WHERE game_id=?", (game_id,)
    ).fetchone()
    state = json.loads(row["state_json"])
    half = state["half"]
    batting_team = "away" if half == "top" else "home"
    players = conn.execute(
        "SELECT * FROM players WHERE game_id=? AND team=? ORDER BY batting_order",
        (game_id, batting_team)
    ).fetchall()
    idx = state["current_batter_idx"][half] % max(len(players), 1)
    batter = players[idx]["name"] if players else "Unknown"

    conn.execute(
        "INSERT INTO hit_locations (game_id, inning, half, batter_name, batter_team, hit_type, x_pct, y_pct, timestamp) VALUES (?,?,?,?,?,?,?,?,?)",
        (game_id, state["inning"], half, batter, batting_team,
         data["hit_type"], data["x"], data["y"], now)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/games/<int:game_id>/hits")
def get_hits(game_id):
    """Return all hit locations for a game (for spray chart)."""
    conn = get_db()
    hits = conn.execute(
        "SELECT * FROM hit_locations WHERE game_id=? ORDER BY timestamp",
        (game_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(h) for h in hits])


@app.route("/api/games/<int:game_id>/pitches")
def get_pitches(game_id):
    """Return pitch counts grouped by pitcher."""
    conn = get_db()
    rows = conn.execute(
        "SELECT pitcher_name, pitcher_team, COUNT(*) as total, "
        "SUM(CASE WHEN result='strike' THEN 1 ELSE 0 END) as strikes, "
        "SUM(CASE WHEN result='ball' THEN 1 ELSE 0 END) as balls "
        "FROM pitches WHERE game_id=? GROUP BY pitcher_name, pitcher_team",
        (game_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/games/<int:game_id>/export/csv")
def export_csv(game_id):
    """Export game summary as CSV."""
    conn = get_db()
    game = conn.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    state = json.loads(conn.execute(
        "SELECT state_json FROM game_state WHERE game_id=?", (game_id,)
    ).fetchone()["state_json"])
    pitches = conn.execute(
        "SELECT * FROM pitches WHERE game_id=? ORDER BY timestamp", (game_id,)
    ).fetchall()
    hits = conn.execute(
        "SELECT * FROM hit_locations WHERE game_id=? ORDER BY timestamp", (game_id,)
    ).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["GAME SUMMARY"])
    writer.writerow(["Home", game["home_team"], "Away", game["away_team"]])
    writer.writerow(["Date", game["date"], "Location", game["location"]])
    writer.writerow(["Final Score", f"{game['home_team']}: {state['home_score']}",
                     f"{game['away_team']}: {state['away_score']}"])
    writer.writerow([])

    writer.writerow(["PITCH LOG"])
    writer.writerow(["Inning", "Half", "Pitcher", "Team", "Result", "Time"])
    for p in pitches:
        writer.writerow([p["inning"], p["half"], p["pitcher_name"],
                         p["pitcher_team"], p["result"], p["timestamp"]])
    writer.writerow([])

    writer.writerow(["HIT LOCATIONS"])
    writer.writerow(["Inning", "Half", "Batter", "Team", "Type", "X%", "Y%"])
    for h in hits:
        writer.writerow([h["inning"], h["half"], h["batter_name"],
                         h["batter_team"], h["hit_type"], h["x_pct"], h["y_pct"]])

    output.seek(0)
    return send_file(
        io.BytesIO(output.read().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"game_{game_id}_{game['date']}.csv"
    )


# ---------------------------------------------------------------------------
# PITCH LOCATION TRACKING
# ---------------------------------------------------------------------------

@app.route("/pitch/<int:game_id>")
def pitch_tracker(game_id):
    """Dedicated pitch location tracking page — runs on a second tablet."""
    conn = get_db()
    g = conn.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
    conn.close()
    if not g:
        return "Game not found", 404
    return render_template("pitch_tracker.html", game=dict(g))


@app.route("/api/games/<int:game_id>/pitch_location", methods=["POST"])
def record_pitch_location(game_id):
    """Record a single pitch location with type and result."""
    data = request.json
    now = datetime.now().isoformat()
    conn = get_db()

    # Get current game state for inning/half/pitcher context
    row = conn.execute(
        "SELECT state_json FROM game_state WHERE game_id=?", (game_id,)
    ).fetchone()
    state = json.loads(row["state_json"])

    half = state["half"]
    fielding_team = "home" if half == "top" else "away"

    # Get current batter name
    players = conn.execute(
        "SELECT * FROM players WHERE game_id=? ORDER BY batting_order",
        (game_id,)
    ).fetchall()
    batting_team = "away" if half == "top" else "home"
    team_players = [p for p in players if p["team"] == batting_team]
    idx = state["current_batter_idx"][half] % max(len(team_players), 1)
    batter = team_players[idx]["name"] if team_players else "Unknown"

    # Count total pitches this game for pitch_num
    count_row = conn.execute(
        "SELECT COUNT(*) as c FROM pitch_locations WHERE game_id=?", (game_id,)
    ).fetchone()
    pitch_num = count_row["c"] + 1

    conn.execute(
        """INSERT INTO pitch_locations
           (game_id, inning, half, pitcher_name, batter_name, pitch_type,
            zone, x_pct, y_pct, result, pitch_num, timestamp)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (game_id, state["inning"], half,
         state["current_pitcher"][half], batter,
         data["pitch_type"], data["zone"],
         data["x"], data["y"], data["result"],
         pitch_num, now)
    )
    conn.commit()

    # Return updated stats for this pitcher
    stats = conn.execute(
        """SELECT zone, result, COUNT(*) as cnt
           FROM pitch_locations
           WHERE game_id=? AND pitcher_name=?
           GROUP BY zone, result""",
        (game_id, state["current_pitcher"][half])
    ).fetchall()
    conn.close()
    return jsonify({
        "ok": True,
        "pitch_num": pitch_num,
        "stats": [dict(s) for s in stats]
    })


@app.route("/api/games/<int:game_id>/pitch_locations")
def get_pitch_locations(game_id):
    """Return all pitch locations, optionally filtered by pitcher."""
    pitcher = request.args.get("pitcher")
    conn = get_db()
    if pitcher:
        rows = conn.execute(
            "SELECT * FROM pitch_locations WHERE game_id=? AND pitcher_name=? ORDER BY pitch_num",
            (game_id, pitcher)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM pitch_locations WHERE game_id=? ORDER BY pitch_num",
            (game_id,)
        ).fetchall()

    # Also return zone summary (count per zone per result)
    zone_summary = conn.execute(
        """SELECT pitcher_name, pitch_type, zone, result, COUNT(*) as cnt
           FROM pitch_locations WHERE game_id=?
           GROUP BY pitcher_name, pitch_type, zone, result""",
        (game_id,)
    ).fetchall()

    # Pitcher list
    pitchers = conn.execute(
        "SELECT DISTINCT pitcher_name FROM pitch_locations WHERE game_id=?",
        (game_id,)
    ).fetchall()

    conn.close()
    return jsonify({
        "pitches": [dict(r) for r in rows],
        "zone_summary": [dict(z) for z in zone_summary],
        "pitchers": [p["pitcher_name"] for p in pitchers]
    })


@app.route("/api/games/<int:game_id>/pitch_locations/<int:pitch_id>", methods=["DELETE"])
def delete_pitch_location(game_id, pitch_id):
    """Delete a pitch — for correcting mistakes."""
    conn = get_db()
    conn.execute(
        "DELETE FROM pitch_locations WHERE id=? AND game_id=?",
        (pitch_id, game_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    print("\n" + "="*50)
    print(" Baseball Scorekeeper is running!")
    print(" Open your browser to: http://localhost:5000")
    print(" Other devices on your hotspot: http://<your-ip>:5000")
    print("="*50 + "\n")
    # host='0.0.0.0' makes the server visible to other devices on the same network
    app.run(host="0.0.0.0", port=5000, debug=True)
