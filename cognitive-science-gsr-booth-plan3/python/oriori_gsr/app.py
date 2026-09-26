"""oriori_gsr v2 local booth server. 운영자: localhost 노트북. 참가자: 세션 전용 URL(태블릿)."""
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
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
from flask import Flask, jsonify, request, send_from_directory, Response
from engine import (DATA, Store, Collector, COURSES, PROTOCOL, INSTRUMENT, LABELS, RAW_FIELDS, EVENT_FIELDS, RESPONSE_FIELDS, BIG5_ITEMS, SCALE,
                    load_config, atomic_json, now, js_round, build_script, score_answers, reference_type, compute_features, qualitative_summary,
                    rule_report, generate_report, llm_ready, llm_model, send_receipt, DEMO_PULSE, CODEBOOK)

config = load_config()
store = Store()
collector = Collector(store, config)
app = Flask(__name__, static_folder="static")
app.config.update(MAX_CONTENT_LENGTH=256 * 1024, JSON_SORT_KEYS=False)
app.json.ensure_ascii = False
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
ALLOW_REMOTE_OPERATOR = os.environ.get("ORIORI_ALLOW_REMOTE_OPERATOR") == "1"   # 미리보기/테스트 전용. 현장에서는 끄세요.
PARTICIPANT_ACTIONS = {"consent", "answer", "stop", "feedback"}


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def base_url():
    return f"http://{lan_ip()}:{config['port']}"


def is_operator():
    return ALLOW_REMOTE_OPERATOR or request.remote_addr in ("127.0.0.1", "::1")


def public_session(s, with_script=False, for_operator=True):
    out = {k: v for k, v in s.items() if not k.startswith("_")}
    if not for_operator and (s.get("report") or {}).get("held"):
        # 안전 플래그: 운영자가 확인·공개하기 전에는 태블릿에 문장을 보내지 않는다.
        out["report"] = None
        out["reportHeld"] = True
    out.update(serverNow=round(time.time() * 1000), hostMs=store.host_ms() if store.active == s["id"] else None,
               paperWidth=config["paperWidth"], resultUrl=f"{base_url()}/result/{s['id']}", courseName=COURSES[s["course"]]["name"],
               referenceType=reference_type(s.get("scores")), summary=qualitative_summary(s) if s.get("metrics") else None)
    if with_script:
        out["script"] = build_script(s["course"], s["demo"], s["seed"])
    return out


def new_session(course):
    if course not in COURSES:
        raise ValueError("올바른 코스를 선택하세요.")
    sid = str(uuid4())
    with store.lock:
        seed = len(store.all())
        s = {"id": sid, "code": "ORI-" + sid[:6].upper(), "course": course, "status": "waiting", "demo": config["mode"] == "demo", "seed": seed,
             "consent": False, "aiConsent": False, "researchConsent": False, "step": -1, "stepStartedMs": None,
             "answers": {}, "answerLatency": {}, "notes": {}, "marks": {}, "scores": None, "scoreMissing": None, "metrics": None, "responses": None,
             "report": None, "reportPending": False, "feedback": None, "createdAt": now(), "startedAt": None, "completedAt": None,
             "protocol": PROTOCOL, "instrument": INSTRUMENT, "adcUnit": "uncalibrated_u16", "nominalHz": 20, "price": config["prices"].get(course)}
        store.save(s)
        store.event(sid, "created", 0, {"protocol": PROTOCOL, "synthetic": s["demo"], "course": course})
    return s


def operator():
    if is_operator():
        return None
    return jsonify(error="운영 기능은 노트북의 localhost 에서만 쓸 수 있어요. 태블릿은 세션 QR 로 입장하세요."), 403


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
    if not ALLOW_REMOTE_OPERATOR:
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
    return jsonify(error="작업에 실패했어요. 터미널 로그를 확인하세요."), 500


