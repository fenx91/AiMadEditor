import subprocess
import numpy as np

def get_frame_hash(file, time):
    cmd = [
        'ffmpeg', '-y',
        '-ss', str(time),
        '-i', file,
        '-vframes', '1',
        '-f', 'rawvideo',
        '-pix_fmt', 'gray',
        '-'
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return np.frombuffer(res.stdout, dtype=np.uint8)

f_mv = get_frame_hash('output/mv_output.mp4', 1.0)
f_orig_1 = get_frame_hash('hyperframes_template/temp_video_0.mp4', 1.0)
f_orig_11 = get_frame_hash('hyperframes_template/temp_video_0.mp4', 11.0)

print(f"f_mv size: {len(f_mv)}")
print(f"f_orig_1 size: {len(f_orig_1)}")
print(f"f_orig_11 size: {len(f_orig_11)}")

if len(f_mv) == len(f_orig_1):
    diff_1s = np.mean(np.abs(f_mv.astype(float) - f_orig_1.astype(float)))
    print(f"Diff with 1.0s: {diff_1s:.4f}")

if len(f_mv) == len(f_orig_11):
    diff_11s = np.mean(np.abs(f_mv.astype(float) - f_orig_11.astype(float)))
    print(f"Diff with 11.0s: {diff_11s:.4f}")
