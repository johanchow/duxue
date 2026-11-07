"""Record a bounded control-only take; coordinates are read from a fresh UI dump."""
import argparse
import os
import subprocess

from record_take import ADB, OUT, snapshot

parser = argparse.ArgumentParser()
parser.add_argument('name')
parser.add_argument('--seconds', type=int, default=40)
args = parser.parse_args()
OUT.mkdir(parents=True, exist_ok=True)
log = (OUT / 'raw' / f'{args.name}.log').open('w')
p = subprocess.Popen(['scrcpy', '--no-playback', '--no-control', '--max-size=1920', '--max-fps=30',
    '--audio-source=playback', '--audio-dup', '--audio-codec=aac', '--video-bit-rate=8M',
    f'--time-limit={args.seconds}', f'--record={OUT / "raw" / (args.name + ".mkv")}'],
    stdout=log, stderr=subprocess.STDOUT, env={**os.environ, 'ADB': ADB})
print(f'Recording {args.name} for {args.seconds}s', flush=True)
p.wait(timeout=args.seconds + 25)
log.close()
snapshot(args.name)
