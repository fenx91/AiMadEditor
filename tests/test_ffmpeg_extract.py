"""
快速诊断脚本：测试对 /home/fenxy/editor/in 里的视频提取关键帧是否正常。
在项目根目录运行：  python tests/test_ffmpeg_extract.py

注意：此文件不通过 pytest 运行（可执行代码放在 if __name__ == '__main__' 里），
     直接 python 执行时才会运行 ffmpeg 提取测试。
"""
import os
import glob
import shutil
import subprocess

if __name__ == '__main__':
    VIDEO_DIR = "/home/fenxy/editor/in"
    OUT_DIR = "/tmp/kf_test"
    os.makedirs(OUT_DIR, exist_ok=True)

    FFPROBE = shutil.which("ffprobe") or "ffprobe"
    FFMPEG  = shutil.which("ffmpeg")  or "ffmpeg"

    # 取第一个视频文件
    videos = sorted(
        glob.glob(os.path.join(VIDEO_DIR, "*.mkv")) +
        glob.glob(os.path.join(VIDEO_DIR, "*.mp4"))
    )
    if not videos:
        print("X 没找到视频文件，请确认路径")
        exit(1)

    video = videos[0]
    print(f"测试文件: {os.path.basename(video)}")

    # 1. 读取时长/编码信息
    print("\n--- Step 1: ffprobe 读取信息 ---")
    probe_cmd = [
        FFPROBE, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "format=duration:stream=r_frame_rate,codec_name,pix_fmt",
        "-of", "json", video
    ]
    result = subprocess.run(probe_cmd, capture_output=True, text=True)
    print(result.stdout or "(无输出)")
    if result.stderr:
        print("stderr:", result.stderr[:500])

    # 2. 提取 2fps 帧（最多 5 帧，快速验证）
    print("\n--- Step 2: ffmpeg 提取 2fps 帧（最多5帧）---")
    out_pattern = os.path.join(OUT_DIR, "frame_%04d.jpg")

    # 先清空旧文件
    for f in glob.glob(os.path.join(OUT_DIR, "frame_*.jpg")):
        os.remove(f)

    extract_cmd = [
        FFMPEG, "-y", "-i", video,
        "-vf", "fps=2",
        "-q:v", "2",
        "-frames:v", "5",
        out_pattern
    ]
    print("命令:", " ".join(extract_cmd))
    result = subprocess.run(extract_cmd, capture_output=True, text=True)
    print("returncode:", result.returncode)

    if result.returncode != 0 or not glob.glob(os.path.join(OUT_DIR, "frame_*.jpg")):
        print("ffmpeg 失败！stderr (最后 2000 字符):")
        print(result.stderr[-2000:])
    else:
        frames = sorted(glob.glob(os.path.join(OUT_DIR, "frame_*.jpg")))
        print(f"成功提取 {len(frames)} 帧:")
        for f in frames:
            print(f"   {os.path.basename(f)}  ({os.path.getsize(f)} bytes)")

    print(f"\n输出目录: {OUT_DIR}")
