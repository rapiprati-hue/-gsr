# oriori_gsr / 데이터 사전 v2

모든 CSV 는 UTF-8 BOM → 엑셀에서 더블클릭으로 열린다. `demo=true / synthetic=true` 는 합성 데모이며 참가자 데이터와 합치지 않는다. ADC 는 보정 전 u16 값(μS 아님).

## 파일 위치
`data/<세션 UUID>/session.json`, `raw.csv`, `events.csv`, (직접 인쇄 시) `receipt.png`. 운영 화면 **데이터** 메뉴에서 전체를 CSV/JSON 으로 내려받는다.

## 내보내기 4종
| 파일 | 행 단위 | 용도 |
|---|---|---|
| `oriori_gsr_sessions.csv` | 세션 | 요약표: Big5, 문항 응답, 범주별 z, 지연 중앙값, 서사 출처, 참가자 평가 |
| `oriori_gsr_responses.csv` | 자극(이벤트) | **논문용 long 형식**: 범주 × 반응 × 지연 × 메모 |
| `oriori_gsr_raw.csv` | 샘플(20 Hz) | 재분석, SCR 분해 |
| `oriori_gsr_events.csv` | 이벤트 | 단계·표시·응답·동의·중단·서사 생성 로그 |

## raw.csv
| 변수 | 의미 |
|---|---|
| seq | Pico 샘플 순번 (재시작 시 0) |
| t | 측정 시작 기준 서버 수신 경과 ms (**events.hostElapsedMs 와 같은 시계**) |
| adc | GSR ADC u16 (RP2040 은 실제 12bit) |
| button | 물리 버튼 0/1 (선택 장치) |
| sound | 사운드 모듈 AO (기본 미사용, 빈칸) |
| device_ms | Pico 내부 ticks 기준 ms |
| host_monotonic_ns / host_unix_ns | 서버 수신 시각(문자열로 보존) |
| source | hardware / synthetic |

## events.csv
`type, elapsedMs, hostElapsedMs, serverTime, payload(JSON)`.
- `step_start` payload `{index,id,kind,category?,direction?}` — 단계 시작. 문항·눈맞춤 onset.
- `mark` payload `{questionId, kind: asked_end|answer_start|answer_end}` — 운영자 Space.
- `answer` payload `{itemId, value, source: tablet|operator}`.
- `note` — 완료 시점에 인터뷰 메모를 로그로 남김.
- `consent {ai_claude}`, `measurement_start/end`, `participant_stop {from}`, `feedback`, `report_generated {source, model, promptVersion, thinking, notes, safetyFlag, error}`, `report_edited {fields}`, `report_released {safetyFlag}`, `print_requested`, `interrupted_restart`, `hardware_button`, `device_clock_reset`, `client_visibility`.

## responses.csv (session.json 의 `responses`)
| 변수 | 의미 |
|---|---|
| event_id | 단계 id (E1…O4, gaze1…gaze4, q_neutral, q_self, q_social, i_lack, i_filled, i_meaning) |
| category | big5 / gaze_direct / gaze_averted / question_neutral / question_self / question_social / interview_lack / interview_filled / interview_meaning |
| onset_ms | 반응 창 기준 시각 (질문·인터뷰는 asked_end) |
| pre_mean_adc | onset 직전 1초 평균 |
| amplitude_adc | 창(onset+1s~6s) 최대 편차 (각성 방향으로 부호화) |
| z_baseline | amplitude ÷ 기준선 SD |
| latency_ms | 질문·인터뷰: answer_start − asked_end · Big5: 응답 − 문항 시작(읽기 포함) |
| answer | Big5 응답 1–5 |
| note | 인터뷰 메모 (참가자 표현, 식별정보 없음) |

## session.json 주요 필드
- `course` basic/social/deep · `status` waiting/consented/running/completed/stopped · `seed` 눈맞춤 순서(짝수: 직접 먼저).
- `consent`, `aiConsent`(Claude 전송 선택 동의), `researchConsent`(항상 false).
- `answers {itemId: 1–5}`, `answerLatency`, `notes {questionId: text}`, `marks {questionId: {asked_end, answer_start, answer_end}}` (ms).
- `scores {O,C,E,A,N}` 0–100 (요인당 2문항 미만이면 null), `scoreMissing`.
- `metrics`: baseline, baselineSd, peak, samples, duration, quality(500<adc<65000 비율), categoryZ, contrasts, questionLatencyMedianMs, big5LatencyMedianMs, polarity, observedHz, missingSequenceCount.
- `report {title, character, lackMeaning, takeHome, oneLine, codes, safetyFlag, safetyNote, held, source: rules|claude|rules-fallback, model, promptVersion, thinking, notes[], usage, error?, editedByOperator?, original?, reviewedByOperator?}`.
  - `codes {lackDomain[], filledContext[], meaningSource[], affectTone}` — Claude 가 운영자 메모를 코드북 v2 로 분류한 값(최대 2개, 없으면 `none`). 코드북 라벨은 `engine.CODEBOOK`. 규칙 문장이면 `null`.
  - `safetyFlag/safetyNote` — 위기 신호 의심. `held=true` 인 동안 태블릿 API(`?view=tablet` 또는 원격 IP)는 `report=null, reportHeld=true` 를 받는다. `release_report` 후 `held=false, reviewedByOperator=true`.
  - `original` — 운영자가 `edit_report` 로 처음 수정할 때 보존되는 원문 5필드.
  - sessions CSV 열: `prompt_version, take_home, code_lack, code_filled, code_meaning, affect_tone, safety_flag, edited_by_operator` (다중 코드는 `|` 구분).
- `feedback {accuracy 1–5, resonant, reportSource, at}`.
- `protocol` = `oriori-live-social-v2`, `instrument` = `mini-ipip-20-ko-unofficial`.

## 해석 원칙
서로 다른 시계를 빼지 말 것(모든 분석은 `t`/`hostElapsedMs`). 절대 반응시간이 아니라 조건 간 차이. 제외한 데이터와 이유를 기록. 진단·감정 판독·성격 예측 주장 금지.
