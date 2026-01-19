import RPi.GPIO as GPIO
import time
import random
import board
import busio
from adafruit_pca9685 import PCA9685
# 連続回転サーボ用のクラスをインポート
from adafruit_motor.servo import ContinuousServo
import os
import atexit

LEVER_PIN = 15

STOP_BUTTON1 = 23 #
STOP_BUTTON2 = 24 #
STOP_BUTTON3 = 25 #

SENSOR_PIN1 = 26 #
SENSOR_PIN2 = 19 #
SENSOR_PIN3 = 13 #

PCA_CHANNEL = 15  # 第1リール
PCA_CHANNEL2 = 8  # 第2リール
PCA_CHANNEL3 = 0 # 第3リール

LED_PIN = 18

GPIO.setmode(GPIO.BCM)
GPIO.setup(SENSOR_PIN1, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(SENSOR_PIN2, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(SENSOR_PIN3, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(STOP_BUTTON1, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(STOP_BUTTON2, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(STOP_BUTTON3, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(LEVER_PIN, GPIO.IN)
GPIO.setup(LED_PIN, GPIO.OUT)


# --- PCA9685の初期化 ---
# 1. I2Cバスの初期化
i2c = busio.I2C(board.SCL, board.SDA)

# 2. PCA9685ドライバの初期化（デフォルトのアドレス 0x40 を使用）
# I2Cアドレスが異なる場合は、i2c_address=0xXX を指定してください
pca = PCA9685(i2c)
pca.frequency = 50  # サーボモーターの標準周波数 50 Hz に設定

# --- 変更点：連続回転サーボ (FS90R) の初期化 ---
# ContinuousServo を使用し、パルス幅の仕様 (700μs ～ 2300μs) を指定
# 静止点パルス幅 1500μs は自動的に中央 (スロットル 0.0) に割り当てられます
continuous_servo = ContinuousServo(
    pca.channels[PCA_CHANNEL], 
    min_pulse=700, 
    max_pulse=2300
)

continuous_servo2 = ContinuousServo(
    pca.channels[PCA_CHANNEL2], 
    min_pulse=700, 
    max_pulse=2300
)

continuous_servo3 = ContinuousServo(
    pca.channels[PCA_CHANNEL3], 
    min_pulse=700, 
    max_pulse=2300
)

# 制御値の定義
# スロットル: -1.0 (最大時計回り速度) ～ 1.0 (最大反時計回り速度)
# パルス幅が静止点以上 (1500μs超) -> 反時計回り (正の値)
# パルス幅が静止点以下 (1500μs未満) -> 時計回り (負の値)
#
# ここでは、全速力の 50% で回転させることを想定します
CLOCKWISE_SPEED = -0.5       # 時計回り (パルス幅が短くなる)
COUNTER_CLOCKWISE_SPEED = 0.8 # 反時計回り (パルス幅が長くなる)
STOP_SPEED = 0.3             # 静止 (1500μs)

def cleanup():
    try:
        if 'continuous_servo' in globals():
            continuous_servo.throttle = 0.3
            continuous_servo2.throttle = 0.3
            continuous_servo3.throttle = 0.3
            time.sleep(0.1) # 信号が安定するのを待つ
            print("スロットルを0.0に設定しました。")
    except Exception as e:
        print(f"スロットル設定エラー: {e}")
        
    # 2. PCA9685をリセットし、出力を完全に無効化
    try:
        if 'pca' in globals():
            # pca.deinit() を呼び出す前に、全てをオフにするコマンドを直接送る
            # 全チャンネルの出力を強制的に Low (オフ) にする
            for i in range(16):
                pca.channels[i].duty_cycle = 0 # 0 に設定
            
            pca.deinit() 
            print("PCA9685の deinit が完了しました。")
    except Exception as e:
        print(f"PCA deinit エラー: {e}")

    GPIO.cleanup()

    if os.path.exists(fifo_path):
        os.remove(fifo_path)
        print("[通知] パイプを削除しました。")

    print("--- クリーンアップ処理を開始 ---")

def lose(rn):
  message = "lose"
  print(f"[通知] 送信: {message}")
  fifo.write(message + '\n')
  fifo.flush()
  return

def win(rn):
  if rn < 0.25:
    print("後告知")
    message = "lose"
    print(f"[通知] 送信: {message}")
    fifo.write(message + '\n')
    fifo.flush()

    time.sleep(0.5)
    rotate()

    while True:
        if(GPIO.input(button_pin) == 0):
            print("button on")
            print("あたり。7まで滑る。")
            while True:
                if(GPIO.input(sensor_pin) == 1):
                    print("センサー反応")
                    break
                time.sleep(0.001)
            break

        time.sleep(0.001)
    
    continuous_servo.throttle = STOP_SPEED 
    continuous_servo2.throttle = STOP_SPEED 
    continuous_servo3.throttle = STOP_SPEED 
    print("サーボの回転停止 (静止点: 1500μs)")

    message = "bonus"
    print(f"[通知] 送信: {message}")
    fifo.write(message + '\n')
    fifo.flush()
    time.sleep(10)
  
  else:
      print("即告知")
      message = "bonus"
      print(f"[通知] 送信: {message}")
      fifo.write(message + '\n')
      fifo.flush()
      time.sleep(10)

  return

def rotate():
    #レバーオンの処理
    while True:
        if(GPIO.input(LEVER_PIN) == GPIO.LOW):
            break
        time.sleep(0.01)

    print("レバーオン")

    continuous_servo.throttle = COUNTER_CLOCKWISE_SPEED
    continuous_servo2.throttle = COUNTER_CLOCKWISE_SPEED
    continuous_servo3.throttle = COUNTER_CLOCKWISE_SPEED
    print(f"サーボ：反時計回りに回転開始 (速度: {COUNTER_CLOCKWISE_SPEED})")
    return

    

def loop():
    time.sleep(0.5)


    rotate()
    rn = random.random()

    message = rn
    print(f"[通知] 送信: {message}")
    fifo.write(str(message) + '\n')
    fifo.flush()

    while True:
        if(GPIO.input(STOP_BUTTON1) == 0):
            print("1st STOP ON")

            if(rn > 0.5):
                print("はずれ。滑って停止。")
                while True:
                    if(GPIO.input(SENSOR_PIN1) == 1):
                        print("センサー反応")
                        time.sleep(0.2)
                        break
                    time.sleep(0.001)
                break
            else:
                print("あたり。7まで滑る。")
                while True:
                    if(GPIO.input(SENSOR_PIN1) == 1):
                        print("センサー反応")
                        break
                    time.sleep(0.001)
                break

        time.sleep(0.001)
    
    continuous_servo.throttle = STOP_SPEED 
    continuous_servo2.throttle = STOP_SPEED 
    continuous_servo3.throttle = STOP_SPEED 
    print("サーボの回転停止 (静止点: 1500μs)")

    if(rn > 0.5):
        lose(rn)
    else:
        win(rn)
    
    time.sleep(0.5)

    print("1 loop comp")
    loop()


atexit.register(cleanup)
fifo_path = '/tmp/notify_pipe'

# すでに存在するなら削除して作り直す
if os.path.exists(fifo_path):
    os.remove(fifo_path)

# 指定したパスに「名前付きパイプ（FIFO）」を作成する
os.mkfifo(fifo_path)

try:
    with open(fifo_path, 'w') as fifo:
        message = "start"
        print(f"[通知] 送信: {message}")
        fifo.write(message + '\n')
        fifo.flush()
        time.sleep(3)
        loop() # 処理を開始
except Exception as e:
    print(f"エラーが発生しました: {e}")

    