import RPi.GPIO as GPIO
import time

# 使用するGPIOピン番号（BCMモード）
LEVER_PIN = 14
LED_PIN = 18

STOP_BUTTON1 = 23
STOP_BUTTON2 = 24
STOP_BUTTON3 = 25

SENSOR_PIN1 = 26
SENSOR_PIN2 = 19
SENSOR_PIN3 = 13

def main():
    # GPIOの初期化
    GPIO.setmode(GPIO.BCM)
    
    # 外部でプルアップ抵抗（3.3V）を接続しているため、
    # ラズパイ側は通常の入力（プルアップなし）として設定します。
    GPIO.setup(SENSOR_PIN, GPIO.IN)
    GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(LED_PIN, GPIO.OUT)
    GPIO.setup(STOP_BUTTON1, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(STOP_BUTTON2, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(STOP_BUTTON3, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    print(f"--- センサーテスト開始 (GPIO {SENSOR_PIN}) ---")
    print("センサーの間に物を置いたり離したりしてください。")
    print("終了するには Ctrl+C を押してください。")

    try:
        # 直前の状態を保持するための変数
        last_state = None
        last_state2 = None
        last_state3 = None
        last_state4 = None
        last_state5 = None

        while True:
            # センサーの状態を読み取る
            # オープンコレクタ動作：
            #  - 物がない（入光）: トランジスタON -> 0V (LOW)
            #  - 物がある（遮光）: トランジスタOFF -> 3.3V (HIGH)
            current_state = GPIO.input(SENSOR_PIN)

            # 状態に変化があった時だけ表示する
            if current_state != last_state:
                if current_state == GPIO.HIGH:
                    print("【レバー遮光中】 物を検知しました (HIGH)")
                else:
                    print("【レバー入光中】 何もありません (LOW)")
                
                last_state = current_state

            current_state2 = GPIO.input(BUTTON_PIN)

            # 状態に変化があった時だけ表示する
            if current_state2 != last_state2:
                if current_state2 == GPIO.HIGH:
                    print("【PUSHボタン遮光中】 物を検知しました (HIGH)")
                    GPIO.output(LED_PIN, GPIO.LOW)
                else:
                    print("【PUSHボタン入光中】 何もありません (LOW)")
                    GPIO.output(LED_PIN, GPIO.HIGH)
                
                last_state2 = current_state2
            
            current_state3 = GPIO.input(STOP_BUTTON1)

            # 状態に変化があった時だけ表示する
            if current_state3 != last_state3:
                if current_state3 == GPIO.HIGH:
                    print("【ボタン1遮光中】 物を検知しました (HIGH)")
                else:
                    print("【ボタン1入光中】 何もありません (LOW)")
                
                last_state3 = current_state3

            current_state4 = GPIO.input(STOP_BUTTON2)

            # 状態に変化があった時だけ表示する
            if current_state4 != last_state4:
                if current_state4 == GPIO.HIGH:
                    print("【ボタン2遮光中】 物を検知しました (HIGH)")
                else:
                    print("【ボタン2入光中】 何もありません (LOW)")
                
                last_state4 = current_state4

            current_state5 = GPIO.input(STOP_BUTTON3)

            # 状態に変化があった時だけ表示する
            if current_state5 != last_state5:
                if current_state5 == GPIO.HIGH:
                    print("【ボタン3遮光中】 物を検知しました (HIGH)")
                else:
                    print("【ボタン3入光中】 何もありません (LOW)")
                
                last_state5 = current_state5
            
            # CPU負荷を下げるための短い待機
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nテストを終了します。")

    finally:
        # GPIO設定をリセット
        GPIO.cleanup()

if __name__ == "__main__":
    main()