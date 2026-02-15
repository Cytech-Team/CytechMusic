import multiprocessing
import os
import sys
import time
from dotenv import load_dotenv

def run_bot(token, is_deprecated=False):
    """ฟังก์ชันสำหรับรันบอทแต่ละตัวโดยรับ Token และสถานะโดยตรง"""
    # ตั้งค่า Environment สำหรับ Process นี้
    mode_text = "MIGRATION MODE" if is_deprecated else "MAIN BOT"
    dep_val = "true" if is_deprecated else "false"
    
    os.environ["BOT_TOKEN"] = token
    os.environ["DEPRECATED_MODE"] = dep_val
    
    # Debug print to verify environment within the process
    print(f"[*] [Process] Setting DEPRECATED_MODE={dep_val} for {mode_text}", flush=True)
    print(f"[*] [Process] Token starts with: {token[:10]}...", flush=True)

    # โหลด main ภายในฟังก์ชันเพื่อให้ใช้ config ที่เราตั้งค่าไว้
    try:
        from main import bot
        print(f"[*] Launching {mode_text}...", flush=True)
        bot.run(token)
    except Exception as e:
        print(f"[!] Error: {e}")

if __name__ == "__main__":
    # โหลดไฟล์ .env หลักเพียงอันเดียว
    load_dotenv()

    print("="*50)
    print("   CYTECH DUAL-INSTANCE RUNNER   ")
    print("   (One .env File / Two Bots)    ")
    print("="*50)

    # ดึง Token จาก .env ที่รวบไว้แล้ว
    main_token = os.getenv("BOT_TOKEN")
    old_token = os.getenv("BOT_TOKEN_OLD") # บอทเก่า (กู้คืนจาก backup)

    if not main_token:
        print("[!] Error: BOT_TOKEN not found in .env")
        sys.exit(1)

    # เตรียม Process
    processes = []

    # 1. รันบอทหลัก
    p_main = multiprocessing.Process(target=run_bot, args=(main_token, False))
    processes.append(p_main)
    print("[*] Starting Instance 1 (Main Bot)...")
    p_main.start()
    
    print("[*] Waiting 10 seconds for Main Bot to initialize...")
    time.sleep(10)

    # 2. รันบอทเก่า (ถ้ามี Token)
    if old_token:
        p_old = multiprocessing.Process(target=run_bot, args=(old_token, True))
        processes.append(p_old)
        print("[*] Starting Instance 2 (Old Bot)...")
        p_old.start()
    else:
        print("[!] Warning: BOT_TOKEN_OLD not found. Skipping Old Bot.")

    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        print("\n[!] Stopping all instances...")
        for p in processes:
            p.terminate()