# ---------------------------------------------------------------- 정적 화면
@app.get("/")
@app.get("/tablet")
@app.get("/result/<sid>")
def frontend(sid=None):
    return send_from_directory(ROOT / "static", "index.html")


@app.get("/icon.svg")
def icon():
    return send_from_directory(ROOT / "static", "icon.svg")


@app.get("/api/health")
def health():
    return jsonify(status="ok", project="oriori_gsr", version="2.0.0", mode=config["mode"], protocol=PROTOCOL)


@app.get("/api/qr")
def qr_png():
    """호출자가 준 텍스트를 QR PNG 로. 비밀을 만들지 않으므로 공개 (길이 제한)."""
    import qrcode
    text = request.args.get("text", "")
    if not text or len(text) > 300:
        raise ValueError("QR 텍스트를 확인하세요.")
    buf = io.BytesIO()
    qrcode.make(text, box_size=6, border=2).save(buf, format="PNG")
    return Response(buf.getvalue(), mimetype="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/meta")
def meta():
    return jsonify(courses=COURSES, prices=config["prices"], items=BIG5_ITEMS, scale=SCALE, labels=LABELS, protocol=PROTOCOL, instrument=INSTRUMENT)


# ---------------------------------------------------------------- 운영자
@app.get("/api/workspace")
def workspace():
    denied = operator()
    if denied:
        return denied
    prefs = {"demo": config["mode"] == "demo", "printer": config["printer"], "paperWidth": config["paperWidth"], "serialPort": config["serialPort"], "baudRate": str(config["baudRate"]),
             "adcRisesWithArousal": bool(config.get("adcRisesWithArousal", True)), "schoolApprovalConfirmed": bool(config.get("schoolApprovalConfirmed")), "checklist": config.get("checklist", []), "prices": config["prices"]}
    return jsonify(sessions=[public_session(s) for s in store.all()], settings=prefs, version="2.0.0", llmAvailable=llm_ready(), llmModel=llm_model(), llmThinking="disabled", codebook=CODEBOOK,
                   tabletBase=base_url(), devices={"pico": collector.status()["connected"], "printer": config["printer"] != "browser"}, active=store.active, courses=COURSES)


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
        for key in ("serialPort", "printer", "paperWidth", "checklist", "adcRisesWithArousal"):
            if key not in b:
                continue
            if key == "printer" and b[key] not in ("browser", "win32", "usb", "network"):
                raise ValueError("올바른 프린터 방식을 선택하세요.")
            if key == "paperWidth" and str(b[key]) not in ("58", "80"):
                raise ValueError("용지 너비를 확인하세요.")
            if key == "serialPort" and (not isinstance(b[key], str) or len(b[key]) > 80):
                raise ValueError("포트를 확인하세요.")
            if key == "checklist" and (not isinstance(b[key], list) or any(type(i) is not int or not 0 <= i < 12 for i in b[key])):
                raise ValueError("체크리스트 형식을 확인하세요.")
            if key == "adcRisesWithArousal" and not isinstance(b[key], bool):
                raise ValueError("극성 값은 true/false 여야 합니다.")
            config[key] = b[key]
        atomic_json(ROOT / "config.json", config)
    return jsonify(ok=True)


@app.post("/api/sessions")
def create_session():
    denied = operator()
    if denied:
        return denied
    return jsonify(public_session(new_session(request.get_json().get("course")), True)), 201


