import os
import sys
import re
import glob
import json
import sqlite3
import subprocess
import shutil
import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F
from transformers import CLIPProcessor, CLIPModel, pipeline

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
        asr_processed INTEGER DEFAULT 0,
        indexed_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Run migration in case table was created before asr_processed column was added
    try:
        cursor.execute("ALTER TABLE videos ADD COLUMN asr_processed INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        # Column already exists
        pass
    
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
    
    # Transcripts table for audio speech-to-text
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transcripts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id INTEGER,
        start_time REAL,
        end_time REAL,
        text TEXT,
        embedding BLOB,
        FOREIGN KEY (video_id) REFERENCES videos (id) ON DELETE CASCADE
    )
    """)
    
    # Video segments table for multimodal scene understanding
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS video_segments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id INTEGER,
        start_time REAL,
        end_time REAL,
        summary TEXT,
        tags TEXT,
        visual_style TEXT,
        motion_intensity TEXT,
        key_objects TEXT,
        emotion_flow TEXT,
        is_op INTEGER DEFAULT 0,
        is_ed INTEGER DEFAULT 0,
        transcript TEXT,
        mad_score INTEGER DEFAULT 5,
        scene_type TEXT DEFAULT 'dialogue',
        FOREIGN KEY (video_id) REFERENCES videos (id) ON DELETE CASCADE
    )
    """)
    
    # Migrate existing databases: add new columns if not present
    try:
        cursor.execute("ALTER TABLE video_segments ADD COLUMN mad_score INTEGER DEFAULT 5")
    except Exception:
        pass  # Column already exists
    try:
        cursor.execute("ALTER TABLE video_segments ADD COLUMN scene_type TEXT DEFAULT 'dialogue'")
    except Exception:
        pass  # Column already exists
    
    # Vision recommendations cache table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vision_cache (
        lyrics_hash TEXT PRIMARY KEY,
        recommendations TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Match cache table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS match_cache (
        query_hash TEXT PRIMARY KEY,
        candidates_json TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
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
    
    # 1. Generate 360p Proxy - Disabled to use original high-def video directly
    proxy_path = video_path
    print(f"Bypassing proxy generation for {video_path}, using original high-def path.")
    
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

import base64
import urllib.request

def get_gemini_api_key():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    api_key = os.environ.get("GOOGLE_API_KEY")
    if api_key:
        return api_key
    env_path = "/home/fenxy/my_new_agent/.env"
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("GOOGLE_API_KEY="):
                        return line.strip().split("GOOGLE_API_KEY=", 1)[1].strip()
        except Exception as e:
            print(f"Error reading env file: {e}")
    return None

def has_audio(video_path):
    cmd = [
        FFPROBE_BIN, "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_type",
        "-of", "json", video_path
    ]
    try:
        out = subprocess.check_output(cmd)
        data = json.loads(out)
        return len(data.get("streams", [])) > 0
    except Exception as e:
        print(f"Error checking audio stream for {video_path}: {e}")
        return False

def extract_audio(video_path, audio_path):
    cmd = [
        FFMPEG_BIN, "-y",
        "-i", video_path,
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k",
        audio_path
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception as e:
        print(f"Failed to extract audio from {video_path}: {e}")
        return False

def parse_srt(srt_path):
    segments = []
    if not os.path.exists(srt_path):
        return segments
    seen = set()
    try:
        with open(srt_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read().replace("\r\n", "\n")
        # Split by empty lines to get blocks
        blocks = content.strip().split("\n\n")
        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) >= 3:
                timing_line = lines[1]
                text = " ".join(lines[2:]).strip()
                if "-->" in timing_line:
                    parts = timing_line.split("-->")
                    start_str = parts[0].strip()
                    end_str = parts[1].strip()
                    
                    def time_to_sec(t_str):
                        t_parts = t_str.replace(",", ".").split(":")
                        h = int(t_parts[0])
                        m = int(t_parts[1])
                        s = float(t_parts[2])
                        return h * 3600 + m * 60 + s
                        
                    start = time_to_sec(start_str)
                    end = time_to_sec(end_str)
                    key = (round(start, 1), text)
                    if key not in seen:
                        seen.add(key)
                        segments.append({"start": start, "end": end, "text": text})
    except Exception as e:
        print(f"Error parsing SRT file {srt_path}: {e}")
    return segments

def parse_lrc(lrc_path):
    segments = []
    if not os.path.exists(lrc_path):
        return segments
    seen = set()
    try:
        pattern = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")
        with open(lrc_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        
        raw_lines = []
        for line in lines:
            match = pattern.match(line.strip())
            if match:
                m = int(match.group(1))
                s = float(match.group(2))
                t = match.group(3).strip()
                sec = m * 60 + s
                raw_lines.append((sec, t))
                
        raw_lines.sort(key=lambda x: x[0])
        
        for i in range(len(raw_lines)):
            start = raw_lines[i][0]
            text = raw_lines[i][1]
            if not text:
                continue
            if i < len(raw_lines) - 1:
                end = raw_lines[i+1][0]
            else:
                end = start + 4.0
            key = (round(start, 1), text)
            if key not in seen:
                seen.add(key)
                segments.append({"start": start, "end": end, "text": text})
    except Exception as e:
        print(f"Error parsing LRC file {lrc_path}: {e}")
    return segments

def parse_ass(ass_path):
    segments = []
    if not os.path.exists(ass_path):
        return segments
    seen = set()
    try:
        with open(ass_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            
        for line in lines:
            line_str = line.strip()
            if line_str.startswith("Dialogue:"):
                # Dialogue: Marked,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
                # We split by comma at most 9 times to separate fields, the 10th part is Text
                parts = line_str.split(",", 9)
                if len(parts) >= 10:
                    start_str = parts[1].strip()
                    end_str = parts[2].strip()
                    text = parts[9].strip()
                    
                    # Clean ASS formatting tags like {\fn...} or {\pos...} or {\fad...}
                    text = re.sub(r"\{.*?\}", "", text)
                    # Replace ASS line breaks \N with space
                    text = text.replace(r"\N", " ").replace(r"\n", " ").replace(r"\h", " ").strip()
                    
                    if not text:
                        continue
                        
                    def time_to_sec(t_str):
                        t_parts = t_str.split(":")
                        h = int(t_parts[0])
                        m = int(t_parts[1])
                        s = float(t_parts[2])
                        return h * 3600 + m * 60 + s
                        
                    try:
                        start = time_to_sec(start_str)
                        end = time_to_sec(end_str)
                        key = (round(start, 1), text)
                        if key not in seen:
                            seen.add(key)
                            segments.append({"start": start, "end": end, "text": text})
                    except Exception:
                        continue
    except Exception as e:
        print(f"Error parsing ASS file {ass_path}: {e}")
    return segments

def find_matching_subtitle_file(video_path):
    video_dir = os.path.dirname(video_path)
    video_name = os.path.basename(video_path)
    
    # 1. Extract episode number from video name (e.g. - 01)
    match_ep = re.search(r"-\s*(\d{1,2})", video_name)
    if not match_ep:
        match_ep = re.search(r"\b(\d{1,2})\b", video_name)
        
    if not match_ep:
        return None
        
    ep_num = int(match_ep.group(1))
    
    # 2. Look in the subtitles/ subfolder, then video_dir
    sub_dirs = [os.path.join(video_dir, "subtitles"), video_dir]
    
    candidate_files = []
    for s_dir in sub_dirs:
        if os.path.exists(s_dir) and os.path.isdir(s_dir):
            for f in os.listdir(s_dir):
                f_lower = f.lower()
                if any(f_lower.endswith(ext) for ext in [".ass", ".srt", ".lrc"]):
                    sub_ep_match = re.search(r"[eE](\d{1,2})", f)
                    if not sub_ep_match:
                        sub_ep_match = re.search(r"-\s*(\d{1,2})", f)
                    if not sub_ep_match:
                        sub_ep_match = re.search(r"\b(\d{1,2})\b", f)
                        
                    if sub_ep_match:
                        sub_ep_num = int(sub_ep_match.group(1))
                        if sub_ep_num == ep_num:
                            candidate_files.append(os.path.join(s_dir, f))
                            
    if not candidate_files:
        return None
        
    # Prioritize chs (Simplified Chinese) subtitle
    for f in candidate_files:
        if ".chs." in f.lower() or "简体" in f or "sc" in f.lower():
            return f
            
    # Then cht (Traditional Chinese)
    for f in candidate_files:
        if ".cht." in f.lower() or "繁体" in f or "tc" in f.lower():
            return f
            
    return candidate_files[0]

def check_and_parse_local_subtitles(video_path):
    # First: check same-name files
    base_no_ext = os.path.splitext(video_path)[0]
    srt_path = base_no_ext + ".srt"
    lrc_path = base_no_ext + ".lrc"
    ass_path = base_no_ext + ".ass"
    
    candidate_paths = [
        srt_path,
        lrc_path,
        ass_path,
        base_no_ext + ".chs.ass",
        base_no_ext + ".cht.ass"
    ]
    
    for path in candidate_paths:
        if os.path.exists(path):
            ext = os.path.splitext(path)[1].lower()
            if path.endswith(".ass"):
                print(f"  [ASR] Found local ASS subtitle file: {path}. Indexing from it directly...")
                return parse_ass(path), True
            elif ext == ".srt":
                print(f"  [ASR] Found local SRT subtitle file: {path}. Indexing from it directly...")
                return parse_srt(path), True
            elif ext == ".lrc":
                print(f"  [ASR] Found local LRC subtitle file: {path}. Indexing from it directly...")
                return parse_lrc(path), True
                
    # Second: find automatically matched subtitle files (e.g. from subtitles/ folder)
    matched_sub = find_matching_subtitle_file(video_path)
    if matched_sub:
        ext = os.path.splitext(matched_sub)[1].lower()
        if matched_sub.endswith(".ass"):
            print(f"  [ASR] Found matched ASS subtitle file: {matched_sub}. Indexing from it directly...")
            return parse_ass(matched_sub), True
        elif ext == ".srt":
            print(f"  [ASR] Found matched SRT subtitle file: {matched_sub}. Indexing from it directly...")
            return parse_srt(matched_sub), True
        elif ext == ".lrc":
            print(f"  [ASR] Found matched LRC subtitle file: {matched_sub}. Indexing from it directly...")
            return parse_lrc(matched_sub), True
            
    return [], False

_whisper_pipeline = None

def get_whisper_pipeline(model_name="openai/whisper-base"):
    global _whisper_pipeline
    if _whisper_pipeline is None:
        device = 0 if torch.cuda.is_available() else -1
        torch_dtype = torch.float16 if device == 0 else torch.float32
        print(f"  [ASR] Initializing local Whisper model '{model_name}' on {'CUDA (GPU)' if device == 0 else 'CPU'}...")
        try:
            _whisper_pipeline = pipeline(
                "automatic-speech-recognition",
                model=model_name,
                torch_dtype=torch_dtype,
                device=device,
                chunk_length_s=30
            )
        except Exception as e:
            print(f"  [ASR] Failed to load Whisper pipeline on GPU: {e}. Falling back to CPU...")
            try:
                _whisper_pipeline = pipeline(
                    "automatic-speech-recognition",
                    model=model_name,
                    torch_dtype=torch.float32,
                    device=-1,
                    chunk_length_s=30
                )
            except Exception as e_cpu:
                print(f"  [ASR] Failed to load Whisper pipeline on CPU: {e_cpu}")
                raise e_cpu
    return _whisper_pipeline

def transcribe_audio_with_local_whisper(audio_path, model_name="openai/whisper-base"):
    try:
        pipe = get_whisper_pipeline(model_name)
        print(f"  [ASR] Transcribing '{audio_path}' with local Whisper base...")
        result = pipe(audio_path, return_timestamps=True)
        
        segments = []
        chunks = result.get("chunks", [])
        for chunk in chunks:
            timestamp = chunk.get("timestamp")
            text = chunk.get("text", "").strip()
            if not text:
                continue
            
            start = 0.0
            end = 3.0
            if timestamp:
                if timestamp[0] is not None:
                    start = float(timestamp[0])
                if timestamp[1] is not None:
                    end = float(timestamp[1])
                else:
                    end = start + 3.0
                    
            segments.append({
                "start": start,
                "end": end,
                "text": text
            })
            
        return segments
    except Exception as e:
        print(f"Local Whisper ASR request failed for {audio_path}: {e}")
        return []

def transcribe_audio(audio_path):
    print("  [ASR] Attempting local Whisper transcription...")
    segments = transcribe_audio_with_local_whisper(audio_path)
    if segments:
        return segments
    
    print("  [ASR] Local Whisper transcription returned empty or failed. Attempting Gemini API fallback...")
    return transcribe_audio_with_gemini(audio_path)

def transcribe_audio_with_gemini(audio_path):
    api_key = get_gemini_api_key()
    if not api_key:
        print("[WARNING] GOOGLE_API_KEY not found. Skipping Gemini audio transcription.")
        return []
        
    try:
        with open(audio_path, "rb") as f:
            audio_data = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        print(f"Failed to read/encode audio file {audio_path}: {e}")
        return []

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
    
    prompt = """
    请转写这段音频中所有说话的人声台词或对白。
    请严格输出一个符合以下 JSON 格式的 JSON 数组，不要返回任何 Markdown 标记或多余的文字：
    [
      {
        "start": 0.0,
        "end": 2.5,
        "text": "台词内容..."
      },
      ...
    ]
    请确保：
    1. 仅转写有人声说话的部分，忽略纯音乐或静音。
    2. start 和 end 分别是该句台词的起始秒数与结束秒数（浮点数）。
    3. 文本必须准确，如果是中文请输出简体中文，支持中英双语混合。
    """
    
    payload = {
        "contents": [{
            "parts": [
                {
                    "inlineData": {
                        "mimeType": "audio/mp3",
                        "data": audio_data
                    }
                },
                {
                    "text": prompt
                }
            ]
        }],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            res_data = json.loads(response.read().decode("utf-8"))
        text = res_data["candidates"][0]["content"]["parts"][0]["text"]
        segments = json.loads(text)
        if not isinstance(segments, list):
            print(f"[WARNING] Gemini returned non-list JSON: {text}")
            return []
        return segments
    except Exception as e:
        print(f"Gemini ASR request failed for {audio_path}: {e}")
        return []

def backfill_voice_transcripts(video_path, video_id, duration, extractor, db_path):
    segments, sub_loaded = check_and_parse_local_subtitles(video_path)
    if sub_loaded:
        print(f"  [ASR Backfill] Successfully parsed {len(segments)} segments from local subtitle file.")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM transcripts WHERE video_id = ?", (video_id,))
        for seg in segments:
            seg_text = seg.get("text", "").strip()
            seg_start = float(seg.get("start", 0.0))
            seg_end = float(seg.get("end", 0.0))
            if not seg_text:
                continue
            seg_emb = extractor.get_text_embedding(seg_text)
            seg_emb_blob = seg_emb.tobytes()
            cursor.execute("""
            INSERT INTO transcripts (video_id, start_time, end_time, text, embedding)
            VALUES (?, ?, ?, ?, ?)
            """, (video_id, seg_start, seg_end, seg_text, seg_emb_blob))
        cursor.execute("UPDATE videos SET asr_processed = 1 WHERE id = ?", (video_id,))
        conn.commit()
        conn.close()
        print(f"  [ASR Backfill] Successfully indexed voice transcripts from local subtitle file.")
        annotate_video_segments(video_id, video_path, extractor, db_path)
        return

    if duration <= 1200.0 and has_audio(video_path):
        os.makedirs("data/audio", exist_ok=True)
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        audio_filename = f"{base_name}_audio.mp3"
        audio_path = os.path.join("data/audio", audio_filename)
        
        print(f"  [ASR Backfill] Audio stream detected. Extracting audio to {audio_path}...")
        if extract_audio(video_path, audio_path):
            print(f"  [ASR Backfill] Transcribing audio (local Whisper with Gemini fallback)...")
            segments = transcribe_audio(audio_path)
            if segments:
                print(f"  [ASR Backfill] Successfully transcribed {len(segments)} dialogue segments.")
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM transcripts WHERE video_id = ?", (video_id,))
                for seg in segments:
                    seg_text = seg.get("text", "").strip()
                    seg_start = float(seg.get("start", 0.0))
                    seg_end = float(seg.get("end", 0.0))
                    if not seg_text:
                        continue
                    seg_emb = extractor.get_text_embedding(seg_text)
                    seg_emb_blob = seg_emb.tobytes()
                    cursor.execute("""
                    INSERT INTO transcripts (video_id, start_time, end_time, text, embedding)
                    VALUES (?, ?, ?, ?, ?)
                    """, (video_id, seg_start, seg_end, seg_text, seg_emb_blob))
                cursor.execute("UPDATE videos SET asr_processed = 1 WHERE id = ?", (video_id,))
                conn.commit()
                conn.close()
                print(f"  [ASR Backfill] Successfully indexed voice transcripts.")
            else:
                print(f"  [ASR Backfill] No dialogue found or ASR failed.")
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("UPDATE videos SET asr_processed = 1 WHERE id = ?", (video_id,))
                conn.commit()
                conn.close()
            
            if os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                except OSError:
                    pass
        else:
            print(f"  [ASR Backfill] Skipped due to audio extraction failure.")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("UPDATE videos SET asr_processed = 1 WHERE id = ?", (video_id,))
            conn.commit()
            conn.close()
    else:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE videos SET asr_processed = 1 WHERE id = ?", (video_id,))
        conn.commit()
        conn.close()
        if duration > 1200.0:
            print(f"  [ASR Backfill] Skipped: duration ({duration:.1f}s) exceeds limit.")
        else:
            print(f"  [ASR Backfill] Skipped: no audio track.")
            
    annotate_video_segments(video_id, video_path, extractor, db_path)

# Index a single video file
def index_video_file(video_path, extractor, db_path="data/metadata.db", force_refresh=False):
    video_path = os.path.abspath(video_path)
    
    # If force_refresh is True, delete existing cache records first
    if force_refresh and os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM videos WHERE original_path = ?", (video_path,))
            row = cursor.fetchone()
            if row:
                video_id = row[0]
                print(f"Force refresh: Deleting existing database cache for video ID {video_id} ({video_path})...")
                cursor.execute("DELETE FROM keyframes WHERE video_id = ?", (video_id,))
                cursor.execute("DELETE FROM transcripts WHERE video_id = ?", (video_id,))
                cursor.execute("DELETE FROM video_segments WHERE video_id = ?", (video_id,))
                cursor.execute("DELETE FROM videos WHERE id = ?", (video_id,))
                conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error clearing cache for force refresh of {video_path}: {e}")
            
    # Check cache to skip already indexed videos
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id, asr_processed FROM videos WHERE original_path = ?", (video_path,))
            row = cursor.fetchone()
            if row:
                video_id = row[0]
                # Default to 0 if asr_processed column was missing
                asr_processed = row[1] if len(row) > 1 and row[1] is not None else 0
                
                cursor.execute("SELECT COUNT(*) FROM keyframes WHERE video_id = ?", (video_id,))
                count = cursor.fetchone()[0]
                if count > 0:
                    if asr_processed == 1:
                        # Check if segments are also annotated
                        cursor.execute("SELECT COUNT(*) FROM video_segments WHERE video_id = ?", (video_id,))
                        seg_count = cursor.fetchone()[0]
                        if seg_count > 0:
                            print(f"Video {video_path} is already fully indexed (Cache hit). Skipping.")
                            conn.close()
                            return video_id
                        else:
                            print(f"Video {video_path} is indexed but lacks segments. Annotating segments...")
                            conn.close()
                            annotate_video_segments(video_id, video_path, extractor, db_path)
                            return video_id
                    else:
                        print(f"Video {video_path} has keyframes but lacks ASR. Running backfill...")
                        conn.close()
                        duration, fps = get_video_info(video_path)
                        backfill_voice_transcripts(video_path, video_id, duration, extractor, db_path)
                        annotate_video_segments(video_id, video_path, extractor, db_path)
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
    INSERT OR REPLACE INTO videos (original_path, proxy_path, duration, fps, asr_processed)
    VALUES (?, ?, ?, ?, 0)
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
    
    # 3. Audio Transcript Indexing / Subtitle Parsing
    segments, sub_loaded = check_and_parse_local_subtitles(video_path)
    if sub_loaded:
        print(f"  [ASR] Successfully parsed {len(segments)} segments from local subtitle file.")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM transcripts WHERE video_id = ?", (video_id,))
        for seg in segments:
            seg_text = seg.get("text", "").strip()
            seg_start = float(seg.get("start", 0.0))
            seg_end = float(seg.get("end", 0.0))
            if not seg_text:
                continue
            seg_emb = extractor.get_text_embedding(seg_text)
            seg_emb_blob = seg_emb.tobytes()
            cursor.execute("""
            INSERT INTO transcripts (video_id, start_time, end_time, text, embedding)
            VALUES (?, ?, ?, ?, ?)
            """, (video_id, seg_start, seg_end, seg_text, seg_emb_blob))
        cursor.execute("UPDATE videos SET asr_processed = 1 WHERE id = ?", (video_id,))
        conn.commit()
        conn.close()
        print(f"  [ASR] Successfully indexed subtitle transcripts for {video_path}.")
    elif duration <= 1200.0 and has_audio(video_path):
        os.makedirs("data/audio", exist_ok=True)
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        audio_filename = f"{base_name}_audio.mp3"
        audio_path = os.path.join("data/audio", audio_filename)
        
        print(f"  [ASR] Audio stream detected. Extracting audio to {audio_path}...")
        if extract_audio(video_path, audio_path):
            print(f"  [ASR] Transcribing audio (local Whisper with Gemini fallback)...")
            segments = transcribe_audio(audio_path)
            if segments:
                print(f"  [ASR] Successfully transcribed {len(segments)} dialogue segments.")
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                # Clear old transcripts if re-indexing
                cursor.execute("DELETE FROM transcripts WHERE video_id = ?", (video_id,))
                
                for seg in segments:
                    seg_text = seg.get("text", "").strip()
                    seg_start = float(seg.get("start", 0.0))
                    seg_end = float(seg.get("end", 0.0))
                    
                    if not seg_text:
                        continue
                        
                    # Calculate CLIP embedding for transcript segment text
                    seg_emb = extractor.get_text_embedding(seg_text)
                    seg_emb_blob = seg_emb.tobytes()
                    
                    cursor.execute("""
                    INSERT INTO transcripts (video_id, start_time, end_time, text, embedding)
                    VALUES (?, ?, ?, ?, ?)
                    """, (video_id, seg_start, seg_end, seg_text, seg_emb_blob))
                cursor.execute("UPDATE videos SET asr_processed = 1 WHERE id = ?", (video_id,))
                conn.commit()
                conn.close()
                print(f"  [ASR] Successfully indexed voice transcripts for {video_path}.")
            else:
                print(f"  [ASR] No dialogue found or ASR failed for {video_path}.")
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("UPDATE videos SET asr_processed = 1 WHERE id = ?", (video_id,))
                conn.commit()
                conn.close()
            
            # Clean up temporary audio file to save disk space
            if os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                except OSError:
                    pass
        else:
            print(f"  [ASR] Skipped transcription due to audio extraction failure.")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("UPDATE videos SET asr_processed = 1 WHERE id = ?", (video_id,))
            conn.commit()
            conn.close()
    else:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE videos SET asr_processed = 1 WHERE id = ?", (video_id,))
        conn.commit()
        conn.close()
        if duration > 1200.0:
            print(f"  [ASR] Video duration ({duration:.1f}s) exceeds safety limit of 1200s. Skipping voice indexing.")
        else:
            print(f"  [ASR] No audio track detected. Skipping voice indexing.")

    print(f"Successfully indexed {video_path} (ID: {video_id}) with {len(paired_keyframes)} keyframes.")
    annotate_video_segments(video_id, video_path, extractor, db_path)

    # Clear matching cache since the video library has changed
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM match_cache")
        conn.commit()
        conn.close()
        print("  [Cache Invalidation] Successfully cleared match_cache due to new video indexing.")
    except Exception as e:
        print(f"  [Cache Invalidation] Failed to clear match_cache: {e}")

    return video_id

# Scan and index a directory of videos
def index_directory(directory_path, extractor, db_path="data/metadata.db", force_refresh=False):
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
        vid = index_video_file(vf, extractor, db_path, force_refresh)
        if vid:
            indexed_ids.append(vid)
    return indexed_ids


def slice_video_into_segments(video_id, db_path="data/metadata.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT timestamp, motion_score, frame_path 
    FROM keyframes WHERE video_id = ? ORDER BY timestamp
    """, (video_id,))
    keyframes = [{"timestamp": r[0], "motion_score": r[1] or 0.0, "frame_path": r[2]} for r in cursor.fetchall()]
    
    cursor.execute("""
    SELECT start_time, end_time, text 
    FROM transcripts WHERE video_id = ? ORDER BY start_time
    """, (video_id,))
    transcripts = [{"start": r[0], "end": r[1], "text": r[2]} for r in cursor.fetchall()]
    
    cursor.execute("SELECT duration FROM videos WHERE id = ?", (video_id,))
    duration_row = cursor.fetchone()
    duration = duration_row[0] if duration_row else 0.0
    conn.close()
    
    if not keyframes:
        return []
        
    boundaries = set()
    
    # 1. Motion cuts
    for kf in keyframes:
        if kf["motion_score"] > 6.0:
            boundaries.add(kf["timestamp"])
            
    # 2. Dialogue silence cuts
    for i in range(len(transcripts) - 1):
        gap = transcripts[i+1]["start"] - transcripts[i]["end"]
        if gap > 2.5:
            boundaries.add(round(transcripts[i]["end"] + gap / 2.0, 2))
            
    boundaries.add(0.0)
    boundaries.add(duration)
    
    sorted_boundaries = sorted(list(boundaries))
    
    partition = []
    start = 0.0
    for b in sorted_boundaries:
        if b - start >= 4.0:
            if duration - b < 4.0:
                continue
            seg_len = b - start
            if seg_len > 15.0:
                num_chunks = int(seg_len // 10.0) + 1
                chunk_size = seg_len / num_chunks
                for _ in range(num_chunks - 1):
                    chunk_end = round(start + chunk_size, 2)
                    partition.append((start, chunk_end))
                    start = chunk_end
            partition.append((start, b))
            start = b
            
    if start < duration:
        if partition:
            if duration - start < 4.0:
                last_start, last_end = partition.pop()
                partition.append((last_start, duration))
            else:
                partition.append((start, duration))
        else:
            partition.append((start, duration))
            
    final_segments = []
    for s_start, s_end in partition:
        seg_kfs = [kf for kf in keyframes if s_start <= kf["timestamp"] <= s_end]
        seg_trans = [t for t in transcripts if s_start <= t["start"] <= s_end or (t["start"] <= s_start and t["end"] >= s_end)]
        
        rep_frame_paths = []
        if seg_kfs:
            if len(seg_kfs) <= 3:
                rep_frame_paths = [kf["frame_path"] for kf in seg_kfs]
            else:
                rep_frame_paths = [
                    seg_kfs[0]["frame_path"],
                    seg_kfs[len(seg_kfs)//2]["frame_path"],
                    seg_kfs[-1]["frame_path"]
                ]
                
        final_segments.append({
            "start_time": s_start,
            "end_time": s_end,
            "keyframes": rep_frame_paths,
            "transcript": " ".join([t["text"] for t in seg_trans]).strip()
        })
        
    return final_segments


def extract_audio_snippet(video_path, start_time, end_time, output_path):
    duration = max(0.1, end_time - start_time)
    cmd = [
        FFMPEG_BIN, "-y",
        "-ss", str(start_time),
        "-i", video_path,
        "-t", str(duration),
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k",
        output_path
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception as e:
        print(f"Failed to extract audio snippet from {start_time}s to {end_time}s: {e}")
        return False


_CHARACTER_PORTRAITS_CACHE = None

def get_character_portraits():
    global _CHARACTER_PORTRAITS_CACHE
    if _CHARACTER_PORTRAITS_CACHE is not None:
        return _CHARACTER_PORTRAITS_CACHE
    
    import base64
    portraits = []
    portrait_files = [
        "sasaki_1.jpg", "sasaki_2.jpg",
        "yamada_1.jpg", "yamada_2.jpg",
        "tayama_1.jpg", "tayama_2.jpg"
    ]
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    portraits_dir = os.path.join(project_root, "data/character_portraits")
    
    for filename in portrait_files:
        filepath = os.path.join(portraits_dir, filename)
        if os.path.exists(filepath):
            try:
                with open(filepath, "rb") as f:
                    img_data = base64.b64encode(f.read()).decode("utf-8")
                portraits.append({
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": img_data
                    }
                })
            except Exception as e:
                print(f"[WARNING] Failed to load character portrait {filename}: {e}")
        else:
            print(f"[WARNING] Character portrait not found: {filepath}")
            
    _CHARACTER_PORTRAITS_CACHE = portraits
    return portraits


def build_gemini_payload(start_time, end_time, transcript, keyframe_paths, audio_snippet_path):
    parts = []
    
    # 1. Add character reference portraits (6 images: 2 for Sasaki, 2 for Yamada, 2 for Tayama)
    portraits = get_character_portraits()
    parts.extend(portraits)
    
    # 2. Add segment keyframes
    import base64
    for kp in keyframe_paths:
        if os.path.exists(kp):
            try:
                with open(kp, "rb") as f:
                    img_data = base64.b64encode(f.read()).decode("utf-8")
                parts.append({
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": img_data
                    }
                })
            except Exception as e:
                print(f"Error reading keyframe image for Gemini: {e}")
                
    if audio_snippet_path and os.path.exists(audio_snippet_path):
        try:
            with open(audio_snippet_path, "rb") as f:
                aud_data = base64.b64encode(f.read()).decode("utf-8")
            parts.append({
                "inlineData": {
                    "mimeType": "audio/mp3",
                    "data": aud_data
                }
            })
        except Exception as e:
            print(f"Error reading audio snippet for Gemini: {e}")
            
    prompt = f"""
Analyze this video segment spanning from {start_time}s to {end_time}s.
You are given:
1. A reference portrait library of the main characters:
   - The first 6 images are reference pictures in order:
     - Image 1 & Image 2 are reference pictures of "佐佐木 (Sasaki)" (中年男性，短发，神情疲惫，常穿灰色或蓝色西服套装).
     - Image 3 & Image 4 are reference pictures of "山田 (Yamada)" (超市收银员状态，戴红色头巾，枣红色中长发，穿绿白条纹超市制服).
     - Image 5 & Image 6 are reference pictures of "田山 (Tayama)" (超市后门抽烟状态，摘掉帽子，枣红色扎起来的头发（偶尔也没有），穿中性休闲服装，打很多耳钉.
2. 2 to 3 representative visual keyframes of this segment (as the subsequent images after the first 6 reference images).
3. The exact audio track of this segment (as audio).
4. The dialog transcript of this segment: "{transcript}".

【角色视觉特征与名字对照表 (Character Context)】:
为了在描述中更精准地称呼主要角色，请在描述、标签与分析中**使用以下名字代替泛称**（如“男子”、“女子”、“收银员”等）：
2. **山田 (Yamada)** / **田山 (Tayama)**：女主角。比对参考图片 3, 4, 5, 6。在超市里工作时是戴头巾、披肩中长发发型、穿绿条纹超市制服的收银员“山田”；在超市后门抽烟时是拿掉口罩、常穿中性休闲装的“田山”。如果是超市内请称呼“山田”，后门抽烟时请称呼“田山”。
3. **店长 (Store Manager)**：超市店长，黑发女子，带红框眼镜。

Please perform a joint spatial-temporal and semantic analysis of the action, style, movement, and emotion of this segment, mapping visual and dialogue cues to the characters above.
You MUST output a single valid JSON object following this EXACT schema, with NO markdown formatting, NO backticks, and NO additional text.
IMPORTANT: All the text fields in the output JSON (summary, visual_style, emotion_flow, and tags) MUST be in Chinese (中文):
{{
  "summary": "一句或两句话对场景动作的中文描述，结合对白和画面线索（必须使用上述对照表中的角色名字代替泛称）。",
  "tags": ["中文标签1", "中文标签2", "中文标签3"],
  "visual_style": "对画面光线、色调、氛围的中文描述（例如：霓虹光影，阴雨暗色调，温馨明亮房间）。",
  "motion_intensity": "low", "medium", or "high" (strictly choose one of these three),
  "key_objects": ["中文物体/道具1", "中文物体/道具2"],
  "emotion_flow": "对画面与对话传达的中文情绪波动的描述（例如：沮丧转温馨，中性，紧张，浪漫）。",
  "mad_score": 1到10的整数，评估该片段在 AMV/MAD 二次创作剪辑中的"素材吸引力": 10=极强情感张力（特写哭泣/深情凝视/愤怒爆发）或极强视觉冲击（雨中奔跑/高速追逐/戏剧光效）; 5-7=有一定内容（日常对话/人物互动/有角色有情节）; 1-3=平淡过场或空境（无主体的天空草地/大面积静态背景/无角色无情节）,
  "scene_type": strictly one of: "action" (高动能动作：奔跑/打斗/极速移动), "emotional" (人物情感特写：哭泣/深情/愤怒), "atmospheric" (氛围空镜：天空/草地/夕阳/雨景/烟雾/无主体场景), "dialogue" (人物日常对话/说话/互动), "transition" (黑屏/淡出/无内容过场)
}}
"""
    parts.append({"text": prompt})
    return {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }


def call_gemini_multimodal(payload, api_key, max_retries=3):
    import time as _time
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                res_data = json.loads(response.read().decode("utf-8"))
            if "candidates" not in res_data or not res_data["candidates"]:
                # Log the full response so we can see block reason / safety ratings
                print(f"[WARN] Gemini returned no candidates. Full response: {json.dumps(res_data, ensure_ascii=False, indent=2)}")
                raise KeyError("candidates")
            text = res_data["candidates"][0]["content"]["parts"][0]["text"]
            return text
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            err_msg = f"HTTP {e.code}: {body[:500]}"
            if attempt < max_retries:
                wait = 2 ** attempt
                print(f"[WARN] Gemini attempt {attempt}/{max_retries} failed: {err_msg}. Retrying in {wait}s...")
                _time.sleep(wait)
            else:
                print(f"[ERROR] Gemini request failed after {max_retries} attempts: {err_msg}")
                return None
        except Exception as e:
            if attempt < max_retries:
                wait = 2 ** attempt
                print(f"[WARN] Gemini attempt {attempt}/{max_retries} failed: {e}. Retrying in {wait}s...")
                _time.sleep(wait)
            else:
                print(f"[ERROR] Gemini request failed after {max_retries} attempts: {e}")
                return None


def find_reusable_segment(cursor, is_op, is_ed, relative_start):
    if not (is_op or is_ed):
        return None
    try:
        if is_op:
            cursor.execute("""
            SELECT s.summary, s.tags, s.visual_style, s.motion_intensity, s.key_objects, s.emotion_flow
            FROM video_segments s
            JOIN (
                SELECT video_id, MIN(start_time) as op_start 
                FROM video_segments 
                WHERE is_op = 1 
                GROUP BY video_id
            ) v ON s.video_id = v.video_id
            WHERE s.is_op = 1 AND abs((s.start_time - v.op_start) - ?) < 1.5
            LIMIT 1
            """, (relative_start,))
        else:
            cursor.execute("""
            SELECT s.summary, s.tags, s.visual_style, s.motion_intensity, s.key_objects, s.emotion_flow
            FROM video_segments s
            JOIN (
                SELECT video_id, MIN(start_time) as ed_start 
                FROM video_segments 
                WHERE is_ed = 1 
                GROUP BY video_id
            ) v ON s.video_id = v.video_id
            WHERE s.is_ed = 1 AND abs((s.start_time - v.ed_start) - ?) < 1.5
            LIMIT 1
            """, (relative_start,))
            
        row = cursor.fetchone()
        if row:
            return {
                "summary": row[0],
                "tags": row[1],
                "visual_style": row[2],
                "motion_intensity": row[3],
                "key_objects": row[4],
                "emotion_flow": row[5]
            }
    except Exception as e:
        print(f"[ERROR] Failed to query reusable segment: {e}")
    return None


def annotate_video_segments(video_id, video_path, extractor, db_path="data/metadata.db"):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    print(f"  [Segments] Slicing video ID {video_id} into semantic segments...")
    segments = slice_video_into_segments(video_id, db_path)
    if not segments:
        print(f"  [Segments] No segments sliced for video ID {video_id}.")
        return
        
    print(f"  [Segments] Sliced into {len(segments)} segments.")
    
    op_keywords = ["心臓こじ开けて", "さらっと食べて", "撬开心脏", "平静食用之", "心臓こじ開けて"]
    ed_keywords = ["どうでもいい流な夜", "どうでもいいような夜", "无所谓的夜晚", "响めき煌めき", "伴着回响与璀璨", "どうでもいい流な夜", "どうでもいいような夜", "響めき煌めき"]
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Delete existing segments to prevent duplicate records
    cursor.execute("DELETE FROM video_segments WHERE video_id = ?", (video_id,))
    conn.commit()
    
    cursor.execute("SELECT start_time, text FROM transcripts WHERE video_id = ? ORDER BY start_time", (video_id,))
    transcripts = cursor.fetchall()
    
    op_start = None
    ed_start = None
    for t_start, t_text in transcripts:
        if op_start is None and any(kw in t_text for kw in op_keywords):
            op_start = t_start
        if ed_start is None and any(kw in t_text for kw in ed_keywords):
            ed_start = t_start
            
    api_key = get_gemini_api_key()
    has_aud = has_audio(video_path)
    
    os.makedirs("data/audio_cache", exist_ok=True)
    
    # Step 1: Identify which segments can reuse OP/ED cache
    segments_to_process = [] # list of (index, seg, relative_start, is_op, is_ed)
    segments_reused = {}     # index -> reused data
    
    for i, seg in enumerate(segments):
        start_time = seg["start_time"]
        end_time = seg["end_time"]
        mid = (start_time + end_time) / 2.0
        
        is_op = 0
        is_ed = 0
        relative_start = 0.0
        
        if op_start is not None and op_start <= mid <= op_start + 92.0:
            is_op = 1
            relative_start = start_time - op_start
        elif ed_start is not None and ed_start <= mid <= ed_start + 92.0:
            is_ed = 1
            relative_start = start_time - ed_start
            
        reused = find_reusable_segment(cursor, is_op, is_ed, relative_start)
        if reused:
            segments_reused[i] = reused
        else:
            segments_to_process.append((i, seg, relative_start, is_op, is_ed))
            
    conn.close() # Close DB connection for now, we will reopen it for final sequential inserts
    
    print(f"  [Segments] OP/ED Cache reused: {len(segments_reused)} segments. Need Gemini: {len(segments_to_process)} segments.")
    
    # Step 2: Define worker function for Gemini call
    def worker(item):
        idx, seg, rel_start, is_op, is_ed = item
        start_time = seg["start_time"]
        end_time = seg["end_time"]
        transcript = seg["transcript"]
        keyframes = seg["keyframes"]
        
        # default placeholder values
        res_data = {
            "summary": f"Segment {start_time:.1f}s - {end_time:.1f}s",
            "tags": "[]",
            "visual_style": "Unknown",
            "motion_intensity": "medium",
            "key_objects": "[]",
            "emotion_flow": "neutral",
            "mad_score": 5,
            "scene_type": "dialogue"
        }
        
        if not api_key:
            return idx, res_data
            
        audio_snippet_path = os.path.join("data/audio_cache", f"temp_{video_id}_{start_time:.1f}_{end_time:.1f}.mp3")
        extracted = False
        if has_aud:
            # FFmpeg extraction is thread-safe as each thread writes to a unique path
            extracted = extract_audio_snippet(video_path, start_time, end_time, audio_snippet_path)
            
        payload = build_gemini_payload(start_time, end_time, transcript, keyframes, audio_snippet_path if extracted else None)
        gemini_res = call_gemini_multimodal(payload, api_key)
        
        if extracted and os.path.exists(audio_snippet_path):
            try:
                os.remove(audio_snippet_path)
            except OSError:
                pass
                
        if gemini_res:
            try:
                cleaned_res = gemini_res.strip()
                if cleaned_res.startswith("```json"):
                    cleaned_res = cleaned_res.split("```json", 1)[1]
                if cleaned_res.endswith("```"):
                    cleaned_res = cleaned_res.rsplit("```", 1)[0]
                cleaned_res = cleaned_res.strip()
                
                data = json.loads(cleaned_res)
                res_data["summary"] = data.get("summary", "")
                res_data["tags"] = json.dumps(data.get("tags", []))
                res_data["visual_style"] = data.get("visual_style", "")
                res_data["motion_intensity"] = data.get("motion_intensity", "medium")
                res_data["key_objects"] = json.dumps(data.get("key_objects", []))
                res_data["emotion_flow"] = data.get("emotion_flow", "")
                res_data["mad_score"] = int(data.get("mad_score", 5))
                res_data["scene_type"] = data.get("scene_type", "dialogue")
            except Exception as e:
                print(f"    [Segments] Failed to parse Gemini JSON for segment {start_time:.1f}s-{end_time:.1f}s: {e}")
        
        return idx, res_data

    # Step 3: Run workers in thread pool
    results_map = {}
    if segments_to_process:
        max_workers = int(os.environ.get("GEMINI_MAX_WORKERS", "24"))
        print(f"  [Segments] Launching thread pool with {max_workers} workers for Gemini API calls...")
        # Configurable concurrency, defaulting to 24 workers (ultra high performance)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(worker, item): item for item in segments_to_process}
            completed_count = 0
            for fut in as_completed(futures):
                idx, res_data = fut.result()
                results_map[idx] = res_data
                completed_count += 1
                seg_time = segments[idx]["start_time"]
                # Print progress unbuffered (explicit flush)
                sys.stdout.write(f"    [Segments] Finished {completed_count}/{len(segments_to_process)} (Segment at {seg_time:.1f}s).\n")
                sys.stdout.flush()
                
    # Step 4: Write all results sequentially to SQLite
    print(f"  [Segments] Saving all segment metadata to database...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # We must ensure we insert the segments in the correct original order (i from 0 to len(segments)-1)
    for i, seg in enumerate(segments):
        start_time = seg["start_time"]
        end_time = seg["end_time"]
        transcript = seg["transcript"]
        
        is_op = 0
        is_ed = 0
        mid = (start_time + end_time) / 2.0
        if op_start is not None and op_start <= mid <= op_start + 92.0:
            is_op = 1
        elif ed_start is not None and ed_start <= mid <= ed_start + 92.0:
            is_ed = 1
            
        if i in segments_reused:
            data = segments_reused[i]
            summary = data["summary"]
            tags = data["tags"]
            visual_style = data["visual_style"]
            motion_intensity = data["motion_intensity"]
            key_objects = data["key_objects"]
            emotion_flow = data["emotion_flow"]
            mad_score = data.get("mad_score", 5)
            scene_type = data.get("scene_type", "dialogue")
        else:
            data = results_map.get(i)
            if data:
                summary = data["summary"]
                tags = data["tags"]
                visual_style = data["visual_style"]
                motion_intensity = data["motion_intensity"]
                key_objects = data["key_objects"]
                emotion_flow = data["emotion_flow"]
                mad_score = data.get("mad_score", 5)
                scene_type = data.get("scene_type", "dialogue")
            else:
                summary = f"Segment {start_time:.1f}s - {end_time:.1f}s"
                tags = "[]"
                visual_style = "Unknown"
                motion_intensity = "medium"
                key_objects = "[]"
                emotion_flow = "neutral"
                mad_score = 5
                scene_type = "dialogue"
                
        cursor.execute("""
        INSERT INTO video_segments (
            video_id, start_time, end_time, summary, tags, visual_style, 
            motion_intensity, key_objects, emotion_flow, is_op, is_ed, transcript,
            mad_score, scene_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            video_id, start_time, end_time, summary, tags, visual_style,
            motion_intensity, key_objects, emotion_flow, is_op, is_ed, transcript,
            mad_score, scene_type
        ))
        
    conn.commit()
    conn.close()
    print(f"  [Segments] Successfully annotated segments for video ID {video_id}.")
