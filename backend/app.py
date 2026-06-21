import os
import sys
import shutil
import json
import sqlite3
import subprocess
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel
from typing import Optional, List

# Add backend directory to path if needed
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from indexer import init_db, FeatureExtractor, index_directory, index_video_file
from analyzer import analyze_music
from matcher import find_candidates

# Create required folders at module load time so StaticFiles mounts don't crash
os.makedirs("data/music", exist_ok=True)
os.makedirs("data/proxies", exist_ok=True)
os.makedirs("data/keyframes", exist_ok=True)
os.makedirs("hyperframes_template", exist_ok=True)
os.makedirs("output", exist_ok=True)

# Global variables
extractor = None
DB_PATH = "data/metadata.db"

@asynccontextmanager
async def lifespan(app: FastAPI):
    global extractor
    # Initialize SQLite database structure
    init_db(DB_PATH)
    
    # Initialize Feature Extractor (CLIP)
    try:
        extractor = FeatureExtractor()
    except Exception as e:
        print(f"Error loading Feature Extractor model: {e}")
    yield

app = FastAPI(title="AI MV Script & HyperFrames Server", lifespan=lifespan)

# Allow CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class IndexRequest(BaseModel):
    directory: str

class MatchRequest(BaseModel):
    lyric_text: str
    motion_preference: str = "any"
    limit: int = 5

class TimelineSlot(BaseModel):
    start_time: float
    end_time: float
    video_path: str
    clip_start: float
    clip_duration: float

class TrimRequest(BaseModel):
    audio_path: str
    lyric_path: Optional[str] = None
    start_time: float
    end_time: float

class RenderRequest(BaseModel):
    slots: List[TimelineSlot]
    audio_path: str

