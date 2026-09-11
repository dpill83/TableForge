#!/usr/bin/env python3
"""TableForge: an authenticated, persistent text relay. Python standard library only."""
import argparse
import hashlib
import json
import os
import re
import secrets
import socket
import sqlite3
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from words import WORDS

MAX_TEXT = 50_000
MAX_BODY = 310_000  # Allows JSON escaping of MAX_TEXT characters.
SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS tables (code TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS actors (
 id TEXT PRIMARY KEY, table_code TEXT NOT NULL REFERENCES tables(code),
 name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('dm','player')),
 token_hash TEXT NOT NULL UNIQUE, UNIQUE(table_code,name));
CREATE TABLE IF NOT EXISTS scenes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, table_code TEXT NOT NULL REFERENCES tables(code),
 text TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS scenes_table ON scenes(table_code,id);
CREATE TABLE IF NOT EXISTS replies (
 id INTEGER PRIMARY KEY AUTOINCREMENT, scene_id INTEGER NOT NULL REFERENCES scenes(id),
 actor_id TEXT NOT NULL REFERENCES actors(id), text TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS replies_scene ON replies(scene_id,id);
CREATE TABLE IF NOT EXISTS requests (
 actor_id TEXT NOT NULL REFERENCES actors(id), request_id TEXT NOT NULL,
 payload_hash TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(actor_id,request_id));
"""


def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def initialize(path):
    Path(path).resolve().parent.mkdir(parents=True, exist_ok=True)
    db = connect(path)
    try:
        db.executescript(SCHEMA)
    finally:
        db.close()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def new_table_code(db):
    used = {row[0] for row in db.execute("SELECT code FROM tables")}
    available = [word for word in WORDS if word not in used]
    if not available:
        raise ValueError("All table words are in use. Add more words to words.py.")
    return secrets.choice(available)


def new_passphrase(db):
    used = {row[0] for row in db.execute("SELECT token_hash FROM actors")}
    available = [f"{first}-{second}" for first in WORDS for second in WORDS
                 if digest(f"{first}-{second}") not in used]
    if not available:
        raise ValueError("All participant passphrases are in use. Add more words to words.py.")
    return secrets.choice(available)


def create_table(path, name, players):
    if not name.strip() or len(name) > 80:
        raise ValueError("Table name must contain 1–80 characters.")
    names = ["AI-DM"] + [p.strip() for p in players]
    if len(names) < 2 or len(names) > 21:
        raise ValueError("Provide between 1 and 20 player names.")
    if any(not n or len(n) > 60 or any(ord(c) < 32 for c in n) for n in names):
        raise ValueError("Each name must contain 1–60 characters without control characters.")
    if len(set(n.casefold() for n in names)) != len(names):
        raise ValueError("Player names must be unique and cannot be AI-DM.")
    initialize(path)
    keys = []
    db = connect(path)
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            code = new_table_code(db)
            db.execute("INSERT INTO tables VALUES (?,?)", (code, name.strip()))
            for index, actor_name in enumerate(names):
                token = new_passphrase(db)
                role = "dm" if index == 0 else "player"
                db.execute("INSERT INTO actors VALUES (?,?,?,?,?)",
                           (secrets.token_hex(16), code, actor_name, role, digest(token)))
                keys.append({"name": actor_name, "role": role, "key": token})
    finally:
        db.close()
    return {"table_code": code, "table_name": name.strip(), "credentials": keys}


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class RelayHandler(BaseHTTPRequestHandler):
    server_version = "TableForge/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, fmt, *args):
        # Do not log keys, message text, request URLs, or table codes.
        pass

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        db = None
        try:
            url = urlsplit(self.path)
            if url.path == "/health" and method == "GET":
                self.send_json(200, {"ok": True, "service": "tableforge", "api_version": 1})
                return
            match = re.fullmatch(r"/v1/tables/([a-z]+|[a-f0-9]{10})/(state|scenes|replies)", url.path)
            if not match:
                raise APIError(404, "Endpoint not found.")
            code, action = match.groups()
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer ") or len(auth) > 256:
                raise APIError(401, "A valid table key is required.")
            db = connect(self.server.db_path)
            actor = db.execute("SELECT * FROM actors WHERE table_code=? AND token_hash=?",
                               (code, digest(auth[7:]))).fetchone()
            if actor is None:
                raise APIError(401, "Table code or key is incorrect.")
            if method == "GET" and action == "state":
                # One consistent read snapshot, including scene, replies and counts.
                db.execute("BEGIN")
                self.send_json(200, self.state(db, code, actor, parse_qs(url.query)))
            elif method == "POST" and action in ("scenes", "replies"):
                self.send_json(200, self.write(db, code, actor, action, self.read_body()))
            else:
                raise APIError(405, "Method not allowed.")
        except APIError as exc:
            self.send_json(exc.status, {"error": exc.message})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except sqlite3.Error:
            self.send_json(503, {"error": "Storage unavailable. Retry the same request."})
        except Exception:
            self.send_json(500, {"error": "Relay error. Retry the same request."})
        finally:
            if db is not None:
                db.close()

    def read_body(self):
        if self.headers.get("Transfer-Encoding"):
            raise APIError(400, "Chunked requests are not supported.")
        if self.headers.get_content_type() != "application/json":
            raise APIError(415, "Use application/json.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise APIError(400, "Invalid Content-Length.")
        if not 0 < length <= MAX_BODY:
            raise APIError(413, "Request body is empty or too large.")
        try:
            body = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeError):
            raise APIError(400, "Invalid JSON.")
        if not isinstance(body, dict):
            raise APIError(400, "JSON must be an object.")
        return body

    def state(self, db, code, actor, query):
        table = dict(db.execute("SELECT * FROM tables WHERE code=?", (code,)).fetchone())
        scenes = [dict(row) for row in db.execute(
            "SELECT id, substr(text,1,90) AS preview, created_at FROM scenes "
            "WHERE table_code=? ORDER BY id DESC LIMIT 50", (code,))]
        raw_id = query.get("scene_id", [None])[0]
        if raw_id is not None:
            if not re.fullmatch(r"[1-9][0-9]{0,17}", raw_id):
                raise APIError(400, "Invalid scene_id.")
            scene_id = int(raw_id)
        else:
            scene_id = scenes[0]["id"] if scenes else None
        scene = None
        replies = []
        if scene_id is not None:
            row = db.execute("SELECT * FROM scenes WHERE table_code=? AND id=?", (code, scene_id)).fetchone()
            if row is None:
                raise APIError(404, "Scene not found in this table.")
            scene = dict(row)
            sql = ("SELECT r.id,r.scene_id,r.actor_id,a.name,r.text,r.created_at "
                   "FROM replies r JOIN actors a ON a.id=r.actor_id WHERE r.scene_id=?")
            args = [scene_id]
            if actor["role"] != "dm":
                sql += " AND r.actor_id=?"
                args.append(actor["id"])
            replies = [dict(r) for r in db.execute(sql + " ORDER BY r.id", args)]
        # Counts reflect only data this actor may read. They help the DM spot late replies.
        for summary in scenes:
            sql = "SELECT count(*) FROM replies WHERE scene_id=?"
            args = [summary["id"]]
            if actor["role"] != "dm":
                sql += " AND actor_id=?"
                args.append(actor["id"])
            summary["reply_count"] = db.execute(sql, args).fetchone()[0]
        return {"api_version": 1, "table": table,
                "actor": {k: actor[k] for k in ("id", "name", "role")},
                "scenes": scenes, "scene": scene, "replies": replies}

    def write(self, db, code, actor, action, body):
        expected_role = "dm" if action == "scenes" else "player"
        if actor["role"] != expected_role:
            raise APIError(403, "This key cannot perform that action.")
        expected_fields = {"request_id", "text"} | ({"scene_id"} if action == "replies" else set())
        if set(body) != expected_fields:
            raise APIError(400, "Request has missing or unexpected fields.")
        request_id = body.get("request_id")
        text = body.get("text")
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", request_id):
            raise APIError(400, "request_id must be 16–80 letters, numbers, underscores or hyphens.")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT or "\x00" in text:
            raise APIError(400, "Text must contain 1–50,000 characters and no null bytes.")
        scene_id = body.get("scene_id")
        if action == "replies" and (type(scene_id) is not int or not 0 < scene_id < 10**18):
            raise APIError(400, "scene_id must be a positive integer.")
        payload_hash = digest(json.dumps([action, body], sort_keys=True, ensure_ascii=True))
        with db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM requests WHERE actor_id=? AND request_id=?",
                                  (actor["id"], request_id)).fetchone()
            if previous:
                if previous["payload_hash"] != payload_hash:
                    raise APIError(409, "This request_id was already used for different content.")
                return {**json.loads(previous["result"]), "replayed": True}
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if action == "scenes":
                cursor = db.execute("INSERT INTO scenes(table_code,text,created_at) VALUES (?,?,?)",
                                    (code, text, stamp))
                result = {"id": cursor.lastrowid, "kind": "scene", "created_at": stamp}
            else:
                if not db.execute("SELECT 1 FROM scenes WHERE id=? AND table_code=?", (scene_id, code)).fetchone():
                    raise APIError(404, "Scene not found in this table.")
                cursor = db.execute("INSERT INTO replies(scene_id,actor_id,text,created_at) VALUES (?,?,?,?)",
                                    (scene_id, actor["id"], text, stamp))
                result = {"id": cursor.lastrowid, "scene_id": scene_id, "kind": "reply", "created_at": stamp}
            db.execute("INSERT INTO requests VALUES (?,?,?,?)",
                       (actor["id"], request_id, payload_hash, json.dumps(result)))
            return {**result, "replayed": False}


def make_server(path, host="127.0.0.1", port=8787):
    initialize(path)
    server = ThreadingHTTPServer((host, port), RelayHandler)
    server.daemon_threads = True
    server.db_path = str(path)
    return server


def lan_addresses():
    """Find local IPv4 addresses without sending network traffic."""
    addresses = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if not address.startswith(("127.", "169.254.")) and address != "0.0.0.0":
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("TABLEFORGE_DB", "tableforge.sqlite3"))
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Create a table and print its keys once.")
    create.add_argument("--name", required=True)
    create.add_argument("--players", nargs="+", required=True)
    serve = commands.add_parser("serve", help="Run the relay.")
    serve.add_argument("--host", default="0.0.0.0",
                       help="Address to listen on (default: 0.0.0.0 for LAN access).")
    serve.add_argument("--port", type=int, default=8787)
    rotate = commands.add_parser("rotate-key", help="Revoke a participant's old key and print a new one.")
    rotate.add_argument("--table", required=True)
    rotate.add_argument("--name", required=True)
    args = parser.parse_args()
    # The database, WAL and console-key redirections default to owner-only files.
    os.umask(0o077)
    if args.command == "create":
        try:
            print(json.dumps(create_table(args.db, args.name, args.players), indent=2))
        except ValueError as exc:
            parser.error(str(exc))
    elif args.command == "rotate-key":
        initialize(args.db)
        db = connect(args.db)
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                token = new_passphrase(db)
                changed = db.execute("UPDATE actors SET token_hash=? WHERE table_code=? AND name=?",
                                     (digest(token), args.table, args.name)).rowcount
            if not changed:
                parser.error("Participant not found.")
            print(json.dumps({"table_code": args.table, "name": args.name, "key": token}, indent=2))
        except ValueError as exc:
            parser.error(str(exc))
        finally:
            db.close()
    else:
        server = make_server(args.db, args.host, args.port)
        print(f"TableForge listening on {args.host}:{server.server_port}", flush=True)
        if args.host == "0.0.0.0":
            addresses = lan_addresses()
            for address in addresses:
                print(f"LAN URL: http://{address}:{server.server_port}", flush=True)
            if not addresses:
                print("LAN access enabled, but no LAN IPv4 address was detected. Run ipconfig to find it.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
