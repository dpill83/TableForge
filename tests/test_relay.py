import concurrent.futures
import json
import os
import sys
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "relay.sqlite3")
        self.table = server.create_table(self.db, "Test table", ["George", "Viktor"])
        self.other = server.create_table(self.db, "Other table", ["Ethereal"])
        self.http = server.make_server(self.db, port=0)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.http.server_port}"

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        self.temp.cleanup()

    def api(self, action="state", actor=0, body=None, table=None, key=None):
        table = table or self.table
        credential = key if key is not None else table["credentials"][actor]["key"]
        request = urllib.request.Request(self.url + "/v1/tables/" + table["table_code"] + "/" + action,
                                        data=json.dumps(body).encode() if body is not None else None,
                                        headers={"Authorization": "Bearer " + credential, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def scene(self, text="A door opens.", rid="scene-request-0001"):
        status, result = self.api("scenes", body={"request_id": rid, "text": text})
        self.assertEqual(status, 200, result)
        return result["id"]

    def test_full_round_trip_and_player_privacy(self):
        scene = self.scene()
        for actor, text in [(1, "George blesses the party."), (2, "Viktor opens the door.")]:
            status, view = self.api(actor=actor)
            self.assertEqual(view["scene"]["text"], "A door opens.")
            status, _ = self.api("replies", actor=actor,
                                 body={"request_id": "reply-request-0001", "scene_id": scene, "text": text})
            self.assertEqual(status, 200)
        _, dm = self.api()
        self.assertEqual([r["name"] for r in dm["replies"]], ["George", "Viktor"])
        _, player = self.api(actor=1)
        self.assertEqual([r["name"] for r in player["replies"]], ["George"])
        self.assertEqual(player["scenes"][0]["reply_count"], 1)
        self.assertNotIn("token", json.dumps(dm))

    def test_readable_credentials_and_rotation(self):
        self.assertIn(self.table["table_code"], server.WORDS)
        keys = [c["key"] for table in (self.table, self.other) for c in table["credentials"]]
        self.assertEqual(len(keys), len(set(keys)))
        for key in keys:
            self.assertEqual(len(key.split("-")), 2)
            self.assertTrue(all(word in server.WORDS for word in key.split("-")))
        scene_id = self.scene()
        output = subprocess.check_output([
            sys.executable, str(Path(server.__file__)), "--db", self.db,
            "rotate-key", "--table", self.table["table_code"], "--name", "AI-DM"], text=True)
        new_key = json.loads(output)["key"]
        self.assertNotIn(new_key, keys)
        self.assertEqual(self.api()[0], 401)
        status, state = self.api(key=new_key)
        self.assertEqual(status, 200)
        self.assertEqual(state["scene"]["id"], scene_id)

    def test_legacy_credentials_still_work(self):
        legacy = {"table_code": "012345abcd", "credentials": [{"key": "old_LONG-token_123"}]}
        db = server.connect(self.db)
        try:
            with db:
                db.execute("INSERT INTO tables VALUES (?, ?)", (legacy["table_code"], "Legacy"))
                db.execute("INSERT INTO actors VALUES (?, ?, ?, ?, ?)",
                           ("legacy", legacy["table_code"], "AI-DM", "dm", server.digest(legacy["credentials"][0]["key"])))
            self.assertEqual(self.api(table=legacy)[0], 200)
        finally:
            db.close()

    def test_dictionary_exhaustion_is_explicit_and_atomic(self):
        with patch.object(server, "WORDS", ("tiny",)):
            with self.assertRaisesRegex(ValueError, "passphrases"):
                server.create_table(self.db, "Too small", ["Player"])
        db = server.connect(self.db)
        try:
            self.assertIsNone(db.execute("SELECT code FROM tables WHERE code='tiny'").fetchone())
            with patch.object(server, "WORDS", (self.table["table_code"],)):
                with self.assertRaisesRegex(ValueError, "table words"):
                    server.new_table_code(db)
        finally:
            db.close()

    def test_auth_roles_and_cross_table_isolation(self):
        self.assertEqual(self.api(key="invalid")[0], 401)
        self.assertEqual(self.api(key=self.other["credentials"][0]["key"])[0], 401)
        self.assertEqual(self.api("scenes", actor=1, body={"request_id": "scene-request-0001", "text": "leak"})[0], 403)
        scene = self.scene()
        payload = {"request_id": "reply-request-0001", "text": "hello", "scene_id": scene}
        self.assertEqual(self.api("replies", body=payload)[0], 403)
        self.assertEqual(self.api("replies", actor=1, body=payload, table=self.other)[0], 404)
        self.assertEqual(self.api("state?scene_id=" + str(scene), table=self.other)[0], 404)

    def test_concurrent_duplicate_and_conflicting_retry(self):
        payload = {"request_id": "scene-request-0001", "text": "Only once."}
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.api("scenes", body=payload), range(8)))
        self.assertTrue(all(status == 200 for status, _ in results))
        self.assertEqual(len({r["id"] for _, r in results}), 1)
        self.assertEqual(sum(not r["replayed"] for _, r in results), 1)
        payload["text"] = "Changed body"
        self.assertEqual(self.api("scenes", body=payload)[0], 409)
        _, state = self.api()
        self.assertEqual(len(state["scenes"]), 1)

    def test_late_replies_remain_with_original_scene(self):
        first = self.scene("First scene")
        second = self.scene("Second scene", "scene-request-0002")
        self.api("replies", actor=1, body={"request_id": "reply-request-0001", "scene_id": first, "text": "Late reply"})
        _, latest = self.api()
        self.assertEqual(latest["scene"]["id"], second)
        self.assertEqual(latest["replies"], [])
        _, earlier = self.api("state?scene_id=" + str(first))
        self.assertEqual(earlier["replies"][0]["text"], "Late reply")

    def test_restart_persists_scene_reply_and_retry(self):
        scene = self.scene()
        payload = {"request_id": "reply-request-0001", "scene_id": scene, "text": "Saved reply"}
        _, first = self.api("replies", actor=1, body=payload)
        self.http.shutdown(); self.http.server_close(); self.thread.join()
        self.http = server.make_server(self.db, port=0)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.http.server_port}"
        _, result = self.api("replies", actor=1, body=payload)
        self.assertEqual(result["id"], first["id"])
        self.assertTrue(result["replayed"])
        _, state = self.api()
        self.assertEqual(len(state["replies"]), 1)

    def test_input_validation_and_key_hash_storage(self):
        for value in ["", " " * 10, "x" * 50001, None, 12, "a\x00b"]:
            status, _ = self.api("scenes", body={"request_id": "scene-request-0001", "text": value})
            self.assertEqual(status, 400)
        self.assertEqual(self.api("scenes", body={"request_id": "short", "text": "x"})[0], 400)
        self.assertEqual(self.api("state?scene_id=nope")[0], 400)
        self.assertEqual(self.api("scenes", body={"request_id": "scene-request-0001", "text": "x", "role": "dm"})[0], 400)
        raw = Path(self.db).read_bytes()
        self.assertNotIn(self.table["credentials"][0]["key"].encode(), raw)


if __name__ == "__main__":
    unittest.main()