@app.get("/")
def read_root():
    # If frontend has index.html, serve it, otherwise serve a welcome message
    frontend_index = os.path.abspath("frontend/index.html")
    if os.path.exists(frontend_index):
        with open(frontend_index, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>AI MV Script Server is Running</h1><p>Frontend files not found yet.</p>")

@app.post("/api/index_videos")
def api_index_videos(req: IndexRequest):
    if not extractor:
        raise HTTPException(status_code=500, detail="CLIP model not loaded yet.")
        
    if not os.path.exists(req.directory):
        raise HTTPException(status_code=400, detail=f"Directory {req.directory} does not exist.")
        
    try:
        indexed_ids = index_directory(req.directory, extractor, DB_PATH)
        return {"status": "success", "indexed_count": len(indexed_ids), "ids": indexed_ids}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/videos")
def api_get_videos():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, original_path, proxy_path, duration, fps FROM videos")
        rows = cursor.fetchall()
        
        videos = []
        for r in rows:
            # We want to serve proxy path relative to static/mount
            proxy_rel = os.path.relpath(r[2], "data/proxies") if r[2] else ""
            videos.append({
                "id": r[0],
                "original_path": r[1],
                "proxy_url": f"/data/proxies/{os.path.basename(r[2])}" if r[2] else "",
                "duration": r[3],
                "fps": r[4]
            })
        conn.close()
        return videos
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload_music")
def api_upload_music(
    audio: UploadFile = File(...),
    lyric: Optional[UploadFile] = File(None),
    lyric_text: Optional[str] = Form(None)
):
    # Save audio file
    audio_path = os.path.join("data/music", audio.filename)
    with open(audio_path, "wb") as buffer:
        shutil.copyfileobj(audio.file, buffer)
        
    # Save lyric file if any
    lyric_path = None
    if lyric:
        lyric_path = os.path.join("data/music", lyric.filename)
        with open(lyric_path, "wb") as buffer:
            shutil.copyfileobj(lyric.file, buffer)
            
    # Analyze music
    try:
        analysis = analyze_music(audio_path, lyric_path=lyric_path, lyric_text=lyric_text)
        # Store relative file path for access
        analysis["audio_url"] = f"/data/music/{audio.filename}"
        analysis["audio_path"] = audio_path
        analysis["lyric_path"] = lyric_path
        return analysis
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/trim_music")
def api_trim_music(req: TrimRequest):
    if not os.path.exists(req.audio_path):
        raise HTTPException(status_code=400, detail=f"Audio file {req.audio_path} does not exist.")
        
    base, ext = os.path.splitext(os.path.basename(req.audio_path))
    # Remove any existing trim suffixes to prevent compounding filename lengths
    if "_trimmed_" in base:
        base = base.split("_trimmed_")[0]
        
    trimmed_filename = f"{base}_trimmed_{int(req.start_time)}_{int(req.end_time)}{ext}"
    trimmed_audio_path = os.path.join("data/music", trimmed_filename)
    
    # 1. Trim the audio file
    try:
        from analyzer import trim_audio_file, offset_lyrics, parse_lrc, parse_txt
        if not os.path.exists(trimmed_audio_path):
            trim_audio_file(req.audio_path, trimmed_audio_path, req.start_time, req.end_time)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error trimming audio: {e}")
        
    # 2. Parse and shift lyrics if available
    preparsed_lyrics = None
    if req.lyric_path and os.path.exists(req.lyric_path):
        try:
            from analyzer import analyze_audio_rhythm
            orig_info = analyze_audio_rhythm(req.audio_path)
            orig_duration = orig_info["duration"]
            
            content = None
            for encoding in ["utf-8", "gb18030", "gbk", "utf-16"]:
                try:
                    with open(req.lyric_path, "r", encoding=encoding) as f:
                        content = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            
            if content is None:
                with open(req.lyric_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    
            if req.lyric_path.lower().endswith(".lrc"):
                orig_lyrics = parse_lrc(content, orig_duration)
            else:
                orig_lyrics = parse_txt(content, orig_duration)
                
            preparsed_lyrics = offset_lyrics(orig_lyrics, req.start_time, req.end_time)
        except Exception as e:
            print(f"Error processing lyrics during trim: {e}")
            
    # 3. Analyze the trimmed audio
    try:
        analysis = analyze_music(trimmed_audio_path, preparsed_lyrics=preparsed_lyrics)
        analysis["audio_url"] = f"/data/music/{trimmed_filename}"
        analysis["audio_path"] = trimmed_audio_path
        analysis["lyric_path"] = req.lyric_path
        return analysis
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/load_test_data")
def api_load_test_data():
    import shutil
    src_mp3 = "tests/data/music/Adam Lambert - Whataya Want from Me_H.mp3"
    src_lrc = "tests/data/music/Adam Lambert - Whataya Want from Me_H.lrc"
    
    if not os.path.exists(src_mp3):
        raise HTTPException(status_code=404, detail="Test MP3 file not found.")
        
    dest_mp3 = os.path.join("data/music", os.path.basename(src_mp3))
    dest_lrc = os.path.join("data/music", os.path.basename(src_lrc))
    
    try:
        shutil.copy2(src_mp3, dest_mp3)
        if os.path.exists(src_lrc):
            shutil.copy2(src_lrc, dest_lrc)
        else:
            dest_lrc = None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to copy test files: {e}")
        
    try:
        analysis = analyze_music(dest_mp3, lyric_path=dest_lrc)
        analysis["audio_url"] = f"/data/music/{os.path.basename(src_mp3)}"
        analysis["audio_path"] = dest_mp3
        analysis["lyric_path"] = dest_lrc
        return analysis
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/match")
def api_match(req: MatchRequest):
    if not extractor:
        raise HTTPException(status_code=500, detail="CLIP model not loaded yet.")
        
    try:
        candidates = find_candidates(
            req.lyric_text, 
            extractor, 
            DB_PATH, 
            limit=req.limit, 
            motion_preference=req.motion_preference
        )
        
        # Adjust paths for Web UI display
        for cand in candidates:
            # Serve proxy and keyframe via FastAPI static files
            cand["proxy_url"] = f"/data/proxies/{os.path.basename(cand['proxy_path'])}"
            cand["frame_url"] = f"/data/keyframes/{os.path.basename(cand['frame_path'])}"
            
        return candidates
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/video_file")
def api_serve_video_file(path: str):
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"File {path} not found.")
    return FileResponse(path)

def get_high_res_render_proxy(original_path):
    base_name = os.path.splitext(os.path.basename(original_path))[0]
    proxy_dir = "data/proxies"
    os.makedirs(proxy_dir, exist_ok=True)
    render_proxy_path = os.path.join(proxy_dir, f"{base_name}_render.mp4")
    
    if os.path.exists(render_proxy_path):
        return render_proxy_path
        
    print(f"Generating high-res rendering proxy for {original_path}...")
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    
    # Try GPU NVENC with keyframe interval of 30 (GOP=30) for fast seeking
    cmd_gpu = [
        ffmpeg, "-y",
        "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
        "-i", original_path,
        "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20",
        "-g", "30", "-keyint_min", "30",
        "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k", render_proxy_path
    ]
    
    cmd_cpu = [
        ffmpeg, "-y",
        "-i", original_path,
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-g", "30", "-keyint_min", "30",
        "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k", render_proxy_path
    ]
    
    # Run GPU command
    result = subprocess.run(cmd_gpu, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print("  NVENC GPU transcode failed or not available. Falling back to CPU...")
        subprocess.run(cmd_cpu, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print("  High-res rendering proxy generated successfully with GPU NVENC.")
        
    return render_proxy_path

@app.post("/api/render")
def api_render(req: RenderRequest):
    try:
        # Save render decision list data to hyperframes template directory
        # Translate local audio path to absolute/web path
        abs_audio = os.path.abspath(req.audio_path)
        
        # Prepare slots for HyperFrames rendering
        # Clean up old temp videos in hyperframes_template (if any remain)
        for f in os.listdir("hyperframes_template"):
            if f.startswith("temp_video_") and f.endswith(".mp4"):
                try:
                    os.remove(os.path.join("hyperframes_template", f))
                except OSError:
                    pass
                    
        # Prepare slots using relative paths relative to hyperframes_template/
        # Prepare slots and hard links inside hyperframes_template/
        slots_data = []
        video_to_temp_name = {}
        
        for slot in req.slots:
            abs_video_path = os.path.abspath(slot.video_path)
            resolved_path = abs_video_path
            
            # If format is not directly supported in Chrome, map to high-res rendering proxy
            if abs_video_path.lower().endswith(('.mkv', '.avi', '.mov', '.flv')):
                resolved_path = os.path.abspath(get_high_res_render_proxy(abs_video_path))
                print(f"Mapped unsupported video format {abs_video_path} to high-res proxy {resolved_path}")
            
            # Create hard link in hyperframes_template
            if resolved_path not in video_to_temp_name:
                temp_name = f"temp_video_{len(video_to_temp_name)}.mp4"
                temp_path = os.path.join("hyperframes_template", temp_name)
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
                try:
                    os.link(resolved_path, temp_path)
                except Exception as link_err:
                    # Fallback to copy if hard link fails (e.g. cross-device)
                    print(f"Hard link failed: {link_err}. Falling back to copy...")
                    shutil.copy2(resolved_path, temp_path)
                video_to_temp_name[resolved_path] = temp_name
                
            slots_data.append({
                "startTime": slot.start_time,
                "endTime": slot.end_time,
                "videoPath": video_to_temp_name[resolved_path],
                "clipStart": slot.clip_start,
                "clipDuration": slot.clip_duration
            })
            
        render_data = {
            "slots": slots_data,
            "audioPath": abs_audio,
            "duration": req.slots[-1].end_time if req.slots else 0.0
        }
        
        # Write render data JSON inside hyperframes template directory
        with open("hyperframes_template/render_data.json", "w", encoding="utf-8") as f:
            json.dump(render_data, f, indent=2)
            
        # Copy audio file to template directory for browser testing/playing
        audio_ext = os.path.splitext(req.audio_path)[1]
        dest_audio = "hyperframes_template/audio" + audio_ext
        shutil.copy2(req.audio_path, dest_audio)
        
        # Dynamically update the index.html with the correct audio file name, video elements, and duration
        try:
            import re
            audio_filename = "audio" + audio_ext
            duration_val = req.slots[-1].end_time if req.slots else 0.0
            
            # Generate static video elements HTML
            video_tags = []
            for i, slot in enumerate(slots_data):
                slot_duration = slot["endTime"] - slot["startTime"]
                video_tags.append(
                    f'<video class="video-layer" id="video_{i}" src="{slot["videoPath"]}" data-start="{slot["startTime"]}" data-duration="{slot_duration}" preload="auto" muted></video>'
                )
            video_elements_html = "\n    ".join(video_tags)
            
            with open("hyperframes_template/index.template.html", "r", encoding="utf-8") as f:
                html_content = f.read()
                
            # Replace audio src
            html_content = re.sub(
                r'<audio id="bg-audio" src="[^"]*"',
                f'<audio id="bg-audio" src="{audio_filename}"',
                html_content
            )
            # Replace data-duration on both viewport and audio tags
            html_content = re.sub(
                r'data-duration="[^"]*"',
                f'data-duration="{duration_val}"',
                html_content
            )
            # Replace video elements placeholder
            html_content = re.sub(
                r'<!-- VIDEO_ELEMENTS_PLACEHOLDER -->',
                video_elements_html,
                html_content
            )
            
            with open("hyperframes_template/index.html", "w", encoding="utf-8") as f:
                f.write(html_content)
        except Exception as e:
            print(f"Error updating template attributes dynamically: {e}")
        
        # Call HyperFrames rendering command
        # First we verify if HyperFrames is installed and render
        # Let's write output to output/mv_output.mp4
        output_mp4 = os.path.abspath("output/mv_output.mp4")
        
        # CLI command execution: npx hyperframes render ...
        # For security and compatibility, we will prepare the command but not run it blindly.
        # HyperFrames render tool command structure:
        # npx hyperframes render <template_index_html_path> -o <output_mp4> --data <render_data_json_path>
        template_path = os.path.abspath("hyperframes_template")
        data_path = os.path.abspath("hyperframes_template/render_data.json")
        
        cmd = [
            "npx", "hyperframes", "render", template_path,
            "-o", output_mp4,
            "--data", data_path,
            "--resolution", "landscape"
        ]
        
        print(f"Executing render command: {' '.join(cmd)}")
        # Prep local node/bin to env PATH
        env = os.environ.copy()
        local_node_bin = os.path.abspath("node/bin")
        env["PATH"] = local_node_bin + os.pathsep + env.get("PATH", "")
        
        # Run render command
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            bufsize=1
        )
        
        stdout_lines = []
        if process.stdout:
            for line in process.stdout:
                print(line, end="", flush=True)
                stdout_lines.append(line)
        
        process.wait()
        returncode = process.returncode
        stdout_content = "".join(stdout_lines)
        
        if returncode != 0:
            print(f"HyperFrames render error: {stdout_content}")
            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "detail": f"Render failed: {stdout_content}",
                    "cmd": " ".join(cmd)
                }
            )
            
        return {
            "status": "success",
            "output_path": output_mp4,
            "output_url": "/output/mv_output.mp4"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Mount static files directories for media and output
app.mount("/data/proxies", StaticFiles(directory="data/proxies"), name="proxies")
app.mount("/data/keyframes", StaticFiles(directory="data/keyframes"), name="keyframes")
app.mount("/data/music", StaticFiles(directory="data/music"), name="music")
app.mount("/output", StaticFiles(directory="output"), name="output")

# Mount frontend files (assets like CSS/JS)
if os.path.exists("frontend"):
    app.mount("/assets", StaticFiles(directory="frontend"), name="assets")

# Serve rendering templates folder statically
app.mount("/hyperframes_template", StaticFiles(directory="hyperframes_template"), name="hyperframes_template")

if __name__ == "__main__":
    import uvicorn
    reload_mode = os.environ.get("RELOAD", "0") == "1"
    if reload_mode:
        print("Starting server in hot-reload mode (Note: CLIP model will reload on code changes)...")
        # Add backend directory to sys.path in reload worker processes
        uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True, reload_dirs=["backend"])
    else:
        uvicorn.run(app, host="0.0.0.0", port=8000)
