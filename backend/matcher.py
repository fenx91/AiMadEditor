import sqlite3
import numpy as np

# Find match candidates for a given lyric text
def find_candidates(lyric_text, extractor, db_path="data/metadata.db", limit=10, motion_preference="any"):
    # motion_preference can be: "any", "low", "medium", "high"
    
    # 1. Get embedding for the lyric text
    text_emb = extractor.get_text_embedding(lyric_text)
    if np.all(text_emb == 0.0):
        # Fallback if text embedding extraction failed
        text_emb = np.zeros(512, dtype=np.float32)
        
    # 2. Query all keyframes from SQLite
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT kf.id, kf.video_id, kf.timestamp, kf.frame_path, kf.embedding, kf.motion_score, 
           v.original_path, v.proxy_path, v.duration
    FROM keyframes kf
    JOIN videos v ON kf.video_id = v.id
    """)
    
    rows = cursor.fetchall()
    conn.close()
    
    candidates = []
    for row in rows:
        kf_id, video_id, timestamp, frame_path, emb_blob, motion_score, original_path, proxy_path, duration = row
        
        # Load embedding from blob
        if not emb_blob:
            continue
        kf_emb = np.frombuffer(emb_blob, dtype=np.float32)
        
        # Compute cosine similarity (both are already L2 normalized, so it's just dot product)
        similarity = float(np.dot(text_emb, kf_emb))
        
        # Adjust score based on motion preference
        # motion_score is roughly 0 to 10 (mean absolute pixel diff)
        # Low motion: < 1.5, Medium: 1.5 - 3.5, High: > 3.5
        motion_factor = 1.0
        if motion_preference == "low":
            # Penalize high motion
            if motion_score > 3.0:
                motion_factor = 0.5
            elif motion_score < 1.5:
                motion_factor = 1.2
        elif motion_preference == "high":
            # Penalize low motion
            if motion_score < 1.5:
                motion_factor = 0.3
            elif motion_score > 3.5:
                motion_factor = 1.3
        elif motion_preference == "medium":
            # Favor middle ground
            if 1.5 <= motion_score <= 3.5:
                motion_factor = 1.2
            else:
                motion_factor = 0.7
                
        final_score = similarity * motion_factor
        
        # Format candidate
        # We also need relative path for frontend Web UI
        rel_proxy_path = os.path.relpath(proxy_path, "backend/static") if "backend/static" in proxy_path else proxy_path
        # If proxy_path starts with data/proxies, we can serve data/ under FastAPI /data mount
        # Let's make sure it's accessible. We will write a standard routing for serving files.
        
        candidates.append({
            "keyframe_id": kf_id,
            "video_id": video_id,
            "video_path": original_path,
            "proxy_path": proxy_path,
            "timestamp": timestamp,
            "frame_path": frame_path,
            "similarity": similarity,
            "motion_score": motion_score,
            "score": final_score,
            "duration": duration
        })
        
    # Sort candidates by final score descending
    candidates = sorted(candidates, key=lambda x: x["score"], reverse=True)
    
    # Deduplicate candidates that are very close to each other in the same video
    # e.g., within 2 seconds of each other, keep only the highest scoring one
    deduped = []
    seen_videos_times = {} # video_id -> list of timestamps
    
    for cand in candidates:
        vid = cand["video_id"]
        ts = cand["timestamp"]
        
        is_duplicate = False
        if vid in seen_videos_times:
            for prev_ts in seen_videos_times[vid]:
                if abs(prev_ts - ts) < 2.0:
                    is_duplicate = True
                    break
                    
        if not is_duplicate:
            deduped.append(cand)
            if vid not in seen_videos_times:
                seen_videos_times[vid] = []
            seen_videos_times[vid].append(ts)
            
        if len(deduped) >= limit:
            break
            
    return deduped
