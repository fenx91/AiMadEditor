import os
import sqlite3
import numpy as np
import hashlib
import json
import urllib.request
import urllib.error

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

def call_gemini(prompt: str, response_json: bool = False) -> str:
    api_key = get_gemini_api_key()
    if not api_key:
        print("[WARNING] GOOGLE_API_KEY not found. Skipping Gemini context match.")
        return ""
        
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
        with urllib.request.urlopen(req, timeout=90) as response:
            res_data = json.loads(response.read().decode('utf-8'))
        text = res_data['candidates'][0]['content']['parts'][0]['text']
        return text
    except Exception as e:
        print(f"Gemini API call failed in matcher: {e}")
        return ""

# Find match candidates for a given lyric/prompt using Gemini's semantic understanding
def find_candidates(lyric_text, extractor, db_path="data/metadata.db", limit=5, motion_preference="any", allow_op=False, lyric="", narrative_concept="", emotional_tone=""):
    # 1. Compute query hash for caching (using prompt + motion preference + allow_op flag + narrative contexts)
    query_str = f"{lyric_text.strip()} | {motion_preference} | op={allow_op} | lyric={lyric} | concept={narrative_concept} | tone={emotional_tone}"
    query_hash = hashlib.md5(query_str.encode("utf-8")).hexdigest()
    
    # 2. Check SQLite cache
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if match_cache table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='match_cache'")
        if cursor.fetchone():
            cursor.execute("SELECT candidates_json FROM match_cache WHERE query_hash = ?", (query_hash,))
            row = cursor.fetchone()
            if row:
                conn.close()
                print(f"Match recommendations cache hit for query: '{lyric_text}'")
                return json.loads(row[0])
        conn.close()
    except Exception as e:
        print(f"Error reading match cache: {e}")

    print(f"Match cache miss. Running Gemini Context-aware Match for query: '{lyric_text}'")
    
    # 3. Retrieve all video segments from DB
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Filter out OP/ED segments unless this is the first MAD slot (allow_op=True)
        # Pre-filter: only keep segments with mad_score >= 6
        if allow_op:
            cursor.execute("""
                SELECT s.id, s.video_id, s.start_time, s.end_time, s.summary, s.tags, s.visual_style, s.motion_intensity, s.transcript,
                       v.original_path, v.proxy_path, v.duration,
                       COALESCE(s.mad_score, 5), COALESCE(s.scene_type, 'dialogue')
                 FROM video_segments s
                 JOIN videos v ON s.video_id = v.id
                 WHERE s.is_ed = 0 AND COALESCE(s.mad_score, 5) >= 6
            """)
        else:
            cursor.execute("""
                SELECT s.id, s.video_id, s.start_time, s.end_time, s.summary, s.tags, s.visual_style, s.motion_intensity, s.transcript,
                       v.original_path, v.proxy_path, v.duration,
                       COALESCE(s.mad_score, 5), COALESCE(s.scene_type, 'dialogue')
                 FROM video_segments s
                 JOIN videos v ON s.video_id = v.id
                 WHERE s.is_op = 0 AND s.is_ed = 0 AND COALESCE(s.mad_score, 5) >= 6
            """)
        rows = cursor.fetchall()
        conn.close()
    except Exception as e:
        print(f"Database error in matcher: {e}")
        return []
        
    if not rows:
        print("No video segments indexed in database.")
        return []
        
    # 4. Format segments for Gemini context
    segment_pool = []
    for r in rows:
        seg_id, video_id, start_time, end_time, summary, tags, visual_style, motion_intensity, transcript, original_path, proxy_path, duration, mad_score, scene_type = r
        video_name = os.path.basename(original_path)
        
        segment_pool.append({
            "id": seg_id,
            "video": video_name,
            "range": f"{start_time:.1f}s-{end_time:.1f}s",
            "summary": summary,
            "style": visual_style,
            "motion": motion_intensity,
            "transcript": transcript or "",
            "mad_score": mad_score,
            "scene_type": scene_type
        })
        
    # 5. Ask Gemini to match
    pool_str = json.dumps(segment_pool, ensure_ascii=False, indent=1)
    
    context_str = ""
    if lyric:
        context_str += f"\nSong Lyric (Text): \"{lyric}\""
    if narrative_concept:
        context_str += f"\nNarrative Concept/Storytelling Goal: \"{narrative_concept}\""
    if emotional_tone:
        context_str += f"\nEmotional Tone: \"{emotional_tone}\""

    prompt = f"""
You are an expert video assistant editor. Your task is to match a storyboard's "Visual Prompt" to the most contextually relevant video segments in our library.

Storyboard Visual Prompt (Goal):
"{lyric_text}"{context_str}

Available Video Segments in our library:
{pool_str}

Please analyze the storyboard visual prompt (and any accompanying lyrics/narrative context) and find the top 5 video segments that are the most contextually, narratively, and visually appropriate.
Pay special attention to:
1. Matching characters (e.g. Sasaki, Tayama, Yamada), actions, emotions, and settings between the visual prompt and the segment summaries/styles.
2. CRITICAL DIALOGUE & TRANSCRIPT ALIGNMENT: If a segment has a non-empty "transcript" (dialogue), you MUST carefully evaluate its semantic alignment with the storyboard's narrative concept and song lyric.
   - We want the character's spoken dialogue to match the story of this section or the meaning of the lyrics as closely as possible.
   - For example, if the narrative concept involves "mutual support" or "healing", prioritize segments where the transcript shows characters speaking lines of comfort, care, or connection.
   - If the song lyric expresses a specific sentiment (e.g. "I want to see you", "don't leave", "thank you"), prioritize segments where the transcript has matching dialogue (e.g. expressing a desire to meet, asking someone to stay, or saying thanks).
   - If the dialogue transcript perfectly mirrors or complements the narrative/lyrics, rank it at the top of the candidates, even if the visual background description isn't a 100% exact match, because matching spoken lines to the song's story creates a far more powerful and cinematic AMV/MAD.
   - Avoid daily trivia or unrelated banter transcripts unless they specifically fit the section's narrative.
3. When multiple segments are visually/semantically similar, prefer segments with a higher mad_score (higher = more visually engaging material).
4. If the visual prompt calls for a calm, wide, or transitional shot (e.g. sky, landscape, opening scene), it is acceptable to select atmospheric (scene_type=atmospheric) segments even with lower mad_scores.

You MUST output strictly a JSON array of segment IDs representing the top matches in order of best match first:
[id1, id2, id3, id4, id5]

Strictly return the JSON array, with no markdown tags (like ```json), no backticks, and no extra text.
"""
    
    gemini_res = call_gemini(prompt, response_json=True)
    
    matched_ids = []
    if gemini_res:
        try:
            cleaned_res = gemini_res.strip()
            if cleaned_res.startswith("```json"):
                cleaned_res = cleaned_res.split("```json", 1)[1]
            if cleaned_res.endswith("```"):
                cleaned_res = cleaned_res.rsplit("```", 1)[0]
            cleaned_res = cleaned_res.strip()
            
            matched_ids = json.loads(cleaned_res)
        except Exception as parse_err:
            print(f"Failed to parse matching results from Gemini: {parse_err}. Raw: {gemini_res}")
        
    if not matched_ids or not isinstance(matched_ids, list):
        print("Gemini context matching returned empty or invalid results. Falling back to first few segments.")
        matched_ids = [r[0] for r in rows[:limit]]
        
    # 6. Map segment IDs back to candidate formats expected by app.py
    candidates = []
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    for rank, seg_id in enumerate(matched_ids):
        # Find the segment row
        seg_row = None
        for r in rows:
            if r[0] == seg_id:
                seg_row = r
                break
        if not seg_row:
            continue
            
        seg_id, video_id, start_time, end_time, summary, tags, visual_style, motion_intensity, transcript, original_path, proxy_path, duration, mad_score, scene_type = seg_row
        
        # Calculate segment mid-point
        mid_time = (start_time + end_time) / 2.0
        
        # Find the closest keyframe to the mid-point of this segment
        cursor.execute("""
            SELECT id, frame_path, motion_score 
            FROM keyframes 
            WHERE video_id = ? 
            ORDER BY abs(timestamp - ?) ASC 
            LIMIT 1
        """, (video_id, mid_time))
        kf_row = cursor.fetchone()
        
        if kf_row:
            kf_id, frame_path, motion_score = kf_row
        else:
            kf_id = 9999 + seg_id
            frame_path = ""
            motion_score = 0.0
            
        score = 100.0 - rank * 10.0  # e.g., 100, 90, 80, 70, 60
        
        candidates.append({
            "keyframe_id": kf_id,
            "video_id": video_id,
            "video_path": original_path,
            "proxy_path": proxy_path,
            "timestamp": mid_time,
            "frame_path": frame_path,
            "similarity": 1.0,
            "motion_score": motion_score,
            "score": score,
            "duration": duration,
            "transcript_text": transcript or "",
            "transcript_similarity": 1.0
        })
        
    conn.close()
    
    # 7. Write to SQLite cache
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='match_cache'")
        if cursor.fetchone():
            cursor.execute("INSERT OR REPLACE INTO match_cache (query_hash, candidates_json) VALUES (?, ?)", (query_hash, json.dumps(candidates)))
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error saving match cache: {e}")
        
    print(f"Successfully matched and cached {len(candidates)} candidates using Gemini Context.")
    return candidates