def finish(sid, s):
    samples = store.raw(sid)
    if not samples:
        raise ValueError("기록된 센서 데이터가 없습니다. 연결을 확인하세요. (중단하면 부분 데이터는 보존됩니다)")
    if not s["demo"] and not collector.status()["connected"]:
        raise ValueError("센서 연결이 끊어졌습니다. 다시 연결한 뒤 완료하거나, 중단하세요.")
    for qid, text in (s.get("notes") or {}).items():
        store.event(sid, "note", None, {"questionId": qid, "text": text})
    script = build_script(s["course"], s["demo"], s["seed"])
    elapsed = store.host_ms()
    store.event(sid, "measurement_end", None, {"synthetic": s["demo"]})
    metrics, responses = compute_features(samples, store.event_rows(sid), script, s, bool(config.get("adcRisesWithArousal", True)))
    metrics["observedHz"] = round(len(samples) / (elapsed / 1000), 2) if elapsed else None
    metrics["missingSequenceCount"] = sum(max(0, int(b["seq"] - a["seq"] - 1)) for a, b in zip(samples, samples[1:]))
    s["scores"], s["scoreMissing"] = score_answers(s.get("answers") or {})
    s.update(metrics=metrics, responses=responses, status="completed", completedAt=now(), step=len(script) - 1)
    s["report"] = rule_report(s)
    s["reportPending"] = bool(s["course"] == "deep" and s["aiConsent"] and llm_ready())
    store.active = None
    store.pulses = []


