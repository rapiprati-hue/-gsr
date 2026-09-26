"""oriori_gsr v2 자동 테스트. 실행: python -m unittest test_engine -v (가상환경에서)."""
import json
import os
import tempfile
import time
import unittest
import unittest.mock

TEST_DATA = tempfile.TemporaryDirectory(prefix="oriori_test_")
os.environ["ORIORI_DATA_DIR"] = TEST_DATA.name
import engine
from app import app, store


class ScoringTests(unittest.TestCase):
    def test_midpoint(self):
        scores, missing = engine.score_answers({i["id"]: 3 for i in engine.BIG5_ITEMS})
        self.assertEqual(scores, dict.fromkeys("OCEAN", 50))
        self.assertEqual(sum(missing.values()), 0)

    def test_reverse_scoring(self):
        high = {i["id"]: (1 if i["reverse"] else 5) for i in engine.BIG5_ITEMS}
        self.assertEqual(set(engine.score_answers(high)[0].values()), {100})
        low = {i["id"]: (5 if i["reverse"] else 1) for i in engine.BIG5_ITEMS}
        self.assertEqual(set(engine.score_answers(low)[0].values()), {0})

    def test_missing_items(self):
        scores, missing = engine.score_answers({"E1": 5, "E3": 5})
        self.assertEqual(scores["E"], 100)
        self.assertIsNone(scores["O"])
        self.assertEqual(missing["O"], 4)
        for bad in ({"E1": 0}, {"E1": True}, {"E1": "5"}, [3] * 20):
            with self.assertRaises(ValueError):
                engine.score_answers(bad)

    def test_reference_type(self):
        self.assertEqual(engine.reference_type({"E": 80, "O": 70, "A": 20, "C": 10, "N": 100}), "ENTP")
        self.assertIsNone(engine.reference_type({"E": 80, "O": None, "A": 20, "C": 10, "N": 0}))

    def test_script_shapes(self):
        basic = engine.build_script("basic", True)
        social = engine.build_script("social", True, seed=0)
        deep = engine.build_script("deep", True, seed=1)
        self.assertEqual(sum(s["kind"] == "big5" for s in basic), 20)
        self.assertEqual(sum(s["kind"] == "gaze" for s in basic), 0)
        self.assertEqual([s["direction"] for s in social if s["kind"] == "gaze"], ["direct", "averted", "averted", "direct"])
        self.assertEqual([s["direction"] for s in deep if s["kind"] == "gaze"], ["averted", "direct", "direct", "averted"])
        self.assertEqual(sum(s["kind"] == "interview" for s in deep), 3)
        self.assertEqual(sum(s["kind"] == "interview" for s in social), 0)
        self.assertEqual(deep[-1]["kind"], "end")
        self.assertEqual(len({s["id"] for s in deep}), len(deep))

    def test_event_response_polarity(self):
        samples = [{"t": t * 50, "adc": 20000 + (3000 if 2500 <= t * 50 <= 5000 else 0)} for t in range(200)]
        up = engine.event_response(samples, 1500, 100, rises=True)
        self.assertEqual(up["amplitude"], 3000)
        self.assertEqual(up["z"], 30.0)
        down = engine.event_response(samples, 1500, 100, rises=False)
        self.assertLessEqual(down["amplitude"], 0)
        self.assertIsNone(engine.event_response(samples, 9990, 100))

    def test_words(self):
        self.assertEqual(engine.reactivity_word(2.0), "뚜렷하게 올라감")
        self.assertEqual(engine.reactivity_word(0.1), "큰 변화 없음")
        self.assertEqual(engine.latency_word(3000, 1000), "한참 뜸을 들인 뒤")
        self.assertIsNone(engine.latency_word(None, 1000))

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            store.folder("../../config.json")

    def test_claude_off_without_key(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        r = engine.generate_report({"course": "deep", "aiConsent": True, "scores": {"O": 60, "C": 40, "E": 70, "A": 55, "N": 30}, "metrics": {"categoryZ": {}}, "responses": []})
        self.assertEqual(r["source"], "rules")
        self.assertNotRegex(r["character"], r"[0-9]")


class APITests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.ids = []

    def tearDown(self):
        store.active = None
        store.pulses = []
        for sid in self.ids:
            if store.folder(sid).exists():
                store.delete(sid)

    def create(self, course="basic"):
        r = self.client.post("/api/sessions", json={"course": course})
        self.assertEqual(r.status_code, 201)
        self.ids.append(r.json["id"])
        return r.json

    def test_operator_access_and_participant_actions(self):
        remote = {"REMOTE_ADDR": "192.168.1.20"}
        self.assertEqual(self.client.get("/api/workspace", environ_overrides=remote).status_code, 403)
        self.assertEqual(self.client.post("/api/sessions", json={"course": "basic"}, environ_overrides=remote).status_code, 403)
        s = self.create()
        path = f"/api/sessions/{s['id']}"
        self.assertEqual(self.client.get(path + "?script=1", environ_overrides=remote).json["status"], "waiting")
        self.assertEqual(self.client.patch(path, json={"action": "start"}, environ_overrides=remote).status_code, 403)
        r = self.client.patch(path, json={"action": "consent", "aiConsent": True}, environ_overrides=remote)
        self.assertEqual(r.json["status"], "consented")
        self.assertTrue(r.json["aiConsent"])
        self.assertFalse(r.json["researchConsent"])

    def test_cross_origin_denied(self):
        self.assertEqual(self.client.post("/api/sessions", json={"course": "basic"}, headers={"Origin": "https://untrusted.example"}).status_code, 403)

    def test_qr_and_meta(self):
        self.assertEqual(self.client.get("/api/qr?text=http://x").mimetype, "image/png")
        self.assertEqual(len(self.client.get("/api/meta").json["items"]), 20)

    def run_full(self, course="deep", ai=False):
        s = self.create(course)
        sid = s["id"]
        path = f"/api/sessions/{sid}"
        script = s["script"]
        self.assertEqual(self.client.patch(path, json={"action": "start"}).status_code, 400)  # 동의 전
        self.client.patch(path, json={"action": "consent", "aiConsent": ai})
        r = self.client.patch(path, json={"action": "start"})
        self.assertEqual(r.json["status"], "running")
        self.assertEqual(r.json["step"], 0)
        # 시계를 뒤로 돌려 60초 어치 합성 신호를 만든다 (테스트용 픽스처; 운영 우회 아님)
        store.start_ns -= 5_000_000_000
        pulses = []
        for i, st in enumerate(script):
            store.start_ns -= 9_000_000_000          # 단계 사이 9초가 흐른 것처럼 (호스트 시계 고정용)
            r = self.client.patch(path, json={"action": "step", "index": i})
            self.assertEqual(r.status_code, 200, r.json)
            if st["kind"] == "big5":
                src = "tablet" if i % 2 else "operator"
                r = self.client.patch(path, json={"action": "answer", "itemId": st["id"], "value": 4 if not st["item"]["reverse"] else 2, "source": src}, environ_overrides={"REMOTE_ADDR": "192.168.1.20"} if src == "tablet" else None)
                self.assertEqual(r.status_code, 200, r.json)
            if st["kind"] in ("question", "interview"):
                for kind in ("asked_end", "answer_start", "answer_end"):
                    store.start_ns -= 1_500_000_000  # 질문 끝 → 1.5초 뜸 → 답변
                    r = self.client.patch(path, json={"action": "mark", "kind": kind, "questionId": st["id"]})
                    self.assertEqual(r.status_code, 200, r.json)
                if st["kind"] == "interview":
                    self.client.patch(path, json={"action": "note", "questionId": st["id"], "text": "시간이 부족 / 혼자 있는 시간"})
        # raw 는 Collector 스레드가 없으므로 직접 채운다: 이벤트 시각에 맞춘 합성 펄스
        events = store.event_rows(sid)
        for e in events:
            p = json.loads(e["payload"])
            if e["type"] == "step_start" and (p.get("kind") == "gaze" or p.get("kind") == "big5"):
                pulses.append((float(e["hostElapsedMs"]) / 1000, 2500 if p.get("direction") == "direct" else 600))
            if e["type"] == "mark" and p.get("kind") == "asked_end":
                pulses.append((float(e["hostElapsedMs"]) / 1000, 1800))
        last_ms = max(float(e["hostElapsedMs"]) for e in events if e["hostElapsedMs"])
        for k in range(int(last_ms / 50) + 200):
            t = k * 50
            store.append(sid, "raw.csv", engine.RAW_FIELDS, {"seq": k, "t": t, "adc": engine.synthetic_adc(t / 1000, pulses), "button": 0, "sound": None, "device_ms": t, "host_monotonic_ns": "0", "host_unix_ns": "0", "source": "synthetic"})
        r = self.client.patch(path, json={"action": "complete"})
        self.assertEqual(r.status_code, 200, r.json)
        return r.json, sid, path

    def test_deep_flow_complete_export_print_delete(self):
        s, sid, path = self.run_full("deep")
        self.assertEqual(s["status"], "completed")
        self.assertEqual(set(s["scores"].values()), {75})
        self.assertEqual(s["referenceType"], "ENFJ")
        cz = s["metrics"]["categoryZ"]
        for key in ("big5", "gaze_direct", "gaze_averted", "question_neutral", "question_self", "question_social", "interview_lack", "interview_meaning"):
            self.assertIn(key, cz)
        self.assertGreater(cz["gaze_direct"], cz["gaze_averted"])
        self.assertGreater(s["metrics"]["contrasts"]["gazeDirectMinusAverted"], 0)
        interview = [r for r in s["responses"] if r["category"] == "interview_lack"][0]
        self.assertEqual(interview["note"], "시간이 부족 / 혼자 있는 시간")
        self.assertIsNotNone(interview["latencyMs"])
        self.assertEqual(s["report"]["source"], "rules")
        self.assertFalse(s["reportPending"])   # 키 없음 → pending 아님
        # 참가자 평가(태블릿)
        r = self.client.patch(path, json={"action": "feedback", "accuracy": 4, "resonant": "문장"}, environ_overrides={"REMOTE_ADDR": "192.168.1.20"})
        self.assertEqual(r.json["feedback"]["accuracy"], 4)
        # 내보내기
        for kind in ("sessions", "responses", "raw", "events"):
            r = self.client.get(f"/api/export?kind={kind}&id={sid}")
            self.assertEqual(r.status_code, 200)
            self.assertIn(sid, r.get_data(as_text=True))
        csv_text = self.client.get(f"/api/export?kind=responses&id={sid}").get_data(as_text=True)
        self.assertIn("gaze_direct", csv_text)
        self.assertEqual(self.client.get(f"/api/export?format=json&id={sid}").json["project"], "oriori_gsr")
        self.assertEqual(self.client.post(path + "/report", json={}).json["report"]["source"], "rules")
        self.assertTrue(self.client.post(path + "/print", json={}).json["browser"])
        self.assertEqual(self.client.delete(path).status_code, 200)
        self.assertFalse(store.folder(sid).exists())

    def test_basic_flow_has_no_social_categories(self):
        s, sid, path = self.run_full("basic")
        self.assertEqual(set(s["metrics"]["categoryZ"]), {"big5"})
        self.assertIsNone(s["metrics"]["questionLatencyMedianMs"])
        self.assertIsNotNone(s["metrics"]["big5LatencyMedianMs"])

    def test_stop_keeps_partial_data(self):
        s = self.create("social")
        path = f"/api/sessions/{s['id']}"
        self.client.patch(path, json={"action": "consent"})
        self.client.patch(path, json={"action": "start"})
        store.append(s["id"], "raw.csv", engine.RAW_FIELDS, {"seq": 0, "t": 0, "adc": 20000, "button": 0, "sound": None, "device_ms": 0, "host_monotonic_ns": "0", "host_unix_ns": "0", "source": "synthetic"})
        r = self.client.patch(path, json={"action": "stop"}, environ_overrides={"REMOTE_ADDR": "192.168.1.20"})
        self.assertEqual(r.json["status"], "stopped")
        self.assertEqual(len(store.raw(s["id"])), 1)
        self.assertIsNone(store.active)

    def test_receipt_image_if_font_available(self):
        try:
            engine.find_font({"fontPath": ""})
        except ValueError:
            self.skipTest("한글 폰트 없음 (브라우저 인쇄 경로는 폰트 불필요)")
        s, sid, path = self.run_full("deep")
        image = engine.receipt_image(s, {"paperWidth": "80", "fontPath": ""}, "http://localhost:8765/result/" + sid)
        self.assertEqual(image.width, 576)


if __name__ == "__main__":
    unittest.main()


class ClaudeParsingTests(unittest.TestCase):
    """실제 API 호출 없이 응답 파싱·검증·폴백을 확인한다."""
    session = {"course": "deep", "aiConsent": True, "demo": True, "scores": {"O": 60, "C": 40, "E": 70, "A": 55, "N": 30},
               "metrics": {"categoryZ": {"gaze_direct": 2.0, "gaze_averted": 0.2}, "questionLatencyMedianMs": 900},
               "responses": [{"category": "interview_lack", "latencyMs": 2000, "z": 1.0, "note": "시간이 부족"}]}

    def fake(self, text):
        import io
        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        body = json.dumps({"model": "claude-test", "content": [{"type": "text", "text": text}]}).encode()
        captured = {}
        def urlopen(req, timeout=0):
            captured["headers"] = dict(req.header_items()); captured["body"] = json.loads(req.data)
            return R(body)
        return urlopen, captured

    def test_valid_json_is_accepted(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        urlopen, cap = self.fake('설명: {"title": "조용한 항해사", "character": "오늘 당신은 시간이 부족하다고 말했어요. 눈이 마주칠 때 몸이 먼저 반응했어요. 고정된 모습은 아니에요.", "lackMeaning": "부족함은 방향일지도 몰라요. 채워진 순간을 기억해 두세요.", "oneLine": "천천히, 당신의 속도로."}')
        with unittest.mock.patch.object(engine.urllib.request, "urlopen", urlopen):
            r = engine.generate_report(self.session)
        self.assertEqual(r["source"], "claude")
        self.assertEqual(r["title"], "조용한 항해사")
        self.assertEqual(cap["headers"].get("X-api-key"), "sk-test")
        self.assertIn("anthropic-version", {k.lower() for k in cap["headers"]})
        sent = json.loads(cap["body"]["messages"][0]["content"])
        self.assertEqual(sent["operator_notes_of_participant_answers"], {"결핍 질문": "시간이 부족"})
        self.assertEqual(sent["skin_conductance_by_situation"]["눈맞춤 (직접 시선)"], "뚜렷하게 올라감")
        os.environ.pop("ANTHROPIC_API_KEY")

    def test_digits_or_bad_shape_fall_back(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        for text in ('{"title": "x", "character": "당신은 87점이에요", "lackMeaning": "y", "oneLine": "z"}', 'not json', '{"title": "x"}'):
            urlopen, _ = self.fake(text)
            with unittest.mock.patch.object(engine.urllib.request, "urlopen", urlopen):
                r = engine.generate_report(self.session)
            self.assertEqual(r["source"], "rules-fallback")
            self.assertIn("error", r)
        os.environ.pop("ANTHROPIC_API_KEY")

    def test_not_sent_without_consent_or_for_other_courses(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        calls = []
        with unittest.mock.patch.object(engine.urllib.request, "urlopen", lambda *a, **k: calls.append(1)):
            self.assertEqual(engine.generate_report({**self.session, "aiConsent": False})["source"], "rules")
            self.assertEqual(engine.generate_report({**self.session, "course": "social"})["source"], "rules")
        self.assertEqual(calls, [])
        os.environ.pop("ANTHROPIC_API_KEY")
