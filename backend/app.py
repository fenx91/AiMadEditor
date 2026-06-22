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
import urllib.parse

# Add backend directory to path if needed
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from indexer import init_db, FeatureExtractor, index_directory, index_video_file
from analyzer import analyze_music
from matcher import find_candidates, find_candidates_batch

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
    force_refresh: bool = False

class MatchRequest(BaseModel):
    lyric_text: str
    motion_preference: str = "any"
    limit: int = 5
    lyric: Optional[str] = ""
    narrative_concept: Optional[str] = ""
    emotional_tone: Optional[str] = ""

class BatchMatchItem(BaseModel):
    index: int
    lyric_text: str
    motion_preference: str = "any"
    lyric: Optional[str] = ""
    narrative_concept: Optional[str] = ""
    emotional_tone: Optional[str] = ""

class BatchMatchRequest(BaseModel):
    items: List[BatchMatchItem]

class TimelineSlot(BaseModel):
    start_time: float
    end_time: float
    video_path: str
    clip_start: float
    clip_duration: float
    keep_audio: Optional[bool] = False
    transcript: Optional[str] = ""

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
            headers = {
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
            return HTMLResponse(content=f.read(), headers=headers)
    return HTMLResponse("<h1>AI MV Script Server is Running</h1><p>Frontend files not found yet.</p>", headers={"Cache-Control": "no-cache"})

@app.post("/api/index_videos")
def api_index_videos(req: IndexRequest):
    if not extractor:
        raise HTTPException(status_code=500, detail="CLIP model not loaded yet.")
        
    if not os.path.exists(req.directory):
        raise HTTPException(status_code=400, detail=f"Directory {req.directory} does not exist.")
        
    try:
        indexed_ids = index_directory(req.directory, extractor, DB_PATH, req.force_refresh)
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
            proxy_url = f"/api/video_file?path={urllib.parse.quote(r[1])}" if r[1] else ""
            videos.append({
                "id": r[0],
                "original_path": r[1],
                "proxy_url": proxy_url,
                "duration": r[3],
                "fps": r[4]
            })
        conn.close()
        return videos
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/videos/{video_id}/transcripts")
def api_get_video_transcripts(video_id: int):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check if transcripts table exists to prevent crash on empty databases
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transcripts'")
        table_exists = cursor.fetchone() is not None
        if not table_exists:
            conn.close()
            return []
            
        cursor.execute("""
        SELECT id, start_time, end_time, text 
        FROM transcripts 
        WHERE video_id = ? 
        ORDER BY start_time ASC
        """, (video_id,))
        rows = cursor.fetchall()
        conn.close()
        
        transcripts = []
        for r in rows:
            transcripts.append({
                "id": r[0],
                "start_time": r[1],
                "end_time": r[2],
                "text": r[3]
            })
        return transcripts
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

class LyricLine(BaseModel):
    text: str
    start: float
    end: float

# Fixed project theme for this MAD — two workers who mutually save each other
_DEFAULT_USER_VISION = (
    "这是一首讲述两个打工人（佐佐木和田山）互相救赎的 AMV/MAD。"
    "故事从两人互不认识开始，工作的压力与疲惫让彼此 messed up，"
    "但他们 keep coming around，用陪伴和温暖悄悄疗愈对方，最终走向相互依靠。"
    "情感基调：从压抑、孤独 → 惊喜相遇 → 暧昧摩擦 → 互相治愈 → 温暖释怀。"
)

class ScriptPlanRequest(BaseModel):
    lyrics: List[LyricLine]
    user_vision: str = _DEFAULT_USER_VISION

class RegenerateLineRequest(BaseModel):
    lyric_text: str
    current_prompt: str
    user_feedback: str
    user_vision: str

def get_gemini_api_key():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    api_key = os.environ.get("GOOGLE_API_KEY")
    if api_key:
        return api_key
    # 2. Try the specific config file path
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

def call_gemini(prompt: str, response_json: bool = False) -> str:
    import urllib.request
    api_key = get_gemini_api_key()
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="Google API key not found. Please set GOOGLE_API_KEY environment variable or configure it in /home/fenxy/my_new_agent/.env"
        )
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
    
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }
    
    if response_json:
        payload["generationConfig"] = {
            "responseMimeType": "application/json"
        }
        
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode('utf-8'))
        text = res_data['candidates'][0]['content']['parts'][0]['text']
        return text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini API call failed: {str(e)}")