@app.route("/api/sessions/<sid>", methods=["GET", "PATCH", "DELETE"])
def session_route(sid):
    s = store.get(sid)
    if request.method == "GET":
        # 태블릿은 view=tablet 을 붙여 요청 → 운영 PC 에서 열어도(디버그 플래그 포함) 보류 문장을 받지 않는다.
        return jsonify(public_session(s, request.args.get("script") == "1", is_operator() and request.args.get("view") != "tablet"))
    if request.method == "DELETE":
        denied = operator()
        if denied:
            return denied
        store.delete(sid)
        return jsonify(ok=True)
    b = request.get_json()
    action = b.get("action")
    if action not in PARTICIPANT_ACTIONS:
        denied = operator()
        if denied:
            return denied
    with store.lock:
        s = store.get(sid)
        script = build_script(s["course"], s["demo"], s["seed"])
        if action == "consent":
            if s["status"] != "waiting":
                raise ValueError("이미 시작한 세션입니다.")
            s.update(consent=True, aiConsent=b.get("aiConsent") is True, status="consented")
            store.event(sid, "consent", 0, {"version": "2.0", "experience": True, "research": False, "ai_claude": s["aiConsent"]})
        elif action == "start":
            if s["status"] != "consented":
                raise ValueError("참가자 동의를 먼저 받아 주세요 (태블릿).")
            if store.active and store.active != sid:
                raise ValueError("다른 참가자의 측정이 진행 중입니다.")
            if not s["demo"]:
                if not config.get("schoolApprovalConfirmed"):
                    raise ValueError("학교 승인·보호자 동의 확인 후 config.json 의 schoolApprovalConfirmed 를 true 로 바꾸세요.")
                if not collector.status()["connected"]:
                    raise ValueError("Pico 신호가 없습니다. Thonny 종료, 포트, 배선을 확인하세요.")
            store.start_ns = time.monotonic_ns()
            store.active = sid
            store.pulses = []
            s.update(status="running", startedAt=now(), step=0, stepStartedMs=0)
            store.event(sid, "measurement_start", 0)
            store.event(sid, "step_start", 0, {"index": 0, **{k: script[0].get(k) for k in ("id", "kind", "category", "direction") if script[0].get(k)}})
        elif action == "step":
            if s["status"] != "running" or store.active != sid:
                raise ValueError("진행 중인 세션이 아닙니다.")
            index = b.get("index")
            if type(index) is not int or not 0 <= index < len(script):
                raise ValueError("단계 번호를 확인하세요.")
            st = script[index]
            host = store.event(sid, "step_start", None, {"index": index, **{k: st.get(k) for k in ("id", "kind", "category", "direction") if st.get(k)}})
            s.update(step=index, stepStartedMs=js_round(host or 0))
            if s["demo"]:
                cat = st.get("category") or ("gaze_" + st["direction"] if st["kind"] == "gaze" else st["kind"])
                if cat in DEMO_PULSE and st["kind"] != "question" and st["kind"] != "interview":
                    store.pulses.append(((host or 0) / 1000, DEMO_PULSE[cat]))
        elif action == "mark":
            if s["status"] != "running" or store.active != sid:
                raise ValueError("진행 중인 세션이 아닙니다.")
            kind, qid = b.get("kind"), b.get("questionId")
            if kind not in ("asked_end", "answer_start", "answer_end") or not isinstance(qid, str):
                raise ValueError("표시 종류를 확인하세요.")
            host = store.event(sid, "mark", None, {"questionId": qid, "kind": kind})
            s["marks"].setdefault(qid, {})[kind] = js_round(host or 0)
            if s["demo"] and kind == "asked_end":
                st = next((x for x in script if x["id"] == qid), None)
                if st and st.get("category") in DEMO_PULSE:
                    store.pulses.append(((host or 0) / 1000, DEMO_PULSE[st["category"]]))
        elif action == "answer":
            if s["status"] != "running" or store.active != sid:
                raise ValueError("진행 중인 세션이 아닙니다.")
            item_id, value = b.get("itemId"), b.get("value")
            if item_id not in {i["id"] for i in BIG5_ITEMS} or type(value) is not int or not 1 <= value <= 5:
                raise ValueError("응답 값을 확인하세요.")
            host = store.event(sid, "answer", None, {"itemId": item_id, "value": value, "source": b.get("source") if b.get("source") in ("tablet", "operator") else "unknown"})
            s["answers"][item_id] = value
            if script[s["step"]]["id"] == item_id and s.get("stepStartedMs") is not None and item_id not in s["answerLatency"]:
                s["answerLatency"][item_id] = js_round((host or 0) - s["stepStartedMs"])
        elif action == "note":
            if s["status"] != "running":
                raise ValueError("진행 중인 세션이 아닙니다.")
            qid, text = b.get("questionId"), b.get("text")
            if not isinstance(qid, str) or not isinstance(text, str) or len(text) > 1000:
                raise ValueError("메모 형식을 확인하세요.")
            s["notes"][qid] = text
        elif action == "complete":
            if s["status"] == "completed":
                return jsonify(public_session(s))
            if s["status"] != "running" or store.active != sid:
                raise ValueError("진행 중인 세션이 아닙니다.")
            finish(sid, s)
        elif action == "stop":
            if s["status"] in ("completed", "stopped"):
                raise ValueError("이미 종료된 세션입니다.")
            store.event(sid, "participant_stop", None, {"from": "tablet" if request.remote_addr not in ("127.0.0.1", "::1") else "operator"})
            s["status"] = "stopped"
            if store.active == sid:
                store.active = None
                store.pulses = []
        elif action == "edit_report":
            if s["status"] != "completed" or not s.get("report"):
                raise ValueError("완료된 세션의 문장만 수정할 수 있어요.")
            rep_ = dict(s["report"])
            if not rep_.get("original"):
                rep_["original"] = {k: rep_.get(k) for k in ("title", "character", "lackMeaning", "takeHome", "oneLine")}
            for k, limit in (("title", 40), ("character", 900), ("lackMeaning", 900), ("takeHome", 120), ("oneLine", 80)):
                if k in b:
                    v = b[k]
                    if v is not None and (not isinstance(v, str) or len(v) > limit):
                        raise ValueError(f"{k} 길이를 확인하세요.")
                    rep_[k] = v.strip() if isinstance(v, str) and v.strip() else None
            if not rep_.get("character"):
                raise ValueError("본문(character)은 비울 수 없어요.")
            rep_["editedByOperator"] = True
            s["report"] = rep_
            store.event(sid, "report_edited", 0, {"fields": [k for k in ("title", "character", "lackMeaning", "takeHome", "oneLine") if k in b]})
        elif action == "release_report":
            if s["status"] != "completed" or not s.get("report"):
                raise ValueError("완료된 세션이 아닙니다.")
            s["report"] = {**s["report"], "held": False, "reviewedByOperator": True}
            store.event(sid, "report_released", 0, {"safetyFlag": bool(s["report"].get("safetyFlag"))})
        elif action == "feedback":
            if s["status"] != "completed" or (s.get("report") or {}).get("held"):
                raise ValueError("완료된 세션만 평가할 수 있어요.")
            acc, res = b.get("accuracy"), b.get("resonant")
            if type(acc) is not int or not 1 <= acc <= 5 or (res is not None and (not isinstance(res, str) or len(res) > 300)):
                raise ValueError("평가 값을 확인하세요.")
            s["feedback"] = {"accuracy": acc, "resonant": res, "reportSource": (s.get("report") or {}).get("source"), "at": now()}
            store.event(sid, "feedback", 0, s["feedback"])
        else:
            raise ValueError("지원하지 않는 동작입니다.")
        store.save(s)
    return jsonify(public_session(s, False, is_operator()))