def find_candidates_batch(items, db_path="data/metadata.db", allow_op_indices=None):
    """
    Find match candidates for a list of items using Gemini's semantic understanding.
    Input format:
    items = [
        {"index": int, "lyric_text": str, "motion_preference": str},
        ...
    ]
    allow_op_indices: set/list of item indices that are allowed to include OP scenes (e.g. {0} for first slot).
    Returns a dict mapping index (int) to a list of candidates.
    """
    results = {}
    missed_items = []
    
    # 1. Connect to DB to check cache
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if match_cache table exists
        has_cache_table = False
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='match_cache'")
        if cursor.fetchone():
            has_cache_table = True
            
        for item in items:
            idx = item["index"]
            lyric_text = item["lyric_text"]
            motion_pref = item.get("motion_preference", "any")
            lyric = item.get("lyric", "")
            concept = item.get("narrative_concept", "")
            tone = item.get("emotional_tone", "")
            
            query_str = f"{lyric_text.strip()} | {motion_pref} | lyric={lyric} | concept={concept} | tone={tone}"
            query_hash = hashlib.md5(query_str.encode("utf-8")).hexdigest()
            
            cached = False
            if has_cache_table:
                cursor.execute("SELECT candidates_json FROM match_cache WHERE query_hash = ?", (query_hash,))
                row = cursor.fetchone()
                if row:
                    results[idx] = json.loads(row[0])
                    cached = True
                    print(f"Match recommendations cache hit for query index {idx}: '{lyric_text}'")
            
            if not cached:
                missed_items.append({
                    "index": idx,
                    "lyric_text": lyric_text,
                    "motion_preference": motion_pref,
                    "hash": query_hash,
                    "lyric": lyric,
                    "narrative_concept": concept,
                    "emotional_tone": tone
                })
                
        conn.close()
    except Exception as e:
        print(f"Error checking match cache in batch: {e}")
        # In case of DB error, all items are considered missed
        for item in items:
            lyric_text = item["lyric_text"]
            motion_pref = item.get("motion_preference", "any")
            lyric = item.get("lyric", "")
            concept = item.get("narrative_concept", "")
            tone = item.get("emotional_tone", "")
            query_str = f"{lyric_text.strip()} | {motion_pref} | lyric={lyric} | concept={concept} | tone={tone}"
            query_hash = hashlib.md5(query_str.encode("utf-8")).hexdigest()
            missed_items.append({
                "index": item["index"],
                "lyric_text": lyric_text,
                "motion_preference": motion_pref,
                "hash": query_hash,
                "lyric": lyric,
                "narrative_concept": concept,
                "emotional_tone": tone
            })

    # 2. If there are missed items, query video segments and send batch request to Gemini
    if missed_items:
        print(f"Batch Match cache miss for {len(missed_items)} items. Running Gemini Context-aware Match.")
        
        # Retrieve all video segments from DB (fetch is_op/is_ed to filter per-slot)
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.id, s.video_id, s.start_time, s.end_time, s.summary, s.tags, s.visual_style, s.motion_intensity, s.transcript,
                       v.original_path, v.proxy_path, v.duration,
                       COALESCE(s.mad_score, 5), COALESCE(s.scene_type, 'dialogue'),
                       s.is_op, s.is_ed
                FROM video_segments s
                JOIN videos v ON s.video_id = v.id
                WHERE COALESCE(s.mad_score, 5) >= 6
            """)
            rows = cursor.fetchall()
            conn.close()
        except Exception as e:
            print(f"Database error retrieving segments in batch matcher: {e}")
            rows = []
            
        if not rows:
            print("No video segments indexed in database.")
            # Fallback for all missed items
            for item in missed_items:
                results[item["index"]] = []
        else:
            # Build segment pools.
            # allow_op_indices controls which slots can use OP scenes.
            # We always exclude ED scenes entirely.
            _allow_op_set = set(allow_op_indices) if allow_op_indices else set()
            any_slot_allows_op = bool(_allow_op_set)

            # Track which segment IDs are OP scenes (for post-match filtering)
            op_segment_ids = set()
            segment_pool = []
            for r in rows:
                seg_id, video_id, start_time, end_time, summary, tags, visual_style, motion_intensity, transcript, original_path, proxy_path, duration, mad_score, scene_type, is_op, is_ed = r
                # Always skip ED scenes
                if is_ed:
                    continue
                # Track OP scenes
                if is_op:
                    op_segment_ids.add(seg_id)
                    # Only include OP scenes in pool if at least one slot allows it
                    if not any_slot_allows_op:
                        continue
                video_name = os.path.basename(original_path)
                segment_pool.append({
                    "id": seg_id,
                    "video": video_name,
                    "range": f"{start_time:.1f}s-{end_time:.1f}s",
                    "summary": summary,
                    "style": visual_style,
                    "motion": motion_intensity,
                    "transcript": transcript or "",
                    "mad_score": mad_score,
                    "scene_type": scene_type
                })
            
            pool_str = json.dumps(segment_pool, ensure_ascii=False, indent=1)
            
            storyboard_lines = []
            for item in missed_items:
                idx = item["index"]
                lt = item["lyric_text"]
                ly = item.get("lyric", "")
                nc = item.get("narrative_concept", "")
                et = item.get("emotional_tone", "")
                details = []
                if ly:
                    details.append(f"Lyric: \"{ly}\"")
                if nc:
                    details.append(f"Narrative Concept: \"{nc}\"")
                if et:
                    details.append(f"Emotional Tone: \"{et}\"")
                if details:
                    storyboard_lines.append(f"- Index {idx}: \"{lt}\" ({'; '.join(details)})")
                else:
                    storyboard_lines.append(f"- Index {idx}: \"{lt}\"")
            missed_prompts_str = "\n".join(storyboard_lines)
            
            prompt = f"""