class RecommendVisionsRequest(BaseModel):
    lyrics: List[LyricLine]

@app.post("/api/recommend_story_visions")
def api_recommend_story_visions(req: RecommendVisionsRequest):
    try:
        import hashlib
        
        # 1. Compute lyrics MD5 hash for caching
        lyrics_text = "".join([l.text for l in req.lyrics])
        lyrics_hash = hashlib.md5(lyrics_text.encode("utf-8")).hexdigest()
        
        # 2. Check SQLite cache
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT recommendations FROM vision_cache WHERE lyrics_hash = ?", (lyrics_hash,))
        row = cursor.fetchone()
        if row:
            conn.close()
            print("Vision recommendations: Cache hit!")
            return json.loads(row[0])
            
        print("Vision recommendations: Cache miss. Gathering video library metadata...")
        
        # 3. Gather video summaries and metadata from database
        cursor.execute("SELECT original_path FROM videos LIMIT 10")
        videos = [os.path.basename(r[0]) for r in cursor.fetchall()]
        
        cursor.execute("SELECT summary, tags, visual_style FROM video_segments LIMIT 50")
        segments = cursor.fetchall()
        
        conn.close()
        
        # Format video profile context
        video_context = ""
        if videos:
            video_context += f"Indexed videos:\n" + "\n".join([f"- {v}" for v in videos]) + "\n"
        if segments:
            seg_texts = []
            for s in segments:
                tags = json.loads(s[1]) if s[1] else []
                seg_texts.append(f"Scene: {s[0]} | Style: {s[2]} | Tags: {', '.join(tags)}")
            video_context += "Visual scene highlights in database:\n" + "\n".join(seg_texts[:30])
            
        if not video_context:
            video_context = "No video segments indexed yet. Assume general anime/music video themes."
            
        # 4. Construct prompt for Gemini
        lyrics_snippet = "\n".join([f"[{l.start:.1f}s - {l.end:.1f}s] {l.text}" for l in req.lyrics[:40]])
        
        prompt = f"""
你是一个专业的音乐视频 (AMV/MAD) 导演。
我们有一首歌曲，歌词内容如下（前40行）：
{lyrics_snippet}

我们还有以下已索引的视频素材库特征信息，我们后续会检索这些素材进行卡点剪切：
{video_context}

请结合这首歌曲的歌词意境、情感起伏，与我们视频素材库中的画面风格、人物（如佐佐木、山田、田山等，如果有）、场景环境等，推荐 3 个极具故事张力和视觉契合度的“故事大纲创意/心情偏好（Story Vision Concept）”。
每一个创意需包含：
1. Title：抓眼球且精简的创意主题名称（例如：“深夜便利店的烟火气” 或 “中年社畜的落雨狂想”）。
2. Description：1 到 2 句话的镜头设计意境说明，可以直接作为用户生成分镜脚本大纲的全局 Vision 输入（例如：“以佐佐木在雨夜便利店后门的落寞与田山的温暖陪伴为核心视觉，镜头节奏缓慢随歌词低回，在副歌部分转为温暖明亮的主题，强调救赎感。”）。

请严格输出一个符合以下 JSON 格式的 JSON 数组，不要包含任何 markdown 代码块标记（如 ```json）或任何额外的多余说明文本：
[
  {{
    "title": "创意名称",
    "description": "创意构想描述（直接用于 user_vision 字段输入）"
  }},
  ...
]
"""
        
        # 5. Call Gemini
        recommendation_text = call_gemini(prompt, response_json=True)
        
        # Validate output is JSON
        try:
            cleaned_res = recommendation_text.strip()
            if cleaned_res.startswith("```json"):
                cleaned_res = cleaned_res.split("```json", 1)[1]
            if cleaned_res.endswith("```"):
                cleaned_res = cleaned_res.rsplit("```", 1)[0]
            cleaned_res = cleaned_res.strip()
            
            recommendations = json.loads(cleaned_res)
        except Exception as parse_err:
            print(f"Failed to parse recommendations JSON from Gemini: {parse_err}. Raw response: {recommendation_text}")
            raise HTTPException(status_code=500, detail="Gemini returned invalid JSON for recommendations.")
            
        # 6. Save to SQLite cache
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO vision_cache (lyrics_hash, recommendations) VALUES (?, ?)", (lyrics_hash, json.dumps(recommendations)))
        conn.commit()
        conn.close()
        
        print("Vision recommendations: Successfully cached and generated.")
        return recommendations
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/generate_script_plan")
def api_generate_script_plan(req: ScriptPlanRequest):
    import hashlib as _hashlib

    # --- 1. Compute lyrics hash for caching ---
    lyrics_key = json.dumps([l.text for l in req.lyrics], ensure_ascii=False, sort_keys=True)
    lyrics_hash = _hashlib.md5(lyrics_key.encode("utf-8")).hexdigest()

    # --- 2. Check section outline cache ---
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS script_outline_cache (
                lyrics_hash TEXT PRIMARY KEY,
                outline_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cur.execute("SELECT outline_json FROM script_outline_cache WHERE lyrics_hash = ?", (lyrics_hash,))
        cached_row = cur.fetchone()
        conn.close()
    except Exception as e:
        print(f"[ScriptPlan] Cache read error: {e}")
        cached_row = None

    if cached_row:
        print("[ScriptPlan] Section outline cache hit — using cached sections.")
        try:
            cached_sections = json.loads(cached_row[0])
            script_plan = []
            for section in cached_sections:
                section_name = section.get("section_name", "")
                mood_arc = section.get("mood_arc", "")
                for line in section.get("lines", []):
                    line["section_name"] = section_name
                    line["mood_arc"] = mood_arc
                    line["narrative_concept"] = section.get("narrative_concept", "")
                    line["visual_pacing"] = section.get("visual_pacing", "")
                    script_plan.append(line)
            script_plan.sort(key=lambda x: x.get("index", 0))
            return script_plan
        except Exception as e:
            print(f"[ScriptPlan] Failed to parse cached outline: {e}. Regenerating.")

    # --- 3. Build material library overview from DB ---
    material_overview = ""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        overview_parts = []
        for scene_type, label in [
            ("emotional", "情感特写"),
            ("atmospheric", "氛围空镜"),
            ("action", "高动能动作"),
            ("dialogue", "日常对话/互动"),
        ]:
            cur.execute("""
                SELECT summary FROM video_segments
                WHERE scene_type = ? AND mad_score >= 7
                ORDER BY mad_score DESC
                LIMIT 5
            """, (scene_type,))
            summaries = [r[0] for r in cur.fetchall() if r[0]]
            if summaries:
                bullets = "；".join(s[:50] for s in summaries)
                overview_parts.append(f"- {scene_type}（{label}）：{bullets}")
        conn.close()
        if overview_parts:
            material_overview = "【可用素材概览（请优先选用库中存在的画面类型，不要凭空生成素材中不存在的场景）】:\n" + "\n".join(overview_parts)
    except Exception as e:
        print(f"[ScriptPlan] Material overview query error: {e}")
        material_overview = ""

    # --- 4. Build and call Gemini ---
    lyrics_json = json.dumps([{"index": i, "text": l.text} for i, l in enumerate(req.lyrics)], ensure_ascii=False, indent=2)
    prompt = f"""
你是一个专业的 AMV/MAD 视频剪辑脚本导演。请根据以下音乐歌词列表、用户的创作视角以及可用素材概览，生成一份完整的分段叙事大纲。

【用户创作视角/心情偏好】:
"{req.user_vision}"

{material_overview}

【歌词列表（含行号）】:
{lyrics_json}

---
## 第一步：段落划分与叙事规划
通读全部歌词后，将其划分为若干有意义的段落（如 Verse 1 / Pre-Chorus / Chorus / Bridge / Outro 等）。
每个段落需定义：
- section_name: 段落名（如 "Verse 1", "Chorus 1"）
- mood_arc: 情绪弧线（如"压抑迷茫 -> 渴望挣扎 -> 爆发释放"）
- narrative_concept: 叙事概念，这段想讲什么故事（具体到人物/动作/场景，1-2句话）
- visual_pacing: 视觉节奏，严格选一："slow" / "normal" / "fast"

## 第二步：逐行画面生成
在每个段落的叙事框架约束下，为段落内每一句歌词生成 visual_prompt 和 motion_preference。
画面提示词必须非常具体（场景、人物、动作、氛围、色调），优先描述素材概览中实际存在的画面类型。
好例子："佐佐木坐在超市后门台阶上抽烟，神情疲惫，昏黄路灯，冷色调暗夜"
坏例子："他感到很迷茫，往事随风"
motion_preference 严格选一："low" / "medium" / "high"

---
严格输出以下格式的单一 JSON 对象，不要有任何 markdown 标记、反引号或多余文字：
{{
  "sections": [
    {{
      "section_name": "Verse 1",
      "mood_arc": "...",
      "narrative_concept": "...",
      "visual_pacing": "slow",
      "lines": [
        {{
          "index": 0,
          "lyric": "歌词内容",
          "visual_prompt": "具体画面描述",
          "motion_preference": "low",
          "emotional_tone": "情感描述"
        }}
      ]
    }}
  ]
}}
"""

    text = call_gemini(prompt, response_json=True)
    try:
        raw = json.loads(text)
        sections = raw.get("sections", [])

        # --- 5. Cache sections to SQLite ---
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO script_outline_cache (lyrics_hash, outline_json) VALUES (?, ?)",
                (lyrics_hash, json.dumps(sections, ensure_ascii=False))
            )
            conn.commit()
            conn.close()
            print("[ScriptPlan] Section outline cached successfully.")
        except Exception as e:
            print(f"[ScriptPlan] Cache write error: {e}")

        script_plan = []
        for section in sections:
            section_name = section.get("section_name", "")
            mood_arc = section.get("mood_arc", "")
            for line in section.get("lines", []):
                line["section_name"] = section_name
                line["mood_arc"] = mood_arc
                line["narrative_concept"] = section.get("narrative_concept", "")
                line["visual_pacing"] = section.get("visual_pacing", "")
                script_plan.append(line)
        script_plan.sort(key=lambda x: x.get("index", 0))
        return script_plan
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse script plan JSON: {str(e)}\nRaw response: {text}")


