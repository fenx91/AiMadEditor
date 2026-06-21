import os
import sys
import glob
import json
import sqlite3
import subprocess
import shutil
import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F
from transformers import CLIPProcessor, CLIPModel

# Resolve ffmpeg/ffprobe full paths at import time so subprocess never gets a bare name.
# On WSL or systems where PATH isn't inherited, bare names cause [Errno 13] Permission denied.
FFPROBE_BIN = shutil.which("ffprobe") or "ffprobe"
FFMPEG_BIN  = shutil.which("ffmpeg")  or "ffmpeg"

if not shutil.which("ffprobe"):
    print("[WARNING] ffprobe not found in PATH. Install ffmpeg: sudo apt install ffmpeg")
if not shutil.which("ffmpeg"):
    print("[WARNING] ffmpeg not found in PATH. Install ffmpeg: sudo apt install ffmpeg")

# Initialize database
def init_db(db_path="data/metadata.db"):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Videos table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        original_path TEXT UNIQUE,
        proxy_path TEXT,
        duration REAL,
        fps REAL,
        indexed_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Keyframes table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS keyframes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id INTEGER,
        timestamp REAL,
        frame_path TEXT,
        embedding BLOB,
        motion_score REAL,
        FOREIGN KEY (video_id) REFERENCES videos (id) ON DELETE CASCADE
    )
    """)
    
    conn.commit()
    conn.close()

# Get video information using ffprobe
def get_video_info(video_path):
    cmd = [
        FFPROBE_BIN, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "format=duration:stream=r_frame_rate",
        "-of", "json", video_path
    ]
    try:
        out = subprocess.check_output(cmd)
        data = json.loads(out)
        
        duration = float(data.get("format", {}).get("duration", 0.0))
        
        r_frame_rate = data.get("streams", [{}])[0].get("r_frame_rate", "30/1")
        if "/" in r_frame_rate:
            num, den = r_frame_rate.split("/")
            fps = float(num) / float(den) if float(den) > 0 else 30.0
        else:
            fps = float(r_frame_rate)
            
        return duration, fps
    except Exception as e:
        print(f"Error getting info for {video_path}: {e}")
        return 0.0, 30.0

# Extract keyframes and generate proxy using FFmpeg
def process_video_media(video_path, keyframes_dir, proxy_dir):
    os.makedirs(keyframes_dir, exist_ok=True)
    os.makedirs(proxy_dir, exist_ok=True)
    
    base_name = os.path.splitext(os.path.basename(video_path))[0]
    
    # 1. Generate 360p Proxy
    proxy_path = os.path.join(proxy_dir, f"{base_name}_proxy.mp4")
    if not os.path.exists(proxy_path):
        print(f"Generating proxy for {video_path}...")
        # Try NVENC GPU encoding first; fall back to CPU if not available
        def _build_proxy_cmd(use_nvenc):
            if use_nvenc:
                return [
                    FFMPEG_BIN, "-y",
                    "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
                    "-i", video_path,
                    "-vf", "scale_cuda=-2:360",
                    "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "28",
                    "-c:a", "aac", "-b:a", "128k", proxy_path
                ]
            else:
                return [
                    FFMPEG_BIN, "-y", "-i", video_path,
                    "-vf", "scale=-2:360", "-c:v", "libx264", "-crf", "28",
                    "-preset", "fast", "-c:a", "aac", "-b:a", "128k", proxy_path
                ]

        # Attempt NVENC first
        result = subprocess.run(
            _build_proxy_cmd(use_nvenc=True),
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
        if result.returncode != 0:
            print(f"  NVENC not available, falling back to CPU encoding...")
            subprocess.run(
                _build_proxy_cmd(use_nvenc=False),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        else:
            print(f"  Proxy generated with NVENC GPU acceleration.")
    
    # 2. Extract frames at fixed intervals (every INTERVAL seconds)
    # This is far more reliable than I-frame detection for HEVC/10-bit content.
    duration_info, _ = get_video_info(video_path)
    INTERVAL = 0.5  # 2 frames per second
    MAX_FRAMES = 3000  # safety cap (~25 mins at 2fps)

    # Clean old keyframes for this video
    # Use glob.escape() so brackets in filenames (e.g. [LoliHouse]) are treated as literals
    video_keyframe_pattern = os.path.join(keyframes_dir, f"{glob.escape(base_name)}_frame_*.jpg")
    for f in glob.glob(video_keyframe_pattern):
        try:
            os.remove(f)
        except OSError:
            pass

    # Use fps=1/INTERVAL filter to grab one frame every INTERVAL seconds
    fps_filter = "fps=2"
    extract_cmd = [
        FFMPEG_BIN, "-y", "-i", video_path,
        "-vf", fps_filter,
        "-q:v", "2",          # JPEG quality (2 = near-lossless)
        "-frames:v", str(MAX_FRAMES),
        os.path.join(keyframes_dir, f"{base_name}_frame_%04d.jpg")
    ]
    result = subprocess.run(extract_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    # Build paired list — use glob.escape() so brackets in filenames don't break glob
    extracted_files = sorted(glob.glob(os.path.join(keyframes_dir, f"{glob.escape(base_name)}_frame_*.jpg")))
    if not extracted_files:
        print(f"  [ERROR] ffmpeg extracted 0 frames! stderr:\n{result.stderr.decode('utf-8', errors='replace')[-2000:]}")
    paired_keyframes = []
    for i, fpath in enumerate(extracted_files):
        paired_keyframes.append({
            "timestamp": round(i * INTERVAL, 2),
            "frame_path": fpath
        })

    print(f"  Extracted {len(paired_keyframes)} keyframes at 2fps.")
    return proxy_path, paired_keyframes


# Calculate motion score between consecutive keyframes
def calculate_motion_scores(keyframes):
    # keyframes is a list of dicts: {"timestamp": ts, "frame_path": path}
    # Motion score for frame N is the mean absolute pixel difference from frame N-1
    # Normalized to [0, 100] approximately
    motion_scores = [0.0] * len(keyframes)
    prev_img_arr = None
    
    for i, kf in enumerate(keyframes):
        try:
            img = Image.open(kf["frame_path"]).convert("L").resize((64, 64))
            img_arr = np.array(img, dtype=np.float32)
            if prev_img_arr is not None:
                diff = np.mean(np.abs(img_arr - prev_img_arr))
                # diff is in [0, 255] range. Normalize it roughly to [0, 10]
                motion_scores[i] = float(diff / 25.5)
            else:
                motion_scores[i] = 0.0
            prev_img_arr = img_arr
        except Exception as e:
            print(f"Error calculating motion for {kf['frame_path']}: {e}")
            motion_scores[i] = 0.0
            
    return motion_scores

class FeatureExtractor:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Loading CLIP model on device: {self.device}")
        self.model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(self.device)
        self.processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        self.model.eval()

    def get_image_embedding(self, image_path):
        try:
            image = Image.open(image_path).convert("RGB")
            inputs = self.processor(images=image, return_tensors="pt").to(self.device)
            with torch.no_grad():
                # Call vision_model directly then apply projection — works on all transformers versions
                vision_out = self.model.vision_model(pixel_values=inputs["pixel_values"])
                feat = self.model.visual_projection(vision_out.pooler_output)
            feat = F.normalize(feat.float(), dim=-1)
            return feat.cpu().numpy()[0]
        except Exception as e:
            print(f"Error extracting embedding for {image_path}: {e}")
            return np.zeros(512, dtype=np.float32)

    def get_text_embedding(self, text):
        try:
            inputs = self.processor(text=[text], return_tensors="pt", padding=True, truncation=True).to(self.device)
            with torch.no_grad():
                # Call text_model directly then apply projection — works on all transformers versions
                text_out = self.model.text_model(
                    input_ids=inputs["input_ids"],
                    attention_mask=inputs.get("attention_mask")
                )
                feat = self.model.text_projection(text_out.pooler_output)
            feat = F.normalize(feat.float(), dim=-1)
            return feat.cpu().numpy()[0]
        except Exception as e:
            print(f"Error extracting embedding for text '{text}': {e}")
            return np.zeros(512, dtype=np.float32)

# Index a single video file
def index_video_file(video_path, extractor, db_path="data/metadata.db"):
    video_path = os.path.abspath(video_path)
    
    # Check cache to skip already indexed videos
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM videos WHERE original_path = ?", (video_path,))
            row = cursor.fetchone()
            if row:
                video_id = row[0]
                cursor.execute("SELECT COUNT(*) FROM keyframes WHERE video_id = ?", (video_id,))
                count = cursor.fetchone()[0]
                if count > 0:
                    print(f"Video {video_path} is already indexed (Cache hit). Skipping extraction.")
                    conn.close()
                    return video_id
            conn.close()
        except Exception as e:
            print(f"Error checking cache for {video_path}: {e}")

    duration, fps = get_video_info(video_path)
    if duration == 0.0:
        print(f"Skipping video {video_path} due to invalid duration.")
        return None
        
    keyframes_dir = "data/keyframes"
    proxy_dir = "data/proxies"
    
    # Process media
    proxy_path, paired_keyframes = process_video_media(video_path, keyframes_dir, proxy_dir)
    
    # Calculate motion scores
    motion_scores = calculate_motion_scores(paired_keyframes)
    
    # Extract features for keyframes
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Insert or replace video entry
    cursor.execute("""
    INSERT OR REPLACE INTO videos (original_path, proxy_path, duration, fps)
    VALUES (?, ?, ?, ?)
    """, (video_path, proxy_path, duration, fps))
    
    video_id = cursor.lastrowid
    
    # Delete old keyframes from DB if re-indexing
    cursor.execute("DELETE FROM keyframes WHERE video_id = ?", (video_id,))
    
    # Batch save keyframes with embeddings
    for i, kf in enumerate(paired_keyframes):
        emb = extractor.get_image_embedding(kf["frame_path"])
        emb_blob = emb.tobytes()
        motion = motion_scores[i]
        
        cursor.execute("""
        INSERT INTO keyframes (video_id, timestamp, frame_path, embedding, motion_score)
        VALUES (?, ?, ?, ?, ?)
        """, (video_id, kf["timestamp"], kf["frame_path"], emb_blob, motion))
        
    conn.commit()
    conn.close()
    print(f"Successfully indexed {video_path} (ID: {video_id}) with {len(paired_keyframes)} keyframes.")
    return video_id

# Scan and index a directory of videos
def index_directory(directory_path, extractor, db_path="data/metadata.db"):
    directory_path = os.path.abspath(directory_path)
    video_extensions = ["*.mp4", "*.mkv", "*.mov", "*.avi"]
    video_files = []
    for ext in video_extensions:
        video_files.extend(glob.glob(os.path.join(directory_path, ext)))
        video_files.extend(glob.glob(os.path.join(directory_path, ext.upper())))
        
    # Deduplicate
    video_files = sorted(list(set(video_files)))
    
    print(f"Found {len(video_files)} videos in {directory_path}.")
    indexed_ids = []
    for vf in video_files:
        vid = index_video_file(vf, extractor, db_path)
        if vid:
            indexed_ids.append(vid)
    return indexed_ids
