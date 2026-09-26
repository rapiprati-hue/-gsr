# oriori_gsr / 데이터 사전 v1.0

## 해석 전제
- protocol: `oriori-exploratory-v1`; instrument: `original-10-exploratory-not-validated`.
- `demo=true`, `source=synthetic`는 **합성 예제**. 실제 데이터와 합쳐 분석하지 않음.
- 원시 ADC는 보정 전 디지털 값. `read_u16`의 0–65535 범위는 Pico의 물리적 16bit 정확도를 뜻하지 않음(RP2040 ADC는 12bit).
- μS, dB, 절대 각성, 성격/감정 진단값이 아님.

## raw.csv
| 변수 | 단위/정의 | 주의 |
|---|---|---|
| seq | 기기 샘플 순번 | 재시작 시 0으로 리셋. 누락/역행 별도 확인 |
| t | 세션 시작 기준 호스트 수신 경과 ms | 브라우저 렌더링 시각과 같은 시계 아님 |
| adc | GSR ADC u16 원시값 | 포화, 움직임, 전극 접촉의 영향 |
| temperature | DHT11 °C | 2초마다 갱신; 실패 시 null/빈칸, 자동 보정에 사용하지 않음 |
| humidity | DHT11 상대습도 % | 데이터시트 정확도 한계, 센서 안정화 필요 |
| sound | 사운드 AO ADC u16 | 상대 주변 소음 지표일 뿐 dB/발화 인식 아님 |
| button | 디바운스 후 0/1 | 약 40ms 디바운스 + 폴링/샘플링 지연 |
| device_ms | Pico 시작 이후 ticks_diff ms | 장시간 ticks wrap/리셋 가능; 실제 수신 시각과 다름 |
| host_monotonic_ns | Python monotonic ns | 같은 부팅/프로세스 맥락 내 간격 분석용 |
| host_unix_ns | Unix timestamp ns | 벽시계. NTP 조정 영향 가능 |
| source | hardware / synthetic | 항상 보존 |

웹 미리보기 내보내기에서는 필드명이 `elapsed_ms`, `adc_u16`, `temperature_c` 등으로 단위를 명시합니다. 웹 합성 신호에는 실제 기기/호스트 수신 시각이 존재하지 않습니다. 로컬 파일과 합칠 때 이름과 단위를 명시적으로 매핑하세요.

## events.csv
- type: `created`, `consent`, `measurement_start`, `stage_start`, `stage_end`, `stimulus`, `social_stimulus`, `reaction`, `hardware_button`, `awareness`, `speech_skipped`, `false_start`, `visibility`, `device_clock_reset`, `measurement_end`, `participant_stop`, `interrupted_restart`, `print_requested`, `demo_seed`.
- elapsedMs: 브라우저가 전송한 세션 기준 경과 ms 또는 호스트 장비 이벤트의 경과 ms. 이벤트 source/clock을 확인.
- hostElapsedMs: 서버가 이벤트를 받은 시점의 monotonic 세션 기준 ms. 네트워크 지연이 포함됨.
- serverTime: UTC ISO 8601.
- payload: JSON. 브라우저 stimulus/reaction에는 trial, performance 시각 또는 reactionMs; 가시성/건너뛰기/동의 버전 포함.
- 서로 다른 시계의 timestamp를 직접 빼지 마세요. 브라우저 reactionMs는 동일 브라우저 performance 시계에서 계산하지만 화면 vsync/터치 지연은 포함됩니다. 하드웨어 버튼은 원시 시각을 보존하며 표준 반응시간 장비의 정밀도를 주장하지 않습니다.
- 키보드/마우스/터치/Pico 버튼의 결과를 같은 품질의 반응시간으로 섞지 마세요.
- 이벤트와 파일 수신 순서만으로 인과·정확한 자극 온셋을 주장하지 마세요. 화면 백그라운드 전환은 visibility 이벤트로 표시됩니다.

## session.json
- id: 랜덤 UUID(세션 링크의 비밀 토큰). code: 화면용 짧은 ID.
- course: basic/relation/full; status: waiting/questionnaire/ready/measuring/completed/stopped.
- consent: 체험/저장 동의. aiConsent: 요약값 OpenAI 전송 동의. researchConsent: 항상 false.
- answers: 1–5 응답 배열 10개, 문항 순서는 PROTOCOL.md. 공란/범위 외는 거부.
- scores: O/C/E/A/N. 양방향 문항 두 개씩 평균하여 범위를 0–100 환산. 백분위/확률 아님.
- metrics.baseline: 기준선 구간 ADC 평균, 반올림.
- metrics.change: `(과제구간 평균ADC - 기준선 평균ADC) / 기준선 평균ADC * 100`, 소수 1자리. 전도도 변화로 해석 금지.
- metrics.peak: 세션 중 ADC 최댓값. SCR peak 검출값 아님.
- metrics.quality: `500 < adc < 65000`인 샘플 비율. **임의 레일 근접 검사**이며 접촉 품질/전체 신호 신뢰도를 보장하지 않음.
- metrics.samples: 실제 저장된 샘플 수. duration: 마지막 raw 경과시간(초 반올림).
- metrics.observedHz: 로컬 실제 샘플 수 / 세션 측정시간. 목표 20Hz와 구분.
- metrics.missingSequenceCount: 인접 seq 간 양의 누락 수 합. 리셋은 별도 device_clock_reset 이벤트.
- metrics.reactionMs: 화면 반응시간 평균(있을 때 우선), 또는 화면 응답이 없을 때 호스트 수신 기준 물리 버튼 근삿값. null이면 미수집. metrics.reactionClock의 `browser_performance`와 `host_receipt_approx`를 구분하고 서로 섞지 말 것. 물리 버튼 근삿값에는 Wi-Fi·폴링·디바운스 지연이 포함되며 연구용 정밀 반응시간이 아님. 원시 반응 분포를 별도로 검토.
- host_monotonic_ns / host_unix_ns: JavaScript의 정수 정밀도 손실을 방지하기 위해 CSV/JSON에서 십진 문자열로 보존. 분석 시 Python int 등 64bit 이상 정수로 읽을 것. 서버 기준 serverNow와 브라우저 performance 시계로 UI 진행 시간을 맞추지만 자극 시계 간 정밀 동기화를 보장하지 않음.
- metrics.temperature/humidity: 마지막 유효 환경값. 전체 변화는 raw를 확인.
- reportSource: rules / llm / rules-fallback. 계산 결과와 AI 문장을 분리해서 보존.
- createdAt/startedAt/completedAt: UTC ISO8601.

## 제외·보고 원칙
결측, 동작 아티팩트, 레일 근접, 수면/카페인/실온, 착용 위치, 자극 순서, 디바운스/네트워크 지연은 한계입니다. 어떤 데이터를 왜 제외했는지 기록하고 사후적으로 유리한 데이터만 고르지 마세요. 본 도구는 검증된 SCR 분해/환경 보정/연구용 척도를 제공하지 않습니다. 표준 척도와 장비를 도입하면 protocol/instrument 버전을 바꾸고 이전 체험 데이터와 구분해야 합니다.