You are an expert video assistant editor. Your task is to match multiple storyboard visual prompts to the most contextually relevant video segments in our library.

Available Video Segments in our library:
{pool_str}

Storyboards to match (with lyrics, narrative context, and emotional tones):
{missed_prompts_str}

Please analyze each storyboard visual prompt and find the top 5 video segments that are the most contextually, narratively, and visually appropriate for it.
Pay special attention to:
1. Matching characters (e.g. Sasaki, Tayama, Yamada), actions, emotions, and settings between the visual prompt and the segment summaries/styles.
2. CRITICAL DIALOGUE & TRANSCRIPT ALIGNMENT: If a segment has a non-empty "transcript" (dialogue), you MUST carefully evaluate its semantic alignment with the storyboard's narrative concept and song lyric.
   - We want the character's spoken dialogue to match the story of this section or the meaning of the lyrics as closely as possible.
   - For example, if the narrative concept involves "mutual support" or "healing", prioritize segments where the transcript shows characters speaking lines of comfort, care, or connection.
   - If the song lyric expresses a specific sentiment (e.g. "I want to see you", "don't leave", "thank you"), prioritize segments where the transcript has matching dialogue (e.g. expressing a desire to meet, asking someone to stay, or saying thanks).
   - If the dialogue transcript perfectly mirrors or complements the narrative/lyrics, rank it at the top of the candidates, even if the visual background description isn't a 100% exact match, because matching spoken lines to the song's story creates a far more powerful and cinematic AMV/MAD.
   - Avoid daily trivia or unrelated banter transcripts unless they specifically fit the section's narrative.
