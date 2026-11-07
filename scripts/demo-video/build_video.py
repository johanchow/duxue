"""Compose real screen recordings with readable chapter panels and Chinese captions.

Requires ffmpeg/ffprobe and Pillow. Raw material and render products stay in output/.
No application UI, transcripts or model replies are fabricated by this renderer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output/homepage-demo'
FONT = '/Library/Fonts/Arial Unicode.ttf'
INK, GREEN, MUTED = '#203b32', '#267655', '#677b71'


def probe(path):
    return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
        '-show_format', '-of', 'json', str(path)], text=True))


def panel(shot, target):
    im = Image.new('RGB', (1920, 1080), '#f5f7f2')
    d = ImageDraw.Draw(im)
    d.ellipse((1270, -400, 2250, 550), fill='#e6efe6')
    d.ellipse((-350, 730, 500, 1480), fill='#eaf0e5')
    def text(x, y, value, size, color=INK, spacing=18):
        d.multiline_text((x, y), value, font=ImageFont.truetype(FONT, size), fill=color, spacing=spacing)
    text(104, 62, '读学', 43)
    text(224, 83, 'AI 启发式伴学', 23, MUTED)
    d.rounded_rectangle((104, 202, 375, 252), radius=25, fill='#e0ecdf')
    text(127, 208, shot['eyebrow'], 27, GREEN)
    text(104, 294, shot['title'], 67, spacing=25)
    text(109, 515, shot['body'], 32, MUTED, spacing=19)
    if shot.get('quote'):
        text(109, 658, shot['quote'], 28, GREEN, spacing=14)
    labels = ['语音输入', '启发引导', '多形式讲解', '冲刺挑战']
    for i, label in enumerate(labels):
        x = 105 + i * 180
        active = shot['chapter'] == i + 1
        d.rounded_rectangle((x, 838, x + 158, 885), radius=23,
                            fill=GREEN if active else '#e7ede4')
        text(x + 17, 844, label, 23, 'white' if active else MUTED)
    text(925, 57, '手机实录' + (' · 界面局部放大' if shot['crop'][3] < 1600 else ''), 24, MUTED)
    x, y, w, h = shot['placement']
    d.rounded_rectangle((x-8, y-8, x+w+8, y+h+8), radius=18, fill='#cbd9ce')
    d.rounded_rectangle((80, 935, 1840, 1020), radius=24, fill='#203b32')
    caption = shot['caption']
    f = ImageFont.truetype(FONT, 35)
    box = d.textbbox((0, 0), caption, font=f)
    if box[2] > 1680:
        raise ValueError('Caption too long; split the shot instead')
    d.text(((1920-box[2])/2, 951), caption, font=f, fill='white')
    text(104, 1040, '小米真机录制 · 示例题目 · 等待已剪短', 21, MUTED)
    im.save(target)


def stamp(seconds, sep=','):
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02}:{m:02}:{s:02}{sep}{ms:03}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--timeline', type=Path, default=Path(__file__).with_name('shots.json'))
    parser.add_argument('--font', default=FONT)
    args = parser.parse_args()
    global_font = args.font
    if global_font != FONT:
        globals()['FONT'] = global_font
    shots = json.loads(args.timeline.read_text())
    renders = OUT / 'render'
    renders.mkdir(parents=True, exist_ok=True)
    concat, srt, vtt, provenance = [], [], ['WEBVTT\n'], []
    elapsed = 0
    for index, shot in enumerate(shots):
        src = OUT / 'raw' / shot['source']
        info = probe(src)
        stream = next(s for s in info['streams'] if s['codec_type'] == 'video')
        x, y, w, h = shot['crop']
        if min(x, y) < 0 or min(w, h) <= 0 or x+w > stream['width'] or y+h > stream['height']:
            raise ValueError(f'Invalid crop for {src}')
        start, duration = shot['start'], shot['duration']
        if start < 0 or duration <= 0 or start+duration > float(info['format']['duration']) + .1:
            raise ValueError(f'Shot outside recording: {src}')
        bg, clip = renders / f'{index:02}.png', renders / f'{index:02}.mp4'
        panel(shot, bg)
        px, py, pw, ph = shot['placement']
        cmd = ['ffmpeg', '-v', 'error', '-y', '-loop', '1', '-framerate', '30', '-i', str(bg),
               '-ss', str(start), '-t', str(duration), '-i', str(src)]
        filters = [f'[1:v]setpts=PTS-STARTPTS,crop={w}:{h}:{x}:{y},fps=30,scale={pw}:{ph}:flags=lanczos,setsar=1[v]',
                   f'[0:v][v]overlay={px}:{py}:shortest=1,format=yuv420p[out]',
                   f'[1:a]asetpts=PTS-STARTPTS,aresample=48000,apad,atrim=0:{duration}[device]']
        audio_label = '[device]'
        if shot.get('voice_audio'):
            cmd += ['-i', str(OUT / shot['voice_audio'])]
            delay = round(shot.get('voice_delay', 0)*1000)
            filters += [f'[2:a]aresample=48000,adelay={delay}:all=1,apad,atrim=0:{duration}[voice]',
                        '[device][voice]amix=inputs=2:duration=longest:normalize=0[a]']
            audio_label = '[a]'
        cmd += ['-filter_complex', ';'.join(filters), '-map', '[out]', '-map', audio_label,
                '-t', str(duration), '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
                '-c:a', 'aac', '-b:a', '160k', '-ar', '48000', '-ac', '2', '-movflags', '+faststart', str(clip)]
        subprocess.run(cmd, check=True)
        concat.append(f"file '{clip.as_posix()}'")
        srt.append(f'{index+1}\n{stamp(elapsed)} --> {stamp(elapsed+duration)}\n{shot["caption"]}\n')
        vtt.append(f'{stamp(elapsed, ".")} --> {stamp(elapsed+duration, ".")}\n{shot["caption"]}\n')
        provenance.append({'shot':index, 'source':shot['source'], 'sha256':hashlib.sha256(src.read_bytes()).hexdigest(),
                           'in':start,'out':start+duration,'timeline_start':elapsed})
        elapsed += duration
        print(f'{index+1}/{len(shots)} rendered ({elapsed:.1f}s)', flush=True)
    (renders / 'concat.txt').write_text('\n'.join(concat)+'\n')
    final = OUT / 'duxue-demo.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(renders/'concat.txt'),
                    '-c','copy','-movflags','+faststart',str(final)],check=True)
    (OUT/'duxue-demo.srt').write_text('\n'.join(srt))
    (OUT/'duxue-demo.vtt').write_text('\n'.join(vtt))
    (OUT/'provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n')
    check = probe(final)
    video = next(s for s in check['streams'] if s['codec_type']=='video')
    audio = next(s for s in check['streams'] if s['codec_type']=='audio')
    assert (video['codec_name'],video['width'],video['height'],video['pix_fmt']) == ('h264',1920,1080,'yuv420p')
    assert audio['codec_name']=='aac' and abs(float(check['format']['duration'])-elapsed)<.2
    subprocess.run(['ffmpeg','-v','error','-y','-ss','1','-i',str(final),'-frames:v','1',str(OUT/'duxue-demo-poster.jpg')],check=True)
    (OUT/'validation.json').write_text(json.dumps({'expected_duration':elapsed, 'probe':check},ensure_ascii=False,indent=2)+'\n')
    print(final)

if __name__ == '__main__':
    main()