@app.post("/api/sessions/<sid>/events")
def events(sid):
    """브라우저 측 보조 이벤트(가시성 변화 등). 자극/응답 시각은 서버 시계 기준 mark/answer 를 쓴다."""
    store.get(sid)
    b = request.get_json()
    if not isinstance(b.get("type"), str) or len(b["type"]) > 80:
        raise ValueError("이벤트 형식을 확인하세요.")
    store.event(sid, "client_" + b["type"], None, b.get("payload", {}))
    return jsonify(ok=True)


@app.post("/api/sessions/<sid>/report")
def report(sid):
    denied = operator()
    if denied:
        return denied
    s = store.get(sid)
    if s["status"] != "completed":
        raise ValueError("검사를 먼저 완료하세요.")
    if time.time() - s.get("_lastReport", 0) < 10:
        return jsonify(report=s["report"], reportPending=False)
    result = generate_report(s)
    with store.lock:
        s = store.get(sid)
        s.update(report=result, reportPending=False, _lastReport=time.time())
        store.save(s)
        store.event(sid, "report_generated", 0, {"source": result["source"], "model": result.get("model"), "promptVersion": result.get("promptVersion"), "thinking": result.get("thinking"), "notes": result.get("notes"), "safetyFlag": result.get("safetyFlag"), "error": result.get("error")})
    return jsonify(report=result, reportPending=False)


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
    result = send_receipt(s, {**config, "paperWidth": width}, f"{base_url()}/result/{sid}", store.folder(sid))
    store.event(sid, "print_requested", 0, {"mode": config["printer"], "browser": result["browser"]})
    return jsonify(result)


