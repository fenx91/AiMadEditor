import os
import sys
import glob
import shutil
import subprocess
import torch
import torch.nn.functional as F
import numpy as np
import json
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor

# Add RIFE repo to path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rife_repo"))
from interpolation_model import IFNet
from safetensors.torch import load_file

def get_video_info(video_path):
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", video_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {video_path}: {res.stderr}")
    data = json.loads(res.stdout)
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = int(stream.get("width"))
            height = int(stream.get("height"))
            r_fps = stream.get("r_frame_rate")
            if "/" in r_fps:
                num, den = map(int, r_fps.split("/"))
                fps = num / den if den != 0 else 23.976
            else:
                fps = float(r_fps)
            
            # Get number of frames (approx or exact)
            nb_frames = stream.get("nb_frames")
            if nb_frames:
                total_frames = int(nb_frames)
            else:
                duration = stream.get("duration")
                if duration:
                    total_frames = int(float(duration) * fps)
                else:
                    total_frames = None
            return width, height, fps, total_frames
    raise ValueError(f"No video stream found in {video_path}")

def interpolate_file_stream(input_video, output_video, device, model, position=0):
    try:
        width, height, fps, total_frames = get_video_info(input_video)
    except Exception as e:
        print(f"  [Worker {position} ERROR] Failed to get video info for {input_video}: {e}")
        return False

    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    
    # 1. Start decoder subprocess
    ffmpeg_cmd_dec = [
        ffmpeg, "-y",
        "-i", input_video,
        "-f", "image2pipe",
        "-pix_fmt", "rgb24",
        "-vcodec", "rawvideo",
        "-"
    ]
    process_dec = subprocess.Popen(ffmpeg_cmd_dec, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    
    # 2. Start encoder subprocess
    ffmpeg_cmd_enc = [
        ffmpeg, "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}",
        "-r", f"{2 * fps:.6f}",
        "-i", "-",
        "-i", input_video,
        "-map", "0:v",
        "-map", "1:a?",
        "-c:v", "h264_nvenc",
        "-preset", "p4",
        "-cq", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        output_video
    ]
    process_enc = subprocess.Popen(ffmpeg_cmd_enc, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    frame_bytes = width * height * 3
    h_pad = (32 - height % 32) % 32
    w_pad = (32 - width % 32) % 32
    padding = (0, w_pad, 0, h_pad)  # left, right, top, bottom
    
    t0 = None
    t0_arr = None
    
    video_name = os.path.basename(output_video)[:30]
    pbar = tqdm(total=total_frames, desc=f"Thread {position} | {video_name}", unit="fr", position=position, leave=True)
    
    try:
        while True:
            in_bytes = process_dec.stdout.read(frame_bytes)
            if not in_bytes:
                break
            if len(in_bytes) < frame_bytes:
                break
                
            arr = np.frombuffer(in_bytes, dtype=np.uint8).reshape((height, width, 3))
            t1 = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0).to(device, dtype=torch.float16) / 255.0
            
            if t0 is None:
                # Write first frame
                process_enc.stdin.write(in_bytes)
                t0 = t1
                t0_arr = arr
                pbar.update(1)
                continue
                
            # Pad inputs
            padded_t0 = F.pad(t0, padding, mode="replicate")
            padded_t1 = F.pad(t1, padding, mode="replicate")
            
            with torch.no_grad():
                out = model(torch.cat([padded_t0, padded_t1], dim=1))
                
            cropped_out = out[:, :, :height, :width]
            
            # Convert cropped_out back to cpu and uint8
            cropped_out_arr = (torch.clamp(cropped_out, 0, 1).squeeze(0).permute(1, 2, 0) * 255.0).to(torch.uint8).cpu().numpy()
            
            # Write middle frame
            process_enc.stdin.write(cropped_out_arr.tobytes())
            # Write t1 (original next frame)
            process_enc.stdin.write(in_bytes)
            
            t0 = t1
            t0_arr = arr
            pbar.update(1)
            
    except Exception as e:
        process_dec.kill()
        process_enc.kill()
        pbar.close()
        return False
        
    pbar.close()
    
    # Close pipes and wait for processes
    if process_dec.stdout:
        process_dec.stdout.close()
    process_dec.wait()
    
    if process_enc.stdin:
        process_enc.stdin.close()
    process_enc.wait()
    
    success = (process_dec.returncode == 0 or process_dec.returncode == -15) and process_enc.returncode == 0
    return success

def process_worker(path, worker_id, device, model):
    bak_path = path + ".bak"
    if not os.path.exists(bak_path):
        shutil.copy2(path, bak_path)
    else:
        # If backup exists, check if path is already successfully interpolated (doubled framerate)
        try:
            w_orig, h_orig, fps_orig, total_orig = get_video_info(bak_path)
            w_dest, h_dest, fps_dest, total_dest = get_video_info(path)
            if abs(fps_dest - 2 * fps_orig) < 1.0 and total_dest is not None:
                print(f"\n[SKIP] {os.path.basename(path)} is already interpolated. Skipping.")
                return path, True
        except Exception as e:
            print(f"\n[RE-RUN] {os.path.basename(path)} check failed ({e}), re-interpolating...")
            try:
                os.remove(path)
                shutil.copy2(bak_path, path)
            except Exception:
                pass
        
    success = interpolate_file_stream(bak_path, path, device, model, position=worker_id)
    return path, success

def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")
    
    # Load RIFE model once
    print("Loading RIFE model...")
    model = IFNet()
    model.load_state_dict(load_file("rife_repo/flownet.safetensors"))
    model.half().to(device).eval()
    try:
        print("Compiling model with torch.compile...")
        model = torch.compile(model)
        
        # Warm-up compile with a dummy input
        print("Warming up compiled model...")
        dummy_input = torch.zeros((1, 6, 1088, 1920), dtype=torch.float16, device=device)
        with torch.no_grad():
            _ = model(dummy_input)
        print("Warm-up complete.")
    except Exception as e:
        print(f"torch.compile failed (will use eager mode): {e}")
    
    targets = []
    # Collect files from data/proxies/
    for f in glob.glob("data/proxies/*_render.mp4"):
        targets.append(os.path.abspath(f))
    # Commented out: No need to process backup proxies
    # for f in glob.glob("data/proxies_backup_20260623-013023/*_render.mp4"):
    #     targets.append(os.path.abspath(f))
        
    print(f"Found {len(targets)} video files to process.")
    
    # Sort targets to process smaller files first
    targets.sort()
    
    # Process files concurrently using ThreadPoolExecutor
    num_workers = 2
    print(f"Starting ThreadPoolExecutor with {num_workers} parallel workers...")
    
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = []
        for i, path in enumerate(targets):
            # assign worker_id from 0 to num_workers-1
            worker_id = i % num_workers
            futures.append(executor.submit(process_worker, path, worker_id, device, model))
            
        for future in futures:
            path, success = future.result()
            if success:
                print(f"\n[SUCCESS] Completed RIFE interpolation for {path}")
            else:
                print(f"\n[FAILED] RIFE interpolation failed for {path}")
                
    print("\nAll batch RIFE frame interpolation processing complete!")

if __name__ == "__main__":
    main()
