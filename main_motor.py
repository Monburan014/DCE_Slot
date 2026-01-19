import RPi.GPIO as GPIO
import time
import random
import board
import busio
from adafruit_pca9685 import PCA9685
from adafruit_motor.servo import ContinuousServo
import os
import atexit
import threading
import pygame

# ===================== ピン設定 =====================
LEVER_PIN = 14
PUSH_BUTTON_PIN = 15  # ※現状未使用（残してOK）

STOP_BUTTON1 = 23
STOP_BUTTON2 = 24
STOP_BUTTON3 = 25

SENSOR_PIN1 = 26
SENSOR_PIN2 = 19
SENSOR_PIN3 = 13

PCA_CHANNEL  = 15  # 第1リール
PCA_CHANNEL2 = 8   # 第2リール
PCA_CHANNEL3 = 0   # 第3リール

LED_PIN = 18  # GPIO側（今は未使用でOK）

# ===== PCA9685 LED =====
LED_CHANNELS = [1, 7, 14]          # 3つとも常時点灯
LED_DUTY_ON = 0xFFFF               # 点灯（最大）
LED_DUTY_OFF = 0x0000              # 消灯
LED_FLASH_DURATION = 3.0           # フラッシュ時間（秒）
LED_FLASH_INTERVAL = 0.08          # 点滅間隔（短いほど速い）

# ★追加：ブラックアウト演出範囲
BLACKOUT_MIN = 0.15
BLACKOUT_MAX = 0.20

# ===================== 速度設定 =====================
CLOCKWISE_SPEED = -0.5
COUNTER_CLOCKWISE_SPEED = 0.8
FREEZE_SPEED = 0.08
STOP_SPEED = 0.3  # あなたの環境に合わせた静止点

# 後告知判定（random.random() は 0.0〜1.0）
AFTER_NOTICE_THRESHOLD = 0.25

# Freeze当選範囲
FREEZE_MIN = 0.25
FREEZE_MAX = 0.3

# ===================== FIFO設定 =====================
fifo_path = '/tmp/notify_pipe'

