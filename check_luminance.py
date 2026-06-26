import os
import subprocess
import numpy as np

def check_video_luminance(video_path):
    print(f"Checking video: {video_path}")
    if not os.path.exists(video_path):
        print("Error: Video file does not exist.")
        return
    
    timestamps = [1.0, 4.0, 7.0, 10.0]
    for t in timestamps:
        raw_cmd = [
            "ffmpeg", "-y",
            "-ss", str(t),
            "-i", video_path,
            "-vframes", "1",
            "-f", "rawvideo",
            "-pix_fmt", "gray",
            "-"
        ]
        raw_res = subprocess.run(raw_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if raw_res.returncode == 0 and len(raw_res.stdout) > 0:
            mean_val = np.mean(np.frombuffer(raw_res.stdout, dtype=np.uint8))
            print(f"Time {t}s: Mean Luminance = {mean_val:.2f} (0-255)")
        else:
            print(f"Time {t}s: Failed to read raw bytes. Error: {raw_res.stderr.decode()[:100]}")

if __name__ == "__main__":
    check_video_luminance("/home/fenxy/editor/output/mv_output.mp4")
    print("\nChecking temporary trimmed video files:")
    check_video_luminance("hyperframes_template/temp_video_0.mp4")
    check_video_luminance("hyperframes_template/temp_video_1.mp4")
    check_video_luminance("hyperframes_template/temp_video_2.mp4")
