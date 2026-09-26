"""오프라인 재현 분석. 라이브러리 추가 없이 data/ 폴더에서 다시 계산한다 (진단·인과 결론 없음).

사용:  python analyze.py                # 실제(하드웨어) 완료 세션만
       python analyze.py --include-demo # 합성 데모도 포함 (연습용)
출력:  analysis_sessions.csv  세션 1행 요약 (Big5, 범주별 z, 반응시간 중앙값, 평가)
       analysis_responses.csv 자극 1행 (혼합모형/조건 비교용 long 형식)
       화면: 범주별 z 평균과 눈맞춤 직접-회피 차이의 부호 검정(간단 기술통계)
"""
import argparse
import csv
import json
import statistics
from pathlib import Path
from engine import DATA, LABELS, build_script, compute_features, CATEGORY_LABELS


def run():
    parser = argparse.ArgumentParser(description="oriori_gsr reproducible re-analysis")
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument("--include-demo", action="store_true", help="합성 데모 포함 (참가자 데이터로 취급 금지)")
    parser.add_argument("--polarity-rises", type=int, default=1, help="1: 각성 시 ADC 상승, 0: 하강 (현장 극성 확인 결과)")
    args = parser.parse_args()
    session_rows, response_rows = [], []
    for meta in sorted(args.data_dir.glob("*/session.json")):
        s = json.loads(meta.read_text(encoding="utf-8"))
        if s["status"] != "completed" or (s["demo"] and not args.include_demo):
            continue
        raw_path, ev_path = meta.parent / "raw.csv", meta.parent / "events.csv"
        if not raw_path.exists() or not ev_path.exists():
            continue
        with raw_path.open(newline="", encoding="utf-8") as f:
            samples = [{"t": int(r["t"]), "adc": int(r["adc"])} for r in csv.DictReader(f) if r.get("t") and r.get("adc")]
        with ev_path.open(newline="", encoding="utf-8") as f:
            events = list(csv.DictReader(f))
        script = build_script(s["course"], s["demo"], s.get("seed", 0))
        metrics, responses = compute_features(samples, events, script, s, bool(args.polarity_rises))
        cz = metrics["categoryZ"]
        session_rows.append({"session_id": s["id"], "course": s["course"], "synthetic": s["demo"], "created_at": s["createdAt"], **{f"big5_{k}": (s.get("scores") or {}).get(k) for k in LABELS},
                             **{f"z_{k}": cz.get(k) for k in CATEGORY_LABELS}, "gaze_contrast": metrics["contrasts"].get("gazeDirectMinusAverted"),
                             "question_latency_median_ms": metrics["questionLatencyMedianMs"], "baseline_adc": metrics["baseline"], "baseline_sd": metrics["baselineSd"], "quality_pct": metrics["quality"],
                             "report_source": (s.get("report") or {}).get("source"), "feedback_accuracy": (s.get("feedback") or {}).get("accuracy"), "protocol": s.get("protocol")})
        for r in responses:
            response_rows.append({"session_id": s["id"], "course": s["course"], "synthetic": s["demo"], **r})
    with open("analysis_sessions.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(session_rows[0].keys()) if session_rows else ["session_id"])
        w.writeheader(); w.writerows(session_rows)
    with open("analysis_responses.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(response_rows[0].keys()) if response_rows else ["session_id"])
        w.writeheader(); w.writerows(response_rows)
    print(f"세션 {len(session_rows)}건, 자극 {len(response_rows)}행 저장. 합성 포함: {args.include_demo}")
    for k, label in CATEGORY_LABELS.items():
        vals = [r[f"z_{k}"] for r in session_rows if r.get(f"z_{k}") is not None]
        if vals:
            print(f"  {label:<14} n={len(vals):>3}  z 평균 {statistics.mean(vals):6.2f}  중앙값 {statistics.median(vals):6.2f}")
    contrasts = [r["gaze_contrast"] for r in session_rows if r.get("gaze_contrast") is not None]
    if contrasts:
        pos = sum(c > 0 for c in contrasts)
        print(f"  눈맞춤 직접 > 회피 인 참가자: {pos}/{len(contrasts)} (부호 검정용 기술통계. 표본이 작으면 해석 보류)")
    fb = [(r["report_source"], r["feedback_accuracy"]) for r in session_rows if r.get("feedback_accuracy")]
    for src in sorted({x for x, _ in fb}):
        vals = [a for x, a in fb if x == src]
        print(f"  결과 문장 정확도 평가 [{src}] n={len(vals)} 평균 {statistics.mean(vals):.2f}")
    print("보정 전 ADC · 편의표본 · 탐색적. 인과/진단/성격 예측 주장 금지.")


if __name__ == "__main__":
    run()