3. When multiple segments are visually/semantically similar, prefer segments with a higher mad_score (higher = more visually engaging material).
4. If a storyboard calls for a calm, wide, or transitional shot, it is acceptable to select atmospheric (scene_type=atmospheric) segments even with lower mad_scores.

You MUST output strictly a JSON object where the keys are the storyboard indexes (as strings) and the values are JSON arrays of segment IDs representing the top matches in order of best match first:
{{
  "index_num": [id1, id2, id3, id4, id5],
  ...
}}

Strictly return the JSON object, with no markdown tags (like ```json), no backticks, and no extra text.
"""
            
            gemini_res = call_gemini(prompt, response_json=True)
            
            batch_matched = {}
            if gemini_res:
                try:
                    cleaned_res = gemini_res.strip()
                    if cleaned_res.startswith("```json"):
                        cleaned_res = cleaned_res.split("```json", 1)[1]
                    if cleaned_res.endswith("```"):
                        cleaned_res = cleaned_res.rsplit("```", 1)[0]
                    cleaned_res = cleaned_res.strip()
                    
                    batch_matched = json.loads(cleaned_res)
                except Exception as parse_err:
                    print(f"Failed to parse batch matching results from Gemini: {parse_err}. Raw: {gemini_res}")
            
            # Map results and write to cache
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # Check cache table again
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='match_cache'")
                has_cache_table = bool(cursor.fetchone())
                
                for item in missed_items:
                    idx = item["index"]
                    query_hash = item["hash"]
                    
                    # Look up matched IDs for this index. Note that JSON keys are strings
                    matched_ids = batch_matched.get(str(idx))
                    if not matched_ids or not isinstance(matched_ids, list):
                        # Fallback to first few non-OP/non-ED segments
                        print(f"Index {idx} has no valid matched IDs in Gemini response. Using fallback.")
                        matched_ids = [r[0] for r in rows[:5] if not r[15]]

                    # Post-match OP filter: if this slot is NOT allowed to use OP scenes,
                    # strip any OP segment IDs that Gemini may have returned
                    if idx not in _allow_op_set:
                        matched_ids = [sid for sid in matched_ids if sid not in op_segment_ids]
                    
                    candidates = []
                    for rank, seg_id in enumerate(matched_ids):
                        seg_row = None
                        for r in rows:
                            if r[0] == seg_id:
                                seg_row = r
                                break
                        if not seg_row:
                            continue
                            
                        seg_id, video_id, start_time, end_time, summary, tags, visual_style, motion_intensity, transcript, original_path, proxy_path, duration, mad_score, scene_type, is_op, is_ed = seg_row
                        mid_time = (start_time + end_time) / 2.0
                        
                        cursor.execute("""
                            SELECT id, frame_path, motion_score 
                            FROM keyframes 
                            WHERE video_id = ? 
                            ORDER BY abs(timestamp - ?) ASC 
                            LIMIT 1
                        """, (video_id, mid_time))
                        kf_row = cursor.fetchone()
                        
                        if kf_row:
                            kf_id, frame_path, motion_score = kf_row
                        else:
                            kf_id = 9999 + seg_id
                            frame_path = ""
                            motion_score = 0.0
                            
                        score = 100.0 - rank * 10.0
                        
                        candidates.append({
                            "keyframe_id": kf_id,
                            "video_id": video_id,
                            "video_path": original_path,
                            "proxy_path": proxy_path,
                            "timestamp": mid_time,
                            "frame_path": frame_path,
                            "similarity": 1.0,
                            "motion_score": motion_score,
                            "score": score,
                            "duration": duration,
                            "transcript_text": transcript or "",
                            "transcript_similarity": 1.0
                        })
                        
                    results[idx] = candidates
                    
                    # Cache the candidates
                    if has_cache_table and candidates:
                        try:
                            cursor.execute("INSERT OR REPLACE INTO match_cache (query_hash, candidates_json) VALUES (?, ?)", (query_hash, json.dumps(candidates)))
                        except Exception as cache_err:
                            print(f"Error inserting cache for query index {idx}: {cache_err}")
                
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"Error mapping or caching batch results: {e}")
                # Ensure results are populated even if DB mapping/caching fails
                for item in missed_items:
                    if item["index"] not in results:
                        results[item["index"]] = []
                        
    return results

