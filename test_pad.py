import subprocess
import os

proxy_path = 'data/proxies/[LoliHouse] Super no Ura de Yani Suu Futari - 08 [Early Release][WebRip 1080p HEVC-10bit AAC]_render.mp4'
cmd = [
    'ffmpeg', '-y',
    '-ss', '20.0',
    '-t', '3.48',
    '-i', proxy_path,
    '-vf', 'tpad=start_duration=3.48',
    '-af', 'adelay=3480|3480',
    '-c:v', 'libx264', '-crf', '18', '-preset', 'ultrafast',
    '-pix_fmt', 'yuv420p',
    'tmp_test_pad.mp4'
]

res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
print('code:', res.returncode)
if res.returncode != 0:
    print('err:', res.stderr.decode()[-500:])
else:
    print('Success! File size:', os.path.getsize('tmp_test_pad.mp4'))
