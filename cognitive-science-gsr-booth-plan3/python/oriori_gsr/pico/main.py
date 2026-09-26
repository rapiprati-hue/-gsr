# oriori_gsr / MicroPython on Raspberry Pi Pico
# Save this file as main.py ON THE PICO with Thonny, then close Thonny.
# BEFORE CONNECTING: verify every signal stays within 0..3.3V. Never connect 5V to ADC/GPIO.
# Pin names are GPIO numbers, not physical pin numbers.
from machine import ADC, Pin
import time
import json
import dht

GSR_PIN = 26       # ADC0, physical pin 31
SOUND_PIN = 27     # ADC1, physical pin 32; analog output ONLY, 0..3.3V
BUTTON_PIN = 14    # physical pin 19
DHT_PIN = 15       # physical pin 20
BUTTON_ACTIVE_LOW = True  # Verify your KS0029 module before use.
USE_SOUND = True
USE_DHT = True

gsr = ADC(Pin(GSR_PIN))
sound = ADC(Pin(SOUND_PIN)) if USE_SOUND else None
button = Pin(BUTTON_PIN, Pin.IN, Pin.PULL_UP if BUTTON_ACTIVE_LOW else Pin.PULL_DOWN)
sensor = dht.DHT11(Pin(DHT_PIN)) if USE_DHT else None
start = time.ticks_ms()
next_sample = start
last_dht = time.ticks_add(start, -2000)
last_change = start
previous_raw = button.value()
stable_button = previous_raw
temperature = None
humidity = None
seq = 0

while True:
    tick = time.ticks_ms()
    raw_button = button.value()
    if raw_button != previous_raw:
        last_change = tick
        previous_raw = raw_button
    if time.ticks_diff(tick, last_change) >= 40:
        stable_button = raw_button
    if sensor and time.ticks_diff(tick, last_dht) >= 2000:
        last_dht = tick
        try:
            sensor.measure()
            temperature = sensor.temperature()
            humidity = sensor.humidity()
        except OSError:
            temperature = None
            humidity = None
    if time.ticks_diff(tick, next_sample) >= 0:
        tick = time.ticks_ms()
        print(json.dumps({
            "seq": seq,
            "t": time.ticks_diff(tick, start),
            "adc": gsr.read_u16(),
            "temperature": temperature,
            "humidity": humidity,
            "sound": sound.read_u16() if sound else None,
            "button": int(stable_button == (0 if BUTTON_ACTIVE_LOW else 1)),
        }))
        seq += 1
        next_sample = time.ticks_add(next_sample, 50)
        # Do not invent/backfill samples after blocking DHT/USB operations.
        if time.ticks_diff(tick, next_sample) >= 50:
            next_sample = time.ticks_add(tick, 50)
    time.sleep_ms(2)