@app.delete("/api/script_outline_cache")
def api_clear_script_outline_cache():
    """Clear the cached section outline so the next generate_script_plan call regenerates from scratch."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM script_outline_cache")
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return {"message": f"Cleared {deleted} cached outline(s)."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/regenerate_script_line")
def api_regenerate_script_line(req: RegenerateLineRequest):
    prompt = f"""
    您是一个专业的视频剪辑脚本导演。请根据用户的反馈，重新设计单行歌词所对应的“画面视觉提示词（Visual Prompt）”与“镜头运动感”。

    整体故事视角: "{req.user_vision}"
    歌词内容: "{req.lyric_text}"
    当前画面提示词: "{req.current_prompt}"
    用户修改反馈意见: "{req.user_feedback}"

    画面描述必须非常具体，适合 CLIP 语义搜索匹配（描述具体场景、人物动作、氛围、色调）。
    运动感偏好（motion_preference）只能在 "low", "medium", "high" 中选择。

    请严格输出一个符合以下 JSON 格式 the JSON 对象：
    {{
      "visual_prompt": "重新设计的画面视觉提示词",
      "motion_preference": "low 或 medium 或 high",
      "emotional_tone": "修改后的情感起伏描述"
    }}
    """
    
    text = call_gemini(prompt, response_json=True)
    try:
        line_plan = json.loads(text)
        return line_plan
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse line plan JSON: {str(e)}\nRaw response: {text}")

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
            motion_preference=req.motion_preference,
            lyric=req.lyric,
            narrative_concept=req.narrative_concept,
            emotional_tone=req.emotional_tone
        )
        
        # Connect to DB to check for segment metadata for each candidate
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Adjust paths for Web UI display
        for cand in candidates:
            # Serve original video path as proxy_url
            cand["proxy_url"] = f"/api/video_file?path={urllib.parse.quote(cand['video_path'])}"
            cand["frame_url"] = f"/data/keyframes/{os.path.basename(cand['frame_path'])}"
            
            # Find the segment that contains the candidate timestamp
            cursor.execute("""
                SELECT start_time, end_time, summary, tags, visual_style, 
                       motion_intensity, key_objects, emotion_flow, is_op, is_ed, transcript,
                       COALESCE(mad_score, 5), COALESCE(scene_type, 'dialogue')
                FROM video_segments
                WHERE video_id = ? AND start_time <= ? AND end_time >= ?
                LIMIT 1
            """, (cand["video_id"], cand["timestamp"], cand["timestamp"]))
            seg_row = cursor.fetchone()
            if seg_row:
                cand["segment"] = {
                    "start_time": seg_row[0],
                    "end_time": seg_row[1],
                    "summary": seg_row[2],
                    "tags": json.loads(seg_row[3]) if seg_row[3] else [],
                    "visual_style": seg_row[4],
                    "motion_intensity": seg_row[5],
                    "key_objects": json.loads(seg_row[6]) if seg_row[6] else [],
                    "emotion_flow": seg_row[7],
                    "is_op": bool(seg_row[8]),
                    "is_ed": bool(seg_row[9]),
                    "transcript": seg_row[10],
                    "mad_score": seg_row[11],
                    "scene_type": seg_row[12]
                }
            else:
                cand["segment"] = None
                
        conn.close()
        return candidates
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/batch_match")
def api_batch_match(req: BatchMatchRequest):
    if not extractor:
        raise HTTPException(status_code=500, detail="CLIP model not loaded yet.")
        
    try:
        items = [
            {
                "index": item.index,
                "lyric_text": item.lyric_text,
                "motion_preference": item.motion_preference,
                "lyric": item.lyric,
                "narrative_concept": item.narrative_concept,
                "emotional_tone": item.emotional_tone
            }
            for item in req.items
        ]
        
        batch_candidates = find_candidates_batch(items, DB_PATH)
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        for idx, candidates in batch_candidates.items():
            for cand in candidates:
                cand["proxy_url"] = f"/api/video_file?path={urllib.parse.quote(cand['video_path'])}"
                cand["frame_url"] = f"/data/keyframes/{os.path.basename(cand['frame_path'])}"
                
                cursor.execute("""
                    SELECT start_time, end_time, summary, tags, visual_style, 
                           motion_intensity, key_objects, emotion_flow, is_op, is_ed, transcript,
                           COALESCE(mad_score, 5), COALESCE(scene_type, 'dialogue')
                    FROM video_segments
                    WHERE video_id = ? AND start_time <= ? AND end_time >= ?
                    LIMIT 1
                """, (cand["video_id"], cand["timestamp"], cand["timestamp"]))
                seg_row = cursor.fetchone()
                if seg_row:
                    cand["segment"] = {
                        "start_time": seg_row[0],
                        "end_time": seg_row[1],
                        "summary": seg_row[2],
                        "tags": json.loads(seg_row[3]) if seg_row[3] else [],
                        "visual_style": seg_row[4],
                        "motion_intensity": seg_row[5],
                        "key_objects": json.loads(seg_row[6]) if seg_row[6] else [],
                        "emotion_flow": seg_row[7],
                        "is_op": bool(seg_row[8]),
                        "is_ed": bool(seg_row[9]),
                        "transcript": seg_row[10],
                        "mad_score": seg_row[11],
                        "scene_type": seg_row[12]
                    }
                else:
                    cand["segment"] = None
                    
        conn.close()
        return batch_candidates
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/videos/{video_id}/segments")
def api_get_video_segments(video_id: int):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, start_time, end_time, summary, tags, visual_style, 
                   motion_intensity, key_objects, emotion_flow, is_op, is_ed, transcript
            FROM video_segments
            WHERE video_id = ?
            ORDER BY start_time
        """, (video_id,))
        rows = cursor.fetchall()
        conn.close()
        
        segments = []
        for r in rows:
            segments.append({
                "id": r[0],
                "start_time": r[1],
                "end_time": r[2],
                "summary": r[3],
                "tags": json.loads(r[4]) if r[4] else [],
                "visual_style": r[5],
                "motion_intensity": r[6],
                "key_objects": json.loads(r[7]) if r[7] else [],
                "emotion_flow": r[8],
                "is_op": bool(r[9]),
                "is_ed": bool(r[10]),
                "transcript": r[11]
            })
        return segments
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
                "clipDuration": slot.clip_duration,
                "keepAudio": slot.keep_audio,
                "transcript": slot.transcript
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
