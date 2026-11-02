"""Two Truths and a Lie: a multiplayer party game for friends.

Run:  pip install -r requirements.txt && python app.py
Then open http://localhost:5000 and share the room code or link.
Game state lives in memory, so run a single process.
"""
import os
import random
import threading
import time

from flask import Flask, jsonify, request, send_from_directory

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=None)

ROOMS = {}
LOCK = threading.Lock()
MAX_PLAYERS = 12
MIN_PLAYERS = 3
POINTS = 100
MAX_LEN = 120


class GameError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


@app.errorhandler(GameError)
def handle_game_error(e):
    return jsonify(error=e.message), e.status


def new_id(n=10):
    return "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=n))


def new_code():
    while True:
        code = "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ", k=4))
        if code not in ROOMS:
            return code


def prune():
    cutoff = time.time() - 6 * 3600
    for code in [c for c, r in ROOMS.items() if r["updated"] < cutoff]:
        del ROOMS[code]


def touch(room):
    room["v"] += 1
    room["updated"] = time.time()


def clean_name(name):
    name = " ".join(str(name or "").split())[:16]
    if not name:
        raise GameError("Enter a name first.")
    return name


def get_room(code):
    room = ROOMS.get(str(code or "").upper().strip())
    if not room:
        raise GameError("Room not found. Check the code.", 404)
    return room


def get_player(room, pid):
    if pid not in room["players"]:
        raise GameError("You are not in this room.", 404)


def require_host(room, pid):
    if room["host"] != pid:
        raise GameError("Only the host can do that.", 403)


def current_presenter(room):
    return room["queue"][room["current"]]


def begin_voting(room):
    ready = [p for p in room["players"] if p in room["entries"]]
    random.shuffle(ready)
    room["queue"] = ready
    room["current"] = 0
    room["votes"] = {}
    room["gains"] = []
    room["phase"] = "voting"


def do_reveal(room):
    pres = current_presenter(room)
    lie = room["entries"][pres]["lie"]
    fooled = 0
    gains = {}
    for voter, choice in room["votes"].items():
        if choice == lie:
            gains[voter] = gains.get(voter, 0) + POINTS
        else:
            fooled += 1
    if fooled:
        gains[pres] = fooled * POINTS
    for pid, pts in gains.items():
        room["players"][pid]["score"] += pts
    room["gains"] = sorted(
        ({"name": room["players"][p]["name"], "points": pts} for p, pts in gains.items()),
        key=lambda g: -g["points"],
    )
    room["phase"] = "reveal"


def public_state(room, pid):
    phase = room["phase"]
    out = {
        "code": room["code"],
        "v": room["v"],
        "phase": phase,
        "you": pid,
        "isHost": room["host"] == pid,
        "submitted": pid in room["entries"],
        "cn": room["cn"],
        "chat": [{"name": m["name"], "text": m["text"], "me": m["pid"] == pid} for m in room["chat"][-40:]],
        "players": [
            {
                "id": i,
                "name": p["name"],
                "score": p["score"],
                "submitted": i in room["entries"],
                "isHost": i == room["host"],
                "voted": i in room["votes"],
            }
            for i, p in room["players"].items()
        ],
    }
    if phase in ("voting", "reveal"):
        pres = current_presenter(room)
        entry = room["entries"][pres]
        rnd = {
            "presenterId": pres,
            "presenterName": room["players"][pres]["name"],
            "index": room["current"] + 1,
            "total": len(room["queue"]),
            "statements": entry["statements"],
            "myVote": room["votes"].get(pid),
            "voted": len(room["votes"]),
            "eligible": len(room["players"]) - 1,
        }
        if phase == "reveal":
            rnd["lie"] = entry["lie"]
            tally = [[], [], []]
            for voter, choice in room["votes"].items():
                tally[choice].append(room["players"][voter]["name"])
            rnd["tally"] = tally
            rnd["gains"] = room["gains"]
        out["round"] = rnd
    return out


def asset(name):
    # files can sit in a "static" folder or right next to app.py
    for folder in (os.path.join(BASE, "static"), BASE):
        if os.path.exists(os.path.join(folder, name)):
            return send_from_directory(folder, name)
    return f"{name} is missing. Put it next to app.py or inside a folder named static.", 404


@app.route("/")
def index():
    return asset("index.html")


@app.route("/manifest.webmanifest")
def manifest():
    return asset("manifest.webmanifest")


@app.route("/sw.js")
def service_worker():
    resp = asset("sw.js")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/icon-<int:size>.png")
def icon_file(size):
    return asset(f"icon-{size}.png")


@app.get("/api/state")
def state():
    with LOCK:
        room = get_room(request.args.get("code"))
        pid = request.args.get("pid", "")
        get_player(room, pid)
        return jsonify(public_state(room, pid))


