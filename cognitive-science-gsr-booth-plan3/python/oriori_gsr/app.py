"""oriori_gsr local booth server. Operator: localhost. Participants: secret session URL."""
from __future__ import annotations
import csv
import io
import json
import logging
import os
import socket
import threading
import time
import webbrowser
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
from flask import Flask, jsonify, request, send_from_directory, Response
from engine import (DATA, Store, Collector, PRICES, PROTOCOL, INSTRUMENT, LABELS, RAW_FIELDS, EVENT_FIELDS, load_config, atomic_json, now, stages, synthetic_sample, score_answers, analyze, rule_report, generate_report, send_receipt)

config = load_config()
store = Store()
collector = Collector(store, config)
app = Flask(__name__, static_folder="static")
app.config.update(MAX_CONTENT_LENGTH=128 * 1024, JSON_SORT_KEYS=False)
app.json.ensure_ascii = False
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def public_session(s):
    return {**{k: v for k, v in s.items() if not k.startswith("_")}, "serverNow": round(time.time() * 1000), "paperWidth": config["paperWidth"], "resultUrl": f"http://{lan_ip()}:{config['port']}/result/{s['id']}"}


def new_session(course):
    if course not in PRICES:
        raise ValueError("올바른 코스를 선택하세요.")
    sid = str(uuid4())
    with store.lock:
        s = {"id": sid, "code": "ORI-" + sid[:6].upper(), "course": course, "status": "waiting", "demo": config["mode"] == "demo", "consent": False, "aiConsent": False, "researchConsent": False, "answers": [], "scores": None, "metrics": None, "report": None, "reportSource": "rules", "createdAt": now(), "completedAt": None, "startedAt": None, "protocol": PROTOCOL, "instrument": INSTRUMENT, "adcUnit": "uncalibrated_u16", "nominalHz": 20}
        store.save(s)
        store.event(sid, "created", payload={"protocol": PROTOCOL, "synthetic": s["demo"]})
    return s


def seed_demo():
    with store.lock:
        marker = DATA / ".initialized"
        if marker.exists():
            return
        if config["mode"] == "demo" and not store.all():
            for i, course in enumerate(["basic", "full", "relation", "full", "basic", "full", "full", "relation"]):
                s = new_session(course)
                s["code"] = f"ORI-{i + 1:03}"
                s["answers"] = [4, 3 + i % 2, 4, 5, 2 + i % 2, 2, 2, 3, 2, 4]
                s["scores"] = score_answers(s["answers"])
                seconds = sum(t for _, t in stages(course))
                samples = [synthetic_sample(j, i) for j in range(seconds * 20)]
                s.update(status="completed", consent=True, metrics=analyze(samples, reaction_ms=280 + i * 17), createdAt=(datetime.now(timezone.utc) - timedelta(minutes=(8 - i) * 11)).isoformat(), completedAt=now())
                s["report"] = rule_report(s["scores"], s["metrics"])
                store.save(s)
                for sample in samples:
                    store.append(s["id"], "raw.csv", RAW_FIELDS, sample)
                store.event(s["id"], "demo_seed", payload={"synthetic": True})
        marker.write_text("1.0", encoding="utf-8")


def operator():
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify(error="운영 기능은 노트북의 localhost에서만 사용할 수 있어요. 태블릿에서는 운영자가 만든 세션 QR로 입장하세요."), 403
    return None


@app.before_request
def same_origin():
    if request.method in ("POST", "PATCH", "DELETE"):
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).netloc != request.host:
            return jsonify(error="다른 출처에서의 요청은 허용하지 않습니다."), 403
        if request.method != "DELETE" and not request.is_json:
            return jsonify(error="JSON 요청이 필요합니다."), 415


