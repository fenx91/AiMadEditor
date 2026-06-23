"""Convert matcher results into the representation consumed by the web UI."""

import json
import os
import sqlite3
import urllib.parse


def enrich_candidates(candidates, db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        for candidate in candidates:
            original_path = candidate["video_path"]
            base_name = os.path.splitext(os.path.basename(original_path))[0] if original_path else ""
            render_path = os.path.join("data/proxies", f"{base_name}_render.mp4") if base_name else ""
            target_path = render_path if render_path and os.path.exists(render_path) else candidate.get("proxy_path") or original_path
            candidate["proxy_url"] = f"/api/video_file?path={urllib.parse.quote(target_path)}"
            candidate["frame_url"] = f"/data/keyframes/{os.path.basename(candidate['frame_path'])}"
            cursor.execute("""
                SELECT start_time, end_time, summary, tags, visual_style,
                       motion_intensity, key_objects, emotion_flow, is_op, is_ed, transcript,
                       COALESCE(mad_score, 5), COALESCE(scene_type, 'dialogue')
                FROM video_segments
                WHERE video_id = ? AND start_time <= ? AND end_time >= ?
                LIMIT 1
            """, (candidate["video_id"], candidate["timestamp"], candidate["timestamp"]))
            row = cursor.fetchone()
            candidate["segment"] = _segment_dict(row) if row else None
    finally:
        conn.close()
    return candidates


def enrich_candidate_batches(candidate_batches, db_path):
    for candidates in candidate_batches.values():
        enrich_candidates(candidates, db_path)
    return candidate_batches


def _segment_dict(row):
    return {
        "start_time": row[0], "end_time": row[1], "summary": row[2],
        "tags": json.loads(row[3]) if row[3] else [], "visual_style": row[4],
        "motion_intensity": row[5], "key_objects": json.loads(row[6]) if row[6] else [],
        "emotion_flow": row[7], "is_op": bool(row[8]), "is_ed": bool(row[9]),
        "transcript": row[10], "mad_score": row[11], "scene_type": row[12],
    }