@app.post("/api/action")
def action():
    data = request.get_json(silent=True) or {}
    kind = data.get("type")
    with LOCK:
        prune()

        if kind == "create":
            name = clean_name(data.get("name"))
            code = new_code()
            pid = new_id()
            ROOMS[code] = {
                "code": code,
                "host": pid,
                "phase": "lobby",
                "players": {pid: {"name": name, "score": 0}},
                "entries": {},
                "queue": [],
                "current": 0,
                "votes": {},
                "gains": [],
                "chat": [],
                "cn": 0,
                "v": 0,
                "updated": time.time(),
            }
            return jsonify(code=code, pid=pid)

        if kind == "join":
            room = get_room(data.get("code"))
            name = clean_name(data.get("name"))
            for pid, p in room["players"].items():
                if p["name"].lower() == name.lower():
                    return jsonify(code=room["code"], pid=pid)  # rejoin
            if room["phase"] != "lobby":
                raise GameError("That game already started.")
            if len(room["players"]) >= MAX_PLAYERS:
                raise GameError("This room is full.")
            pid = new_id()
            room["players"][pid] = {"name": name, "score": 0}
            touch(room)
            return jsonify(code=room["code"], pid=pid)

        room = get_room(data.get("code"))
        pid = data.get("pid", "")
        get_player(room, pid)
        phase = room["phase"]

        if kind == "chat":  # chat never bumps room["v"], so game screens are not redrawn
            text = " ".join(str(data.get("text", "")).split())[:200]
            if not text:
                raise GameError("Type a message first.")
            now = time.time()
            me = room["players"][pid]
            if now - me.get("last_chat", 0) < 0.6:
                raise GameError("Slow down a little.")
            me["last_chat"] = now
            room["chat"] = (room["chat"] + [{"pid": pid, "name": me["name"], "text": text}])[-50:]
            room["cn"] += 1
            room["updated"] = now
            return jsonify(ok=True)

        if kind == "start":
            require_host(room, pid)
            if phase != "lobby":
                raise GameError("The game already started.")
            if len(room["players"]) < MIN_PLAYERS:
                raise GameError(f"You need at least {MIN_PLAYERS} players.")
            room["phase"] = "writing"
            room["entries"] = {}

        elif kind == "submit":
            if phase != "writing":
                raise GameError("It is not time to write yet.")
            if pid in room["entries"]:
                raise GameError("You already submitted.")
            raw = data.get("statements")
            lie = data.get("lie")
            if not isinstance(raw, list) or len(raw) != 3:
                raise GameError("Write three statements.")
            statements = [" ".join(str(s or "").split()) for s in raw]
            if any(not s for s in statements):
                raise GameError("Fill in all three statements.")
            if any(len(s) > MAX_LEN for s in statements):
                raise GameError(f"Keep each statement under {MAX_LEN} characters.")
            if lie not in (0, 1, 2):
                raise GameError("Mark which statement is the lie.")
            order = [0, 1, 2]
            random.shuffle(order)
            room["entries"][pid] = {
                "statements": [statements[i] for i in order],
                "lie": order.index(lie),
            }
            if len(room["entries"]) == len(room["players"]):
                begin_voting(room)

        elif kind == "begin":
            require_host(room, pid)
            if phase != "writing":
                raise GameError("Nothing to start.")
            if len(room["entries"]) < 2:
                raise GameError("At least two players need to submit first.")
            begin_voting(room)

        elif kind == "vote":
            if phase != "voting":
                raise GameError("Voting is closed.")
            if pid == current_presenter(room):
                raise GameError("You cannot vote on your own round.")
            if pid in room["votes"]:
                raise GameError("You already voted.")
            choice = data.get("choice")
            if choice not in (0, 1, 2):
                raise GameError("Pick one statement.")
            room["votes"][pid] = choice
            if len(room["votes"]) == len(room["players"]) - 1:
                do_reveal(room)

        elif kind == "reveal":
            require_host(room, pid)
            if phase != "voting":
                raise GameError("Nothing to reveal.")
            do_reveal(room)

        elif kind == "next":
            require_host(room, pid)
            if phase != "reveal":
                raise GameError("Reveal the answer first.")
            room["current"] += 1
            room["votes"] = {}
            room["gains"] = []
            room["phase"] = "final" if room["current"] >= len(room["queue"]) else "voting"

        elif kind == "again":
            require_host(room, pid)
            if phase != "final":
                raise GameError("The game is not over yet.")
            for p in room["players"].values():
                p["score"] = 0
            room.update(phase="lobby", entries={}, queue=[], current=0, votes={}, gains=[])

        else:
            raise GameError("Unknown action.")

        touch(room)
        return jsonify(ok=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