@app.after_request
def privacy_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    if request.path.startswith("/api/") or request.path.startswith("/result/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(Exception)
def handle_error(exc):
    from werkzeug.exceptions import HTTPException
    if isinstance(exc, HTTPException):
        return jsonify(error=exc.description), exc.code
    if isinstance(exc, FileNotFoundError):
        return jsonify(error=str(exc)), 404
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return jsonify(error=str(exc) or "입력 값을 확인해 주세요."), 400
    logging.exception("oriori operation failed")
    return jsonify(error="작업에 실패했어요. 터미널 로그와 README를 확인하세요. 프린터 오류라면 브라우저 인쇄를 이용하세요."), 500


@app.get("/")
@app.get("/tablet")
@app.get("/result/<sid>")
def frontend(sid=None):
    return send_from_directory(ROOT / "static", "index.html")


@app.get("/fonts/<path:name>")
def fonts(name):
    return send_from_directory(ROOT / "static" / "fonts", name)


@app.get("/icon.svg")
def icon():
    return send_from_directory(ROOT / "static", "icon.svg")


@app.get("/api/health")
def health():
    return jsonify(status="ok", project="oriori_gsr", mode=config["mode"])


@app.get("/api/workspace")
def workspace():
    denied = operator()
    if denied:
        return denied
    seed_demo()
    prefs = {"demo": config["mode"] == "demo", "printer": config["printer"], "paperWidth": config["paperWidth"], "serialPort": config["serialPort"], "baudRate": str(config["baudRate"]), "checklist": config.get("checklist", [])}
    return jsonify(sessions=[public_session(s) for s in store.all()], settings=prefs, local=True, version="1.0.0", llmAvailable=bool(os.environ.get("OPENAI_API_KEY")), tabletBase=f"http://{lan_ip()}:{config['port']}", devices={"pico": collector.status()["connected"], "printer": config["printer"] != "browser"})


@app.get("/api/sensor")
def sensor():
    denied = operator()
    return denied or jsonify(collector.status())


@app.get("/api/ports")
def ports():
    denied = operator()
    if denied:
        return denied
    from serial.tools import list_ports
    return jsonify(ports=[{"device": p.device, "description": p.description} for p in list_ports.comports()])


@app.patch("/api/settings")
def settings():
    denied = operator()
    if denied:
        return denied
    b = request.get_json()
    with store.lock:
        if store.active:
            raise ValueError("측정이 끝난 뒤 설정을 바꿔 주세요.")
        for key in ("serialPort", "printer", "paperWidth", "checklist"):
            if key in b:
                if key == "printer" and b[key] not in ("browser", "win32", "usb", "network"):
                    raise ValueError("올바른 프린터 방식을 선택하세요.")
                if key == "paperWidth" and str(b[key]) not in ("58", "80"):
                    raise ValueError("용지 너비를 확인하세요.")
                if key == "serialPort" and (not isinstance(b[key], str) or len(b[key]) > 80):
                    raise ValueError("포트를 확인하세요.")
                if key == "checklist" and (not isinstance(b[key], list) or any(type(i) is not int or not 0 <= i < 6 for i in b[key])):
                    raise ValueError("체크리스트 형식을 확인하세요.")
                config[key] = b[key]
        atomic_json(ROOT / "config.json", config)
    return jsonify(demo=config["mode"] == "demo", printer=config["printer"], paperWidth=config["paperWidth"], serialPort=config["serialPort"], baudRate=str(config["baudRate"]), checklist=config.get("checklist", []))


@app.post("/api/sessions")
def create_session():
    denied = operator()
    if denied:
        return denied
    return jsonify(public_session(new_session(request.get_json().get("course")))), 201


@app.route("/api/sessions/<sid>", methods=["GET", "PATCH", "DELETE"])
def session_route(sid):
    s = store.get(sid)
    if request.method == "GET":
        return jsonify(public_session(s))
    if request.method == "DELETE":
        denied = operator()
        if denied:
            return denied
        store.delete(sid)
        return jsonify(ok=True)
    b = request.get_json()
    action = b.get("action")
    with store.lock:
        s = store.get(sid)
        if action == "consent":
            if s["status"] != "waiting":
                raise ValueError("이미 시작한 세션입니다.")
            s.update(consent=True, aiConsent=b.get("aiConsent") is True, status="questionnaire")
            store.event(sid, "consent", payload={"version": "1.0", "experience": True, "research": False, "ai": s["aiConsent"]})
        elif action == "answers":
            if s["status"] != "questionnaire" or not s["consent"]:
                raise ValueError("먼저 참여 동의를 확인하세요.")
            s["scores"] = score_answers(b.get("answers"))
            s.update(answers=b["answers"], status="ready")
        elif action == "start":
            if s["status"] != "ready":
                raise ValueError("설문을 먼저 완료하세요.")
            if store.active and store.active != sid:
                raise ValueError("다른 참가자의 측정이 진행 중입니다.")
            if not s["demo"]:
                if not config.get("schoolApprovalConfirmed"):
                    raise ValueError("학교 승인과 필요한 보호자 동의를 확인한 후 config.json에서 schoolApprovalConfirmed를 설정하세요.")
                if not collector.status()["connected"]:
                    raise ValueError("Pico 신호가 수신되지 않습니다. Thonny 종료, 포트, 배선을 확인하세요.")
            s.update(status="measuring", startedAt=now())
            store.start_ns = time.monotonic_ns()
            store.active = sid
            store.event(sid, "measurement_start")
        elif action == "complete":
            if s["status"] == "completed":
                return jsonify(public_session(s))
            if s["status"] != "measuring" or store.active != sid:
                raise ValueError("측정 중인 세션이 아닙니다.")
            total = sum(t for _, t in stages(s["course"], s["demo"]))
            elapsed = (time.monotonic_ns() - store.start_ns) / 1e9
            if elapsed < total - .5:
                raise ValueError("측정이 아직 끝나지 않았어요.")
            samples = store.raw(sid)
            if not samples:
                raise ValueError("기록된 센서 데이터가 없습니다. 측정을 중단하고 연결을 확인하세요.")
            if not s["demo"] and not collector.status()["connected"]:
                raise ValueError("센서 연결이 끊어졌습니다. 중단하면 부분 원시 데이터가 보존됩니다.")
            rts, hardware_rts = [], []
            stimulus_host = None
            for e in store.event_rows(sid):
                if e["type"] == "reaction":
                    val = json.loads(e["payload"]).get("reactionMs")
                    if isinstance(val, (int, float)) and 0 <= val <= 10000:
                        rts.append(val)
                elif e["type"] == "stimulus" and e.get("hostElapsedMs"):
                    stimulus_host = float(e["hostElapsedMs"])
                elif e["type"] == "hardware_button" and stimulus_host is not None and e.get("hostElapsedMs"):
                    delta = float(e["hostElapsedMs"]) - stimulus_host
                    if 0 <= delta <= (2000 if s["demo"] else 6000):
                        hardware_rts.append(delta)
                        stimulus_host = None
            reaction_clock = "browser_performance" if rts else "host_receipt_approx" if hardware_rts else "not_available"
            chosen_rts = rts or hardware_rts
            metrics = analyze(samples, 6000 if s["demo"] else 60000, round(sum(chosen_rts) / len(chosen_rts)) if chosen_rts else None)
            metrics["reactionClock"] = reaction_clock
            metrics["hardwareReactionCount"] = len(hardware_rts)
            metrics["observedHz"] = round(len(samples) / elapsed, 2)
            metrics["missingSequenceCount"] = sum(max(0, int(b["seq"] - a["seq"] - 1)) for a, b in zip(samples, samples[1:]))
            s.update(metrics=metrics, status="completed", completedAt=now(), report=rule_report(s["scores"], metrics))
            store.event(sid, "measurement_end", elapsed * 1000, {"observedHz": metrics["observedHz"], "synthetic": s["demo"]})
            store.active = None
        elif action == "stop":
            if s["status"] in ("completed", "stopped"):
                raise ValueError("이미 종료된 세션입니다.")
            store.event(sid, "participant_stop", (time.monotonic_ns() - store.start_ns) / 1e6 if store.active == sid else 0)
            s["status"] = "stopped"
            if store.active == sid:
                store.active = None
        else:
            raise ValueError("지원하지 않는 동작입니다.")
        store.save(s)
    return jsonify(public_session(s))


@app.post("/api/sessions/<sid>/events")
def events(sid):
    s = store.get(sid)
    b = request.get_json()
    if not isinstance(b.get("type"), str) or len(b["type"]) > 80 or not isinstance(b.get("elapsedMs"), (int, float)) or not 0 <= b["elapsedMs"] <= 3600000:
        raise ValueError("이벤트 형식을 확인하세요.")
    store.event(sid, b["type"], b["elapsedMs"], b.get("payload", {}))
    return jsonify(ok=True)


@app.post("/api/sessions/<sid>/report")
def report(sid):
    s = store.get(sid)
    if s["status"] != "completed":
        raise ValueError("검사를 먼저 완료하세요.")
    if time.time() - s.get("_lastReport", 0) < 15:
        return jsonify(report=s["report"], reportSource=s["reportSource"])
    result = generate_report(s)
    with store.lock:
        s = store.get(sid)
        s.update(result, _lastReport=time.time())
        store.save(s)
    return jsonify(result)


@app.post("/api/sessions/<sid>/print")
def print_session(sid):
    denied = operator()
    if denied:
        return denied
    s = store.get(sid)
    if s["status"] != "completed":
        raise ValueError("완료한 세션만 출력할 수 있어요.")
    with store.lock:
        if time.time() - s.get("_lastPrint", 0) < 5:
            raise ValueError("중복 출력을 막기 위해 5초 뒤 다시 시도하세요.")
        s["_lastPrint"] = time.time()
        store.save(s)
    width = str(request.get_json().get("paperWidth", config["paperWidth"]))
    if width not in ("58", "80"):
        raise ValueError("인쇄 용지 너비를 확인하세요.")
    result = send_receipt(s, {**config, "paperWidth": width}, f"http://{lan_ip()}:{config['port']}/result/{sid}", store.folder(sid))
    store.event(sid, "print_requested", payload={"mode": config["printer"], "browser": result["browser"]})
    return jsonify(result)


@app.get("/api/export")
def export():
    denied = operator()
    if denied:
        return denied
    sid, kind = request.args.get("id"), request.args.get("kind", "sessions")
    selected = [store.get(sid)] if sid else store.all()
    if request.args.get("format") == "json":
        payload = {"project": "oriori_gsr", "protocol": PROTOCOL, "instrument": INSTRUMENT, "adcUnit": "uncalibrated_u16", "researchApproved": False, "exportedAt": now(), "sessions": [public_session(s) for s in selected], "raw": [{"sessionId": s["id"], "samples": store.raw(s["id"])} for s in selected], "events": [{"sessionId": s["id"], "events": store.event_rows(s["id"])} for s in selected]}
        return Response(json.dumps(payload, ensure_ascii=False, indent=2), mimetype="application/json", headers={"Content-Disposition": "attachment; filename=oriori_gsr_dataset.json"})
    output = io.StringIO(newline="")
    output.write("\ufeff")
    if kind == "raw":
        writer = csv.DictWriter(output, ["session_id"] + RAW_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for s in selected:
            for row in store.raw(s["id"]):
                writer.writerow({"session_id": s["id"], **row})
    elif kind == "events":
        writer = csv.DictWriter(output, ["session_id"] + EVENT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for s in selected:
            for row in store.event_rows(s["id"]):
                writer.writerow({"session_id": s["id"], **row})
    else:
        writer = csv.writer(output)
        writer.writerow(["id", "code", "course", "status", "demo", "created_at", *LABELS, "baseline_adc", "change_pct", "samples", "research_consent"])
        for s in selected:
            scores, metrics = s.get("scores") or {}, s.get("metrics") or {}
            writer.writerow([s["id"], s["code"], s["course"], s["status"], s["demo"], s["createdAt"], *[scores.get(k) for k in LABELS], metrics.get("baseline"), metrics.get("change"), metrics.get("samples"), False])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=oriori_gsr_{kind if kind in ('raw', 'events') else 'sessions'}.csv"})


@app.get("/downloads/README.md")
def readme():
    return send_from_directory(ROOT, "README.md", as_attachment=True)


@app.get("/downloads/oriori_gsr.zip")
def package():
    denied = operator()
    if denied:
        return denied
    stream = io.BytesIO()
    allowed = {"app.py", "engine.py", "requirements.txt", "config.json", "config.example.json", "README.md", "DATA_DICTIONARY.md", "PROTOCOL.md", ".env.example", "start_windows.bat", "start_mac.sh", "analyze.py", "test_engine.py"}
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as z:
        for p in ROOT.rglob("*"):
            rel = p.relative_to(ROOT)
            if not p.is_file() or any(x in ("__pycache__", ".venv", "data") for x in rel.parts):
                continue
            if str(rel) in allowed or rel.parts[0] in ("pico", "static", "assets"):
                if str(rel) == "config.json":
                    z.write(ROOT / "config.example.json", "oriori_gsr/config.json")
                else:
                    z.write(p, "oriori_gsr/" + str(rel))
    return Response(stream.getvalue(), mimetype="application/zip", headers={"Content-Disposition": "attachment; filename=oriori_gsr.zip"})


if __name__ == "__main__":
    from waitress import serve
    store.recover_and_expire(int(config.get("retentionDays", 30)))
    collector.start()
    host = lan_ip()
    port = int(config["port"])
    print("\n=== oriori_gsr v1.0 ===", flush=True)
    print(f"Operator: http://127.0.0.1:{port}", flush=True)
    print(f"Tablet:   http://{host}:{port}/tablet", flush=True)
    print(f"Mode: {config['mode']} | Data: {DATA}", flush=True)
    print("Keep this window open. Press Ctrl+C to stop. Private hotspot only.\n", flush=True)
    if not os.environ.get("ORIORI_NO_BROWSER"):
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    try:
        serve(app, host="0.0.0.0", port=port, threads=8, max_request_body_size=128 * 1024)
    except KeyboardInterrupt:
        collector.running = False
