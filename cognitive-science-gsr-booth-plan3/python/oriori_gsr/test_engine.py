import os
import tempfile
import unittest
from pathlib import Path

TEST_DATA = tempfile.TemporaryDirectory(prefix="oriori_test_")
os.environ["ORIORI_DATA_DIR"] = TEST_DATA.name
import engine
from app import app, store, config


class ScoringTests(unittest.TestCase):
    def test_midpoint(self):
        self.assertEqual(engine.score_answers([3] * 10), dict.fromkeys("OCEAN", 50))

    def test_reverse_scoring(self):
        self.assertEqual(set(engine.score_answers([5] * 5 + [1] * 5).values()), {100})
        self.assertEqual(set(engine.score_answers([1] * 5 + [5] * 5).values()), {0})

    def test_invalid_answers(self):
        for a in ([0] * 10, [1] * 9, [True] * 10, None, [6] * 10):
            with self.assertRaises(ValueError):
                engine.score_answers(a)

    def test_reference_is_deterministic(self):
        self.assertEqual(engine.reference_type({"E": 80, "O": 70, "A": 20, "C": 10, "N": 100}), "ENTP")

    def test_protocol(self):
        self.assertEqual(sum(t for _, t in engine.stages("full", True)), 40)
        self.assertEqual(sum(t for _, t in engine.stages("basic", False)), 90)

    def test_raw_metrics(self):
        samples = [engine.synthetic_sample(i) for i in range(800)]
        m = engine.analyze(samples)
        self.assertEqual(m["samples"], 800)
        self.assertEqual(m["quality"], 100)
        self.assertTrue(27500 < m["baseline"] < 28500)
        self.assertGreater(m["change"], 0)
        self.assertIsNone(m["reactionMs"])

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            store.folder("../../config.json")


class APITests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.ids = []

    def tearDown(self):
        store.active = None
        for sid in self.ids:
            if store.folder(sid).exists():
                store.delete(sid)

    def create(self, course="basic"):
        r = self.client.post("/api/sessions", json={"course": course})
        self.assertEqual(r.status_code, 201)
        sid = r.json["id"]
        self.ids.append(sid)
        return sid

    def test_operator_access(self):
        r = self.client.get("/api/workspace", environ_overrides={"REMOTE_ADDR": "192.168.1.20"})
        self.assertEqual(r.status_code, 403)
        r = self.client.post("/api/sessions", json={"course": "basic"}, environ_overrides={"REMOTE_ADDR": "192.168.1.20"})
        self.assertEqual(r.status_code, 403)

    def test_cross_origin_denied(self):
        r = self.client.post("/api/sessions", json={"course": "basic"}, headers={"Origin": "https://untrusted.example"})
        self.assertEqual(r.status_code, 403)

    def test_consent_and_validation(self):
        sid = self.create()
        path = f"/api/sessions/{sid}"
        self.assertEqual(self.client.patch(path, json={"action": "start"}).status_code, 400)
        r = self.client.patch(path, json={"action": "consent", "aiConsent": False})
        self.assertEqual(r.json["status"], "questionnaire")
        self.assertFalse(r.json["researchConsent"])
        self.assertEqual(self.client.patch(path, json={"action": "answers", "answers": [6] * 10}).status_code, 400)

    def test_complete_export_print_and_delete(self):
        sid = self.create("full")
        path = f"/api/sessions/{sid}"
        self.client.patch(path, json={"action": "consent", "aiConsent": False})
        self.client.patch(path, json={"action": "answers", "answers": [4, 4, 4, 4, 3, 2, 2, 2, 2, 3]})
        r = self.client.patch(path, json={"action": "start"})
        self.assertEqual(r.json["status"], "measuring")
        self.assertEqual(self.client.patch(path, json={"action": "complete"}).status_code, 400)
        # Controlled clock/sample fixture, NOT a production bypass.
        store.start_ns -= 40_000_000_000
        for i in range(800):
            store.append(sid, "raw.csv", engine.RAW_FIELDS, engine.synthetic_sample(i))
        self.client.post(path + "/events", json={"type": "reaction", "elapsedMs": 7000, "payload": {"reactionMs": 320}})
        r = self.client.patch(path, json={"action": "complete"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["status"], "completed")
        self.assertEqual(r.json["metrics"]["samples"], 800)
        self.assertEqual(r.json["metrics"]["reactionMs"], 320)
        self.assertEqual(self.client.get(f"/api/export?kind=raw&id={sid}").status_code, 200)
        report = self.client.post(path + "/report", json={}).json
        self.assertEqual(report["reportSource"], "rules")
        self.assertTrue(self.client.post(path + "/print", json={}).json["browser"])
        image = engine.receipt_image(r.json, config, "http://localhost:8765/result/" + sid)
        self.assertEqual(image.width, 576)
        self.assertGreater(image.height, 800)
        image.save(Path(TEST_DATA.name) / "receipt_test.png")
        self.assertEqual(self.client.delete(path).status_code, 200)
        self.assertFalse(store.folder(sid).exists())

    def test_partial_data_survives_stop(self):
        sid = self.create()
        path = f"/api/sessions/{sid}"
        self.client.patch(path, json={"action": "consent"})
        self.client.patch(path, json={"action": "answers", "answers": [3] * 10})
        self.client.patch(path, json={"action": "start"})
        store.append(sid, "raw.csv", engine.RAW_FIELDS, engine.synthetic_sample(0))
        r = self.client.patch(path, json={"action": "stop"})
        self.assertEqual(r.json["status"], "stopped")
        self.assertEqual(len(store.raw(sid)), 1)
        self.assertIsNone(store.active)


if __name__ == "__main__":
    unittest.main()
