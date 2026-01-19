import os
import time
from datetime import datetime
import atexit
import random

def cleanup():
  if os.path.exists(fifo_path):
    os.remove(fifo_path)
    print("[通知] パイプを削除しました。")

def win(rn):
  if rn < 0.25:
      print("後告知")
      message = "lose"
      print(f"[通知] 送信: {message}")
      fifo.write(message + '\n')
      fifo.flush()
      time.sleep(3)

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

def lose(rn):
  print("ハズレ")
  message = "lose"
  print(f"[通知] 送信: {message}")
  fifo.write(message + '\n')
  fifo.flush()
  return

atexit.register(cleanup)

fifo_path = '/tmp/notify_pipe'

# すでに存在するなら削除して作り直す
if os.path.exists(fifo_path):
    os.remove(fifo_path)

# 指定したパスに「名前付きパイプ（FIFO）」を作成する
os.mkfifo(fifo_path)

with open(fifo_path, 'w') as fifo:
    message = "start"
    print(f"[通知] 送信: {message}")
    fifo.write(message + '\n')
    fifo.flush()
    time.sleep(3)

    while True:
        rn = random.random()
        message = rn
        print(f"[通知] 送信: {message}")
        fifo.write(str(message) + '\n')
        fifo.flush()
        time.sleep(3)

        if rn < 0.5:
          win(rn)
        else:
          lose(rn)

        time.sleep(3)