@app.get("/api/export")
def export():
    """CSV 는 UTF-8 BOM 포함 → 엑셀에서 더블클릭으로 바로 열림."""
    denied = operator()
    if denied:
        return denied
    sid, kind = request.args.get("id"), request.args.get("kind", "sessions")
    selected = [store.get(sid)] if sid else store.all()
    if request.args.get("format") == "json":
        payload = {"project": "oriori_gsr", "protocol": PROTOCOL, "instrument": INSTRUMENT, "adcUnit": "uncalibrated_u16", "researchApproved": False, "exportedAt": now(),
                   "sessions": [public_session(s) for s in selected], "raw": [{"sessionId": s["id"], "samples": store.raw(s["id"])} for s in selected], "events": [{"sessionId": s["id"], "events": store.event_rows(s["id"])} for s in selected]}
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
    elif kind == "responses":
        writer = csv.DictWriter(output, RESPONSE_FIELDS)
        writer.writeheader()
        for s in selected:
            for r in s.get("responses") or []:
                writer.writerow({"session_id": s["id"], "course": s["course"], "synthetic": s["demo"], "event_id": r["eventId"], "category": r["category"], "onset_ms": r["onsetMs"], "pre_mean_adc": r["preMean"],
                                 "amplitude_adc": r["amplitude"], "z_baseline": r["z"], "latency_ms": r["latencyMs"], "answer": r["answer"], "note": r["note"]})
    else:
        writer = csv.writer(output)
        item_cols = [i["id"] for i in BIG5_ITEMS]
        writer.writerow(["id", "code", "course", "status", "demo", "created_at", "ai_consent", *LABELS, "reference_4letter", *item_cols, "baseline_adc", "baseline_sd", "quality_pct", "observed_hz",
                         "gaze_direct_z", "gaze_averted_z", "q_neutral_z", "q_self_z", "q_social_z", "i_lack_z", "i_filled_z", "i_meaning_z", "question_latency_median_ms", "big5_latency_median_ms",
                         "report_source", "report_model", "prompt_version", "report_title", "take_home", "code_lack", "code_filled", "code_meaning", "affect_tone", "safety_flag", "edited_by_operator",
                         "feedback_accuracy", "feedback_resonant", "research_consent"])
        for s in selected:
            sc, m, cz, rep, fb = s.get("scores") or {}, s.get("metrics") or {}, (s.get("metrics") or {}).get("categoryZ") or {}, s.get("report") or {}, s.get("feedback") or {}
            codes = rep.get("codes") or {}
            writer.writerow([s["id"], s["code"], s["course"], s["status"], s["demo"], s["createdAt"], s["aiConsent"], *[sc.get(k) for k in LABELS], reference_type(sc), *[(s.get("answers") or {}).get(c) for c in item_cols],
                             m.get("baseline"), m.get("baselineSd"), m.get("quality"), m.get("observedHz"), cz.get("gaze_direct"), cz.get("gaze_averted"), cz.get("question_neutral"), cz.get("question_self"), cz.get("question_social"),
                             cz.get("interview_lack"), cz.get("interview_filled"), cz.get("interview_meaning"), m.get("questionLatencyMedianMs"), m.get("big5LatencyMedianMs"),
                             rep.get("source"), rep.get("model"), rep.get("promptVersion"), rep.get("title"), rep.get("takeHome"), "|".join(codes.get("lackDomain") or []), "|".join(codes.get("filledContext") or []),
                             "|".join(codes.get("meaningSource") or []), codes.get("affectTone"), rep.get("safetyFlag"), rep.get("editedByOperator"), fb.get("accuracy"), fb.get("resonant"), False])
    name = kind if kind in ("raw", "events", "responses") else "sessions"
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=oriori_gsr_{name}.csv"})


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
                z.write(ROOT / "config.example.json" if str(rel) == "config.json" else p, "oriori_gsr/" + str(rel))
    return Response(stream.getvalue(), mimetype="application/zip", headers={"Content-Disposition": "attachment; filename=oriori_gsr.zip"})


if __name__ == "__main__":
    from waitress import serve
    store.recover_and_expire(int(config.get("retentionDays", 30)))
    collector.start()
    host = lan_ip()
    port = int(os.environ.get("ORIORI_PORT", config["port"]))
    print("\n=== oriori_gsr v2.0 ===", flush=True)
    print(f"Operator: http://127.0.0.1:{port}", flush=True)
    print(f"Tablet:   http://{host}:{port}/tablet   (같은 핫스팟, localhost 아님)", flush=True)
    print(f"Mode: {config['mode']} | Claude: {('ON · ' + llm_model() + ' · thinking off') if llm_ready() else 'OFF (.env 에 ANTHROPIC_API_KEY)'} | Data: {DATA}", flush=True)
    if ALLOW_REMOTE_OPERATOR:
        print("WARNING: ORIORI_ALLOW_REMOTE_OPERATOR=1 — 운영 API 가 네트워크에 열려 있습니다. 현장에서는 끄세요.", flush=True)
    print("이 창을 닫지 마세요. Ctrl+C 로 종료.\n", flush=True)
    if not os.environ.get("ORIORI_NO_BROWSER"):
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    try:
        serve(app, host="0.0.0.0", port=port, threads=8, max_request_body_size=256 * 1024)
    except KeyboardInterrupt:
        collector.running = False
