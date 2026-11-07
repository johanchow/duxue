"""Record real device interaction; prompts are spoken by macOS and heard by the phone.

Raw footage, UI snapshots and timings stay in ignored output/homepage-demo.
This never injects transcripts or AI replies into the application.
"""
import argparse
import json
import math
import os
import subprocess
import time
from pathlib import Path

ADB = os.environ.get("ADB", str(Path(os.environ.get("ANDROID_HOME", Path.home() / "Library/Android/sdk")) / "platform-tools/adb"))
OUT = Path("output/homepage-demo")


def adb(*args, **kwargs):
    return subprocess.run([ADB, *args], check=True, **kwargs)


def snapshot(name):
    with (OUT / f"{name}.png").open("wb") as file:
        adb("exec-out", "screencap", "-p", stdout=file)
    adb("shell", "uiautomator", "dump", "/sdcard/duxue-demo-ui.xml", stdout=subprocess.DEVNULL)
    adb("pull", "/sdcard/duxue-demo-ui.xml", str(OUT / f"{name}.xml"), stdout=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--wait", type=float, default=18)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "raw").mkdir(exist_ok=True)
    audio = OUT / f"{args.name}-voice.aiff"
    subprocess.run(["say", "-v", "Tingting", "-r", "190", "-o", str(audio), args.prompt], check=True)
    duration = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio)], text=True))
    log = (OUT / "raw" / f"{args.name}.log").open("w")
    record = subprocess.Popen([
        "scrcpy", "--no-playback", "--no-control", "--max-size=1920", "--max-fps=30",
        "--audio-source=playback", "--audio-dup", "--audio-codec=aac",
        "--video-bit-rate=8M", f"--time-limit={math.ceil(duration + args.wait + 20)}",
        f"--record={OUT / 'raw' / (args.name + '.mkv')}",
    ], stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "ADB": ADB})
    start = time.monotonic()
    try:
        time.sleep(3)
        hold = int((duration + 3) * 1000)
        touch = subprocess.Popen([ADB, "shell", "input", "swipe", "430", "2000", "430", "2000", str(hold)])
        time.sleep(2)
        spoken_at = time.monotonic() - start
        subprocess.run(["afplay", str(audio)], check=True)
        touch.wait()
        sent_at = time.monotonic() - start
        time.sleep(args.wait)
        snapshot(args.name)
        time.sleep(3)
    finally:
        try:
            record.wait(timeout=25)
        except subprocess.TimeoutExpired:
            record.kill()
        log.close()
    timings = {"prompt": args.prompt, "voice_start": spoken_at, "voice_duration": duration,
               "sent_at": sent_at, "record_wall_duration": time.monotonic() - start}
    (OUT / f"{args.name}-timings.json").write_text(json.dumps(timings, ensure_ascii=False, indent=2))
    print(json.dumps({"take": args.name, **timings}, ensure_ascii=False))


if __name__ == "__main__":
    main()
