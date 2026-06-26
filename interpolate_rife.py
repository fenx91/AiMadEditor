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

def main():
    if len(sys.argv) < 5:
        print("Usage: python interpolate_rife.py <input_video> <output_video> <start_time> <duration>")
        sys.exit(1)
        
    input_video = sys.argv[1]
    output_video = sys.argv[2]
    start_time = sys.argv[3]
    duration = sys.argv[4]
    
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")
    
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
        "-ss", start_time,
        "-t", duration,
        "-i", input_video,
        "-vsync", "0",
        os.path.join(temp_in, "frame_%05d.png")
    ]
    print(f"Extracting frames: {' '.join(extract_cmd)}")
    subprocess.run(extract_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    frames = sorted(glob.glob(os.path.join(temp_in, "frame_*.png")))
    num_frames = len(frames)
    print(f"Extracted {num_frames} frames.")
    if num_frames < 2:
        print("Not enough frames extracted.")
        sys.exit(1)
        
    # 3. Load RIFE model
    print("Loading RIFE model...")
    model = IFNet()
    model.load_state_dict(load_file("rife_repo/flownet.safetensors"))
    model.half().to(device).eval()
    
    # 4. Interpolate
    print("Performing frame interpolation...")
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
    # We query the input video framerate to set the output rate correctly
    # Input is 23.976 -> Output is 47.952
    assemble_cmd = [
        ffmpeg, "-y",
        "-r", "47.952",
        "-i", os.path.join(temp_out, "frame_%05d.png"),
        "-ss", start_time,
        "-t", duration,
        "-i", input_video,
        "-map", "0:v",
        "-map", "1:a",
        "-vf", "fps=60",
        "-c:v", "libx264",
        "-crf", "20",
        "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k",
        output_video
    ]
    print(f"Assembling video: {' '.join(assemble_cmd)}")
    subprocess.run(assemble_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # 6. Cleanup
    shutil.rmtree(temp_in, ignore_errors=True)
    shutil.rmtree(temp_out, ignore_errors=True)
    print("Done!")

if __name__ == "__main__":
    main()
