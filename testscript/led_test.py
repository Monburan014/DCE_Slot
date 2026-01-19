from adafruit_pca9685 import PCA9685
import time
import board
import busio

# 設定周波数（Hz）
SET_FREQ = 50

# LED接続ポート
LED_1 = 1
LED_2 = 7
LED_2 = 14

# 点滅間隔（秒）
WINKER_INTERVAL = 1.0

# 半分の明るさ（16bit PWM）
HALF_BRIGHT = 0xEFFF  # 約50%

i2c = busio.I2C(board.SCL, board.SDA)

# PCA9685 初期化
pca = PCA9685(i2c)
pca.frequency = SET_FREQ

try:
    while True:
        # ON（半分の明るさ）
        pca.channels[LED_1].duty_cycle = HALF_BRIGHT
        pca.channels[LED_2].duty_cycle = HALF_BRIGHT
        pca.channels[LED_3].duty_cycle = HALF_BRIGHT
        time.sleep(WINKER_INTERVAL)

        # OFF
        pca.channels[LED_1].duty_cycle = 0x0000
        pca.channels[LED_2].duty_cycle = 0x0000
        pca.channels[LED_3].duty_cycle = 0x0000
        time.sleep(WINKER_INTERVAL)

except KeyboardInterrupt:
    pca.channels[LED_1].duty_cycle = 0x0000
    pca.channels[LED_2].duty_cycle = 0x0000
    pca.channels[LED_3].duty_cycle = 0x0000
    pca.deinit()
    print("KeyboardInterrupt")
