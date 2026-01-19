import cv2
import pygame
import random
import sys
import os
from datetime import datetime

import threading
import queue
import time

# ===== Raspberry Pi GPIO =====
GPIO_AVAILABLE = False
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except Exception as e:
    print(f"[GPIO] RPi.GPIO が使えません（Raspberry Pi以外等）: {e}")
    GPIO_AVAILABLE = False

# ===================== メッセージ受信 =====================
msg_queue = queue.Queue()

# "bonus" はイベントで扱う（freeze保持解除・通常の当たり待ち両対応）
bonus_event = threading.Event()

def receiver_thread(fifo_path):
    """裏でひたすら受信してQueueに入れる係（bonusはイベントだけにする）"""
    with open(fifo_path, 'r') as fifo:
        for line in fifo:
            msg = line.strip()
            if msg == "bonus":
                bonus_event.set()
                continue  # ★bonusはQueueに入れない（取りこぼし/食い合い防止）
            msg_queue.put(msg)

def is_float(s):
    try:
        float(s)
        return True
    except ValueError:
        return False

# ===================== 設定 =====================
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 400

IMG_BLACK_PATH = "lamp_black.png"
IMG_LIGHT_PATH = "lamp_light.png"

VIDEO_PATH = "bigbonus_fix2.mp4"
AUDIO_PATH = "big_sound.mp3"

SE_WIN_PATH = "win_se.wav"
SE_POKYUN_PATH = "win_pokyun.wav"
SE_START_PATH = "start_se.wav"
SE_STOP_PATH = "stop_se.wav"

# Freeze演出
FREEZE_VIDEO_PATH = "freeze_movie.mp4"
FREEZE_SE_PATH = "freeze_se.wav"
FREEZE_BGM_PATH = "freeze_bgm.wav"

# 新演出（ボタン演出）
BUTTON_VIDEO_PATH = "button.mp4"
GPIO_PIN_BUTTON = 15  # BCM 15（ご指定）

LED_PIN = 18          # ★追加：BCM 18（PUSHボタンLED）

STATE_IDLE = 0
STATE_WIN = 1

# ===================== Pygame初期化 =====================
pygame.init()
try:
    pygame.mixer.init()
except pygame.error as e:
    print(f"mixer initエラー: {e}")

