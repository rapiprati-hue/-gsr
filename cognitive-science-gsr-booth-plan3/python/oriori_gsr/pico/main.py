# oriori_gsr v2 / MicroPython on Raspberry Pi Pico
# 이 파일만 Thonny 로 Pico 에 "main.py" 이름으로 저장하고, Thonny 를 완전히 종료하세요.
# 연결 전 확인: 모든 신호선은 0~3.3V. 5V 를 ADC/GPIO 에 직결하지 마세요.
# 핀 이름은 GPIO 번호(물리 핀 번호 아님). GSR SIG → GP26(물리 31), GND 공통, VCC 는 모듈 사양(3.3V 지원 시 3V3 OUT 물리 36).
from machine import ADC, Pin
import time
import json

GSR_PIN = 26          # ADC0, 물리 핀 31
BUTTON_PIN = 14       # 물리 핀 19 (KS0029 등 푸시버튼, 선택)
USE_BUTTON = True
BUTTON_ACTIVE_LOW = True   # 모듈 사양 확인. 눌렀을 때 0 이면 True
SOUND_PIN = 27        # ADC1, 물리 핀 32. 아날로그 출력(AO) 있는 모듈만. 기본 사용 안 함
USE_SOUND = False
SAMPLE_MS = 50        # 20 Hz

gsr = ADC(Pin(GSR_PIN))
button = Pin(BUTTON_PIN, Pin.IN, Pin.PULL_UP if BUTTON_ACTIVE_LOW else Pin.PULL_DOWN) if USE_BUTTON else None
sound = ADC(Pin(SOUND_PIN)) if USE_SOUND else None

start = time.ticks_ms()
next_sample = start
last_change = start
previous_raw = button.value() if button else 0
stable_button = previous_raw
seq = 0

while True:
    tick = time.ticks_ms()
    if button:
        raw_button = button.value()
        if raw_button != previous_raw:
            last_change = tick
            previous_raw = raw_button
        if time.ticks_diff(tick, last_change) >= 40:      # 40 ms 디바운스
            stable_button = raw_button
    if time.ticks_diff(tick, next_sample) >= 0:
        # 잡음 완화: 4회 평균 (약 0.4 ms)
        total = 0
        for _ in range(4):
            total += gsr.read_u16()
        pressed = 0
        if button:
            pressed = int(stable_button == (0 if BUTTON_ACTIVE_LOW else 1))
        print(json.dumps({
            "seq": seq,
            "t": time.ticks_diff(tick, start),
            "adc": total // 4,
            "button": pressed,
            "sound": sound.read_u16() if sound else None,
        }))
        seq += 1
        next_sample = time.ticks_add(next_sample, SAMPLE_MS)
        if time.ticks_diff(tick, next_sample) >= SAMPLE_MS:   # USB 지연으로 밀렸으면 샘플을 지어내지 않고 재정렬
            next_sample = time.ticks_add(tick, SAMPLE_MS)
    time.sleep_ms(2)