# ===================== GPIO初期化 =====================
GPIO.setmode(GPIO.BCM)
GPIO.setup(SENSOR_PIN1, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(SENSOR_PIN2, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(SENSOR_PIN3, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

GPIO.setup(STOP_BUTTON1, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(STOP_BUTTON2, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(STOP_BUTTON3, GPIO.IN, pull_up_down=GPIO.PUD_UP)

GPIO.setup(LEVER_PIN, GPIO.IN)
GPIO.setup(LED_PIN, GPIO.OUT)

# ===================== PCA9685初期化 =====================
i2c = busio.I2C(board.SCL, board.SDA)
pca = PCA9685(i2c)
pca.frequency = 50

continuous_servo  = ContinuousServo(pca.channels[PCA_CHANNEL],  min_pulse=700, max_pulse=2300)
continuous_servo2 = ContinuousServo(pca.channels[PCA_CHANNEL2], min_pulse=700, max_pulse=2300)
continuous_servo3 = ContinuousServo(pca.channels[PCA_CHANNEL3], min_pulse=700, max_pulse=2300)

# ===================== PCA LED制御 =====================
_led_lock = threading.Lock()
_led_stop_event = threading.Event()
_led_flash_thread = None

def leds_set(duty: int):
    with _led_lock:
        for ch in LED_CHANNELS:
            try:
                pca.channels[ch].duty_cycle = duty
            except Exception as e:
                print(f"[LED] duty_cycle 設定失敗 ch={ch}: {e}")

def leds_on():
    leds_set(LED_DUTY_ON)

def leds_off():
    leds_set(LED_DUTY_OFF)

def _flash_worker(duration: float, interval: float):
    end_t = time.time() + duration
    state = False
    while time.time() < end_t and not _led_stop_event.is_set():
        state = not state
        leds_set(LED_DUTY_ON if state else LED_DUTY_OFF)
        time.sleep(interval)
    if not _led_stop_event.is_set():
        leds_on()

def flash_leds(duration: float = LED_FLASH_DURATION, interval: float = LED_FLASH_INTERVAL):
    global _led_flash_thread
    if _led_flash_thread is not None and _led_flash_thread.is_alive():
        return
    _led_flash_thread = threading.Thread(target=_flash_worker, args=(duration, interval), daemon=True)
    _led_flash_thread.start()

# 起動時：常時点灯
leds_on()

# ===================== STOP受付（回転中のみ有効） =====================
spin_active = threading.Event()

def stop_accept_enable():
    spin_active.set()

def stop_accept_disable():
    spin_active.clear()

# 初期状態：STOP無効
stop_accept_disable()

# ===================== rn共有（停止ロジック参照用） =====================
rn_lock = threading.Lock()
spin_rn = 0.0
original_rn = 0.0

def set_spin_rn(v: float):
    global spin_rn
    with rn_lock:
        spin_rn = v

def get_spin_rn() -> float:
    with rn_lock:
        return spin_rn

def set_original_rn(v: float):
    global original_rn
    with rn_lock:
        original_rn = v

def get_original_rn() -> float:
    with rn_lock:
        return original_rn

# ===================== FIFO（STOPスレッドからも送る） =====================
fifo_lock = threading.Lock()
fifo_global = None

def set_fifo_global(f):
    global fifo_global
    with fifo_lock:
        fifo_global = f

def send_fifo_threadsafe(message: str):
    with fifo_lock:
        if fifo_global is None:
            return
        print(f"[通知] 送信: {message}")
        fifo_global.write(message + "\n")
        fifo_global.flush()

# ===================== 第一停止通知（ラウンド中1回だけ） =====================
first_stop_lock = threading.Lock()
first_stop_sent = False

def reset_first_stop():
    global first_stop_sent
    with first_stop_lock:
        first_stop_sent = False

def notify_first_stop_once():
    global first_stop_sent
    with first_stop_lock:
        if first_stop_sent:
            return False
        first_stop_sent = True
    send_fifo_threadsafe("first_stop")
    return True

# ===================== ユーティリティ（メインスレッド用） =====================
def send_fifo(fifo, message: str):
    print(f"[通知] 送信: {message}")
    fifo.write(message + "\n")
    fifo.flush()

def wait_all_reels_stop():
    while not (reel1.stopped.is_set() and reel2.stopped.is_set() and reel3.stopped.is_set()):
        time.sleep(0.005)

# ===================== STOP割り込みのON/OFF（フリーズ中は無効化） =====================
_interrupts_enabled = True
_interrupt_lock = threading.Lock()

def disable_stop_interrupts():
    global _interrupts_enabled
    with _interrupt_lock:
        if not _interrupts_enabled:
            return
        for pin in (STOP_BUTTON1, STOP_BUTTON2, STOP_BUTTON3):
            try:
                GPIO.remove_event_detect(pin)
            except Exception:
                pass
        _interrupts_enabled = False
        print("[FREEZE] STOP割り込み無効化（押下は完全に無視）")

def enable_stop_interrupts():
    global _interrupts_enabled
    with _interrupt_lock:
        if _interrupts_enabled:
            return
        setup_button_interrupts()
        _interrupts_enabled = True
        print("[FREEZE] STOP割り込み有効化")

# ===================== クリーンアップ =====================
def cleanup():
    print("--- クリーンアップ処理を開始 ---")

    # LED停止＆消灯
    try:
        _led_stop_event.set()
        leds_off()
    except Exception:
        pass

    try:
        continuous_servo.throttle = STOP_SPEED
        continuous_servo2.throttle = STOP_SPEED
        continuous_servo3.throttle = STOP_SPEED
        time.sleep(0.1)
    except Exception as e:
        print(f"スロットル設定エラー: {e}")

    try:
        for i in range(16):
            try:
                pca.channels[i].duty_cycle = 0
            except Exception:
                pass
        pca.deinit()
    except Exception as e:
        print(f"PCA deinit エラー: {e}")

    try:
        for pin in (STOP_BUTTON1, STOP_BUTTON2, STOP_BUTTON3):
            try:
                GPIO.remove_event_detect(pin)
            except Exception:
                pass
    except Exception:
        pass

    try:
        GPIO.cleanup()
    except Exception:
        pass

    try:
        if os.path.exists(fifo_path):
            os.remove(fifo_path)
            print("[通知] パイプを削除しました。")
    except Exception as e:
        print(f"パイプ削除エラー: {e}")

atexit.register(cleanup)

# ===================== 回転開始 =====================
def rotate(isFirst):
    # ★レバー前はSTOP無効
    stop_accept_disable()

    # レバーオン待ち
    while True:
        if GPIO.input(LEVER_PIN) == GPIO.LOW:
            break
        time.sleep(0.01)

    print("レバーオン")
    time.sleep(0.3)

    if isFirst:
        rn = random.random()

        # ★フリーズ当選なら「回転しない」で返す（静止状態から演出スタート）
        if FREEZE_MIN <= rn < FREEZE_MAX:
            continuous_servo.throttle = STOP_SPEED
            continuous_servo2.throttle = STOP_SPEED
            continuous_servo3.throttle = STOP_SPEED
            print("[FREEZE] 当選：回転開始せず静止のまま")
            return rn

        # ---- ここから通常の回転開始 ----
        if 0.1 <= rn < 0.15:
            continuous_servo.throttle = COUNTER_CLOCKWISE_SPEED
            time.sleep(0.5)
            continuous_servo2.throttle = COUNTER_CLOCKWISE_SPEED
            time.sleep(0.5)
            continuous_servo3.throttle = COUNTER_CLOCKWISE_SPEED
            print(f"サーボ：反時計回りに回転開始 (速度: {COUNTER_CLOCKWISE_SPEED})")

            # ★回転開始したのでSTOP有効
            stop_accept_enable()
        else:
            continuous_servo.throttle = COUNTER_CLOCKWISE_SPEED
            continuous_servo2.throttle = COUNTER_CLOCKWISE_SPEED
            continuous_servo3.throttle = COUNTER_CLOCKWISE_SPEED
            print(f"サーボ：反時計回りに回転開始 (速度: {COUNTER_CLOCKWISE_SPEED})")

            # ★回転開始したのでSTOP有効
            stop_accept_enable()

        return rn

    else:
        rn = get_original_rn()
        continuous_servo.throttle = COUNTER_CLOCKWISE_SPEED
        continuous_servo2.throttle = COUNTER_CLOCKWISE_SPEED
        continuous_servo3.throttle = COUNTER_CLOCKWISE_SPEED
        print(f"サーボ：反時計回りに回転開始 (速度: {COUNTER_CLOCKWISE_SPEED})")

        # ★回転開始したのでSTOP有効
        stop_accept_enable()

        return rn

# ===================== STOP処理（リール別・並行） =====================
class ReelStopper:
    def __init__(self, name, button_pin, sensor_pin, servo):
        self.name = name
        self.button_pin = button_pin
        self.sensor_pin = sensor_pin
        self.servo = servo
        self.stop_requested = threading.Event()
        self.stopped = threading.Event()

    def reset_for_new_round(self):
        self.stop_requested.clear()
        self.stopped.clear()

    def request_stop(self):
        if not self.stopped.is_set():
            self.stop_requested.set()

    def run(self):
        while True:
            self.stop_requested.wait()
            self.stop_requested.clear()

            if self.stopped.is_set():
                continue

            rn = get_spin_rn()
            print(f"[{self.name}] STOP ON (spin_rn={rn})")

            if rn > 0.5:
                print(f"[{self.name}] はずれ。滑って停止。")
                while True:
                    if GPIO.input(self.sensor_pin) == 1:
                        print(f"[{self.name}] センサー反応")
                        time.sleep(0.2)
                        break
                    time.sleep(0.001)
            else:
                print(f"[{self.name}] あたり。7まで滑る。")
                while True:
                    if GPIO.input(self.sensor_pin) == 1:
                        print(f"[{self.name}] センサー反応")
                        break
                    time.sleep(0.001)

            self.servo.throttle = STOP_SPEED
            self.stopped.set()

            notify_first_stop_once()

            stop_se.play()
            print(f"[{self.name}] モーター停止")

reel1 = ReelStopper("REEL1", STOP_BUTTON1, SENSOR_PIN1, continuous_servo)
reel2 = ReelStopper("REEL2", STOP_BUTTON2, SENSOR_PIN2, continuous_servo2)
reel3 = ReelStopper("REEL3", STOP_BUTTON3, SENSOR_PIN3, continuous_servo3)

threading.Thread(target=reel1.run, daemon=True).start()
threading.Thread(target=reel2.run, daemon=True).start()
threading.Thread(target=reel3.run, daemon=True).start()

def _btn_callback_factory(reel: ReelStopper):
    def _cb(channel):
        # ★回転中以外はSTOP押下を無効化
        if not spin_active.is_set():
            return
        reel.request_stop()
    return _cb

def setup_button_interrupts():
    for pin in (STOP_BUTTON1, STOP_BUTTON2, STOP_BUTTON3):
        try:
            GPIO.remove_event_detect(pin)
        except Exception:
            pass

    GPIO.add_event_detect(STOP_BUTTON1, GPIO.FALLING, callback=_btn_callback_factory(reel1), bouncetime=80)
    GPIO.add_event_detect(STOP_BUTTON2, GPIO.FALLING, callback=_btn_callback_factory(reel2), bouncetime=80)
    GPIO.add_event_detect(STOP_BUTTON3, GPIO.FALLING, callback=_btn_callback_factory(reel3), bouncetime=80)

setup_button_interrupts()

# ===================== 結果通知（後告知対応） =====================
def lose(fifo, rn):
    send_fifo(fifo, "lose")

def win(fifo, rn):
    if rn < AFTER_NOTICE_THRESHOLD:
        print("後告知")

        send_fifo(fifo, "lose")
        time.sleep(0.5)

        reset_first_stop()
        reel1.reset_for_new_round()
        reel2.reset_for_new_round()
        reel3.reset_for_new_round()

        set_spin_rn(0.1)  # 当たり扱い

        rotate(False)
        wait_all_reels_stop()

        # ★停止したのでSTOP無効
        stop_accept_disable()

        continuous_servo.throttle = STOP_SPEED
        continuous_servo2.throttle = STOP_SPEED
        continuous_servo3.throttle = STOP_SPEED
        print("サーボの回転停止（後告知2回目）")

        # 7揃い確定（bonus送信）→LEDフラッシュ
        flash_leds()
        send_fifo(fifo, "bonus")
        time.sleep(10)
    else:
        print("即告知")
        flash_leds()
        send_fifo(fifo, "bonus")
        time.sleep(10)

# ===================== メインループ =====================
def loop(fifo):
    while True:
        time.sleep(0.5)

        reset_first_stop()
        reel1.reset_for_new_round()
        reel2.reset_for_new_round()
        reel3.reset_for_new_round()

        rn = rotate(True)
        set_original_rn(rn)

        # ★追加：このラウンドのブラックアウト判定
        blackout_active = (BLACKOUT_MIN <= rn < BLACKOUT_MAX)
        if blackout_active:
            print("[LED] BLACKOUT 開始（0.15<=rn<0.20）：リール停止まで消灯")
            leds_off()

        # 通常の停止ロジック（フリーズ時は後で上書きする）
        if rn < AFTER_NOTICE_THRESHOLD:
            set_spin_rn(0.9)   # 1回目はハズレ停止
        else:
            set_spin_rn(rn)

        print(f"[通知] 送信: {rn}")
        fifo.write(str(rn) + "\n")
        fifo.flush()

        # ===================== FREEZE演出（静止から開始） =====================
        if FREEZE_MIN <= rn < FREEZE_MAX:
            print("[FREEZE] 演出開始（静止状態から）")

            disable_stop_interrupts()

            reel1.stop_requested.clear()
            reel2.stop_requested.clear()
            reel3.stop_requested.clear()

            continuous_servo.throttle = STOP_SPEED
            continuous_servo2.throttle = STOP_SPEED
            continuous_servo3.throttle = STOP_SPEED
            time.sleep(2)

            continuous_servo.throttle = FREEZE_SPEED
            continuous_servo2.throttle = FREEZE_SPEED
            continuous_servo3.throttle = FREEZE_SPEED
            print(f"[FREEZE] FREEZE状態 (速度: {FREEZE_SPEED})")

            time.sleep(8)

            continuous_servo.throttle = STOP_SPEED
            continuous_servo2.throttle = STOP_SPEED
            continuous_servo3.throttle = STOP_SPEED
            print("[FREEZE] 再開前STOP (1秒)")
            time.sleep(1)

            continuous_servo.throttle = COUNTER_CLOCKWISE_SPEED
            continuous_servo2.throttle = COUNTER_CLOCKWISE_SPEED
            continuous_servo3.throttle = COUNTER_CLOCKWISE_SPEED
            print(f"[FREEZE] 回転再開 (速度: {COUNTER_CLOCKWISE_SPEED})")

            # ★回転再開したのでSTOP有効
            stop_accept_enable()

            set_spin_rn(0.1)
            enable_stop_interrupts()

            print("[FREEZE] STOP受付開始：ボタンで7停止してください")
        # ===============================================================

        wait_all_reels_stop()

        # ★停止したのでSTOP無効
        stop_accept_disable()

        # ★追加：ブラックアウト復帰（リール停止後に点灯へ）
        if blackout_active:
            print("[LED] BLACKOUT 終了：リール停止 → 点灯復帰")
            leds_on()

        continuous_servo.throttle = STOP_SPEED
        continuous_servo2.throttle = STOP_SPEED
        continuous_servo3.throttle = STOP_SPEED
        print("サーボの回転停止（1回目）")

        if rn > 0.5:
            lose(fifo, rn)
        else:
            win(fifo, rn)

        print("1 loop comp")

# ===================== FIFO作成〜開始 =====================
if os.path.exists(fifo_path):
    os.remove(fifo_path)
os.mkfifo(fifo_path)

# ===================== SE初期化 =====================
pygame.mixer.pre_init(44100, -16, 2, 512)
pygame.init()
pygame.mixer.init()
stop_se = pygame.mixer.Sound("stop_se.wav")

try:
    with open(fifo_path, 'w') as fifo:
        set_fifo_global(fifo)
        send_fifo(fifo, "start")
        time.sleep(3)
        loop(fifo)
except Exception as e:
    print(f"エラーが発生しました: {e}")