# ===================== GPIO初期化 =====================
def gpio_init():
    if not GPIO_AVAILABLE:
        return
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    # 事前プルアップ前提でも、念のためPUD_UP指定（問題になりにくい）
    GPIO.setup(GPIO_PIN_BUTTON, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    print(f"[GPIO] BCM{GPIO_PIN_BUTTON} を入力(PUD_UP)で初期化")

    # ★追加：LEDピンを出力にして初期消灯
    GPIO.setup(LED_PIN, GPIO.OUT, initial=GPIO.LOW)
    print(f"[GPIO] BCM{LED_PIN} を出力で初期化（LED消灯）")

def gpio_cleanup():
    if GPIO_AVAILABLE:
        # ★追加：終了時に必ず消灯
        try:
            GPIO.output(LED_PIN, GPIO.LOW)
        except Exception:
            pass
        GPIO.cleanup()

# ===================== FIFO =====================
fifo_path = '/tmp/notify_pipe'
print("[FIFO] メイン基盤待機中...")
while not os.path.exists(fifo_path):
    pass
print("[FIFO] メイン基盤接続完了")

# ===================== 効果音ロード =====================
se_win = None
se_start = None
se_stop = None
se_pokyun = None
se_freeze = None

try:
    se_win = pygame.mixer.Sound(SE_WIN_PATH)
    se_start = pygame.mixer.Sound(SE_START_PATH)
    se_stop = pygame.mixer.Sound(SE_STOP_PATH)
    se_pokyun = pygame.mixer.Sound(SE_POKYUN_PATH)
    se_freeze = pygame.mixer.Sound(FREEZE_SE_PATH)
except (FileNotFoundError, pygame.error) as e:
    print(f"効果音エラー: {e}")

# ===================== ムービー再生 =====================
def play_movie(screen, clock):
    try:
        pygame.mixer.music.load(AUDIO_PATH)
    except pygame.error:
        print("動画用音声が見つかりません")

    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        print("動画が開けません:", VIDEO_PATH)
        return

    video_fps = cap.get(cv2.CAP_PROP_FPS)
    if not video_fps or video_fps <= 1:
        video_fps = 30

    pygame.mixer.music.play()
    playing = True

    while playing:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                cap.release()
                pygame.quit()
                gpio_cleanup()
                sys.exit()

        ret, frame = cap.read()
        if ret:
            frame = cv2.resize(frame, (SCREEN_WIDTH, SCREEN_HEIGHT))
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            surf = pygame.image.frombuffer(frame.tobytes(), (SCREEN_WIDTH, SCREEN_HEIGHT), 'RGB')
            screen.blit(surf, (0, 0))
            pygame.display.update()
            clock.tick(video_fps)
        else:
            playing = False

    pygame.mixer.music.stop()
    cap.release()
    screen.fill((0, 0, 0))
    pygame.display.update()

def freeze_movie(screen, clock):
    """
    freeze_movie.mp4 を再生。
    - 再生開始と同時に freeze_se.wav
    - 再生3秒後に freeze_bgm.wav（pygame.mixer.music）を再生（ループ）
    - 再生終了後、最終フレームで保持し、bonus_event が立つまで待つ
    - bonus_event が立ったらBGM停止して復帰
    """
    cap = cv2.VideoCapture(FREEZE_VIDEO_PATH)
    if not cap.isOpened():
        print("freeze動画が開けません:", FREEZE_VIDEO_PATH)
        return

    video_fps = cap.get(cv2.CAP_PROP_FPS)
    if not video_fps or video_fps <= 1:
        video_fps = 30

    # 再生開始と同時にSE
    if se_freeze:
        se_freeze.play()

    # 3秒後にBGM
    bgm_started = False
    start_time = time.time()
    try:
        pygame.mixer.music.load(FREEZE_BGM_PATH)
    except pygame.error as e:
        print(f"freeze BGMロード失敗: {e}")
        bgm_started = True  # 再生不能なら試行しない

    last_surface = None
    playing = True

    while playing:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                cap.release()
                pygame.quit()
                gpio_cleanup()
                sys.exit()

        if (not bgm_started) and (time.time() - start_time >= 3.0):
            try:
                pygame.mixer.music.play()  # ループせずに
            except pygame.error as e:
                print(f"freeze BGM再生失敗: {e}")
            bgm_started = True

        ret, frame = cap.read()
        if ret:
            frame = cv2.resize(frame, (SCREEN_WIDTH, SCREEN_HEIGHT))
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            last_surface = pygame.image.frombuffer(frame.tobytes(), (SCREEN_WIDTH, SCREEN_HEIGHT), 'RGB')
            screen.blit(last_surface, (0, 0))
            pygame.display.update()
            clock.tick(video_fps)
        else:
            playing = False

    cap.release()

    # 最終フレームで保持（bonusが来るまで）
    if last_surface is not None:
        screen.blit(last_surface, (0, 0))
        pygame.display.update()

    print("[FREEZE] 最終フレーム保持：bonus待ち...")
    while not bonus_event.is_set():
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                gpio_cleanup()
                sys.exit()
        time.sleep(0.01)

    pygame.mixer.music.stop()
    print("[FREEZE] bonus受信：freeze_movie終了")
    return

def button_loop_movie_until_gpio_high(screen, clock):
    """
    button.mp4 をループ再生し続け、GPIO15がHIGHになったら終了する。
    - 再生中はLED_PIN(BCM18)を点灯
    - 終了時にLEDを消灯
    """
    # ★追加：演出開始でLED点灯
    if GPIO_AVAILABLE:
        try:
            GPIO.output(LED_PIN, GPIO.HIGH)
            print("[LED] ON (BCM18 HIGH)")
        except Exception as e:
            print(f"[LED] ON失敗: {e}")

    cap = cv2.VideoCapture(BUTTON_VIDEO_PATH)
    if not cap.isOpened():
        print("button動画が開けません:", BUTTON_VIDEO_PATH)
        # ★失敗時も消灯
        if GPIO_AVAILABLE:
            try:
                GPIO.output(LED_PIN, GPIO.LOW)
                print("[LED] OFF (BCM18 LOW)")
            except Exception:
                pass
        return False

    try:
        video_fps = cap.get(cv2.CAP_PROP_FPS)
        if not video_fps or video_fps <= 1:
            video_fps = 30

        # 起動直後からHIGHだと即終了しちゃうので、最初の状態を見て「LOW→HIGH」を優先
        initial_high = False
        if GPIO_AVAILABLE:
            try:
                initial_high = (GPIO.input(GPIO_PIN_BUTTON) == GPIO.HIGH)
            except Exception as e:
                print(f"[GPIO] 読み取り失敗: {e}")
                initial_high = False

        print(f"[BUTTON] ループ再生開始（initial_high={initial_high}）")

        confirmed = False
        waiting_for_rise = initial_high  # 初期がHIGHなら、一度LOWになるまで上昇扱いしない

        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    cap.release()
                    pygame.quit()
                    gpio_cleanup()
                    sys.exit()

            # GPIOチェック
            if GPIO_AVAILABLE:
                try:
                    val = GPIO.input(GPIO_PIN_BUTTON)
                    if waiting_for_rise:
                        # 初期HIGHだった場合は、いったんLOWになるのを待つ
                        if val == GPIO.LOW:
                            waiting_for_rise = False
                    else:
                        # LOW→HIGH を検出したら確定
                        if val == GPIO.HIGH:
                            confirmed = True
                            break
                except Exception as e:
                    print(f"[GPIO] 読み取り失敗: {e}")

            ret, frame = cap.read()
            if not ret:
                # ループ：先頭へ
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

            frame = cv2.resize(frame, (SCREEN_WIDTH, SCREEN_HEIGHT))
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            surf = pygame.image.frombuffer(frame.tobytes(), (SCREEN_WIDTH, SCREEN_HEIGHT), 'RGB')
            screen.blit(surf, (0, 0))
            pygame.display.update()
            clock.tick(video_fps)

        screen.fill((0, 0, 0))
        pygame.display.update()

        if confirmed:
            print("[BUTTON] GPIO HIGH 検出：確定")
        else:
            print("[BUTTON] 終了（未確定）")

        return confirmed

    finally:
        # ★追加：演出終了でLED消灯（確定/未確定どちらでも）
        if GPIO_AVAILABLE:
            try:
                GPIO.output(LED_PIN, GPIO.LOW)
                print("[LED] OFF (BCM18 LOW)")
            except Exception as e:
                print(f"[LED] OFF失敗: {e}")
        cap.release()

# ===================== FIFO待ちユーティリティ =====================
def wait_first_stop():
    while True:
        if not msg_queue.empty():
            try:
                message = msg_queue.get_nowait()
                if message == "first_stop":
                    print("[FIFO] 受信: 第一停止")
                    return
            except queue.Empty:
                pass

def wait_lose():
    while True:
        if not msg_queue.empty():
            try:
                message = msg_queue.get_nowait()
                if message == "lose":
                    print("[FIFO] 受信: ハズレ目停止")
                    return
            except queue.Empty:
                pass

# ===================== 当たり演出 =====================
def winnnig(rn, screen, clock):
    """
    当たり演出。
    戻り値:
      True  -> 当たり確定（STATE_WINへ遷移してOK）
      False -> まだ確定してない
    """
    print("Num: " + str(rn))

    # ★freeze演出（0.25〜0.30）
    if 0.25 <= rn < 0.30:
        print("FREEZE演出")
        freeze_movie(screen, clock)

        # freeze_movie が bonus_event まで待って戻るので、ここでは待たない
        if se_win:
            se_win.play()
        return True

    # ★新演出（0.30〜0.35）
    if 0.30 <= rn < 0.35:
        print("BUTTON演出（button.mp4 ループ → GPIO15 HIGH待ち）")
        ok = button_loop_movie_until_gpio_high(screen, clock)
        if ok:
            if se_win:
                se_win.play()
            return True
        else:
            # 通常はここに来ない（QUIT等で抜けた場合）
            return False

    # --- 既存の当たり分岐（範囲を整理）---
    if rn < 0.15:
        wait_first_stop()
        if se_win:
            se_win.play()
        return True

    elif rn < 0.25:
        print("後告知")
        wait_lose()
        if se_win:
            se_win.play()
        return True

    elif rn < 0.50:
        # 0.35〜0.50 は従来の即告知系としてまとめ（必要なら細分化してOK）
        print("即告知/通常当たり")
        if se_win:
            se_win.play()
        return True

    return False

def winnnig_after(rn):
    # bonus_event は receiver_thread が立てる
    print("[FIFO] bonus待機（7停止）...")
    bonus_event.wait()
    print("[FIFO] bonus受信（7停止）")
    bonus_event.clear()  # 次ラウンド用にクリア

# ===================== メイン =====================
def main():
    gpio_init()

    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.NOFRAME)
    pygame.display.set_caption("Bonus Lottery Machine")
    clock = pygame.time.Clock()

    t = threading.Thread(target=receiver_thread, args=(fifo_path,), daemon=True)
    t.start()

    try:
        img_black = pygame.image.load(IMG_BLACK_PATH)
        img_light = pygame.image.load(IMG_LIGHT_PATH)
    except FileNotFoundError:
        print("画像ファイルが見つかりません")
        return

    rect_black = img_black.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2))
    rect_light = img_light.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2))

    current_state = STATE_IDLE

    # start待ち
    while True:
        if not msg_queue.empty():
            try:
                message = msg_queue.get_nowait()
                if message == "start":
                    print("[FIFO] 受信: メイン基盤起動")
                    break
            except queue.Empty:
                pass

    rn = 1.0
    running = True
    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

            if current_state == STATE_IDLE:
                if not msg_queue.empty():
                    try:
                        message = msg_queue.get_nowait()
                        print(f"[FIFO] 受信: {message}")

                        if is_float(message):
                            rn = float(message)

                            if rn >= 0.1:
                                if se_start:
                                    se_start.play()
                                time.sleep(0.3)

                            if rn < 0.05:
                                if se_pokyun:
                                    se_pokyun.play()
                                print("先バレ告知")
                                time.sleep(0.3)

                            if rn < 0.5:
                                confirmed = winnnig(rn, screen, clock)
                                if confirmed:
                                    print("当たり！")
                                    current_state = STATE_WIN
                                else:
                                    print("当たり未確定（想定外）")
                            else:
                                print("ハズレ...")

                    except queue.Empty:
                        pass

            elif current_state == STATE_WIN:
                winnnig_after(rn)
                play_movie(screen, clock)
                current_state = STATE_IDLE

            # 描画（新演出中は動画描画してるので、ここは上書きされる）
            screen.fill((0, 0, 0))
            if current_state == STATE_IDLE:
                screen.blit(img_black, rect_black)
            else:
                screen.blit(img_light, rect_light)

            pygame.display.update()
            clock.tick(60)

    finally:
        pygame.quit()
        gpio_cleanup()

if __name__ == "__main__":
    main()
