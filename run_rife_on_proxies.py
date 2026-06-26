import os
import sys
import glob
import shutil
import subprocess
import torch
import torch.nn.functional as F
import numpy as np
from PIL import Image
from tqdm import tqdm

# Add RIFE repo to path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rife_repo"))
from interpolation_model import IFNet
from safetensors.torch import load_file

def load_img_tensor(path, device):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    arr = np.array(img).transpose(2, 0, 1)  # [3, H, W]
    tensor = torch.from_numpy(arr).unsqueeze(0).to(device, dtype=torch.float16) / 255.0
    return tensor, w, h

def save_tensor_img(tensor, path):
    tensor = torch.clamp(tensor, 0, 1)
    arr = (tensor.squeeze(0).permute(1, 2, 0).cpu().numpy() * 255.0).astype(np.uint8)
    img = Image.fromarray(arr)
    img.save(path)

def interpolate_file(input_video, output_video, device, model):
    print(f"\nProcessing: {input_video} -> {output_video}")
    
    # 1. Prepare temp dirs
    temp_in = "output/temp_rife_in"
    temp_out = "output/temp_rife_out"
    shutil.rmtree(temp_in, ignore_errors=True)
    shutil.rmtree(temp_out, ignore_errors=True)
    os.makedirs(temp_in, exist_ok=True)
    os.makedirs(temp_out, exist_ok=True)
    
    # 2. Extract frames using FFmpeg
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    extract_cmd = [
        ffmpeg, "-y",
        "-i", input_video,
        "-vsync", "0",
        os.path.join(temp_in, "frame_%05d.png")
    ]
    print(f"  Extracting frames...")
    subprocess.run(extract_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    frames = sorted(glob.glob(os.path.join(temp_in, "frame_*.png")))
    num_frames = len(frames)
    print(f"  Extracted {num_frames} frames.")
    if num_frames < 2:
        print("  [ERROR] Not enough frames extracted.")
        shutil.rmtree(temp_in, ignore_errors=True)
        shutil.rmtree(temp_out, ignore_errors=True)
        return False
    
    # 4. Interpolate
    print("  Performing frame interpolation...")
    out_idx = 1
    
    # Pre-load first frame
    t0, w, h = load_img_tensor(frames[0], device)
    h_pad = (32 - h % 32) % 32
    w_pad = (32 - w % 32) % 32
    padding = (0, w_pad, 0, h_pad)  # left, right, top, bottom
    
    save_tensor_img(t0, os.path.join(temp_out, f"frame_{out_idx:05d}.png"))
    out_idx += 1
    
    for i in tqdm(range(num_frames - 1)):
        t1, _, _ = load_img_tensor(frames[i + 1], device)
        
        # Pad inputs to multiples of 32
        padded_t0 = F.pad(t0, padding, mode="replicate")
        padded_t1 = F.pad(t1, padding, mode="replicate")
        
        with torch.no_grad():
            out = model(torch.cat([padded_t0, padded_t1], dim=1))
            
        cropped_out = out[:, :, :h, :w]
        
        # Save middle frame
        save_tensor_img(cropped_out, os.path.join(temp_out, f"frame_{out_idx:05d}.png"))
        out_idx += 1
        
        # Save original next frame
        save_tensor_img(t1, os.path.join(temp_out, f"frame_{out_idx:05d}.png"))
        out_idx += 1
        
        # Move next frame to current frame
        t0 = t1

    # 5. Assemble final video with audio from original source
    assemble_cmd = [
        ffmpeg, "-y",
        "-r", "47.952",
        "-i", os.path.join(temp_out, "frame_%05d.png"),
        "-i", input_video,
        "-map", "0:v",
        "-map", "1:a?",
        "-vf", "fps=60",
        "-c:v", "libx264",
        "-crf", "20",
        "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k",
        output_video
    ]
    print(f"  Assembling final video at 60fps...")
    subprocess.run(assemble_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # 6. Cleanup
    shutil.rmtree(temp_in, ignore_errors=True)
    shutil.rmtree(temp_out, ignore_errors=True)
    print("  Done!")
    return True

def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")
    
    # Load RIFE model once
    print("Loading RIFE model...")
    model = IFNet()
    model.load_state_dict(load_file("rife_repo/flownet.safetensors"))
    model.half().to(device).eval()
    
    targets = []
    # Collect files from data/proxies/
    for f in glob.glob("data/proxies/*_render.mp4"):
        targets.append(os.path.abspath(f))
    # Collect files from data/proxies_backup_20260623-013023/
    for f in glob.glob("data/proxies_backup_20260623-013023/*_render.mp4"):
        targets.append(os.path.abspath(f))
        
    print(f"Found {len(targets)} video files to process.")
    
    for path in targets:
        bak_path = path + ".bak"
        if not os.path.exists(bak_path):
            print(f"Backing up: {path} -> {bak_path}")
            shutil.copy2(path, bak_path)
            
        success = interpolate_file(bak_path, path, device, model)
        if not success:
            print(f"Failed to process {path}")
            
    print("\nAll batch RIFE frame interpolation processing complete!")

if __name__ == "__main__":
    main()
