import os
import sys
import pytest
import sqlite3
import json
import base64
from unittest.mock import MagicMock, patch

# Add directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

# Mock FeatureExtractor class so it doesn't load model
class MockFeatureExtractor:
    def __init__(self):
        self.device = "cpu"
    def get_image_embedding(self, image_path):
        import numpy as np
        return np.ones(512, dtype=np.float32)
    def get_text_embedding(self, text):
        import numpy as np
        return np.ones(512, dtype=np.float32) / 22.627

class MockTensor:
    pass

sys.modules['transformers'] = MagicMock()
mock_torch = MagicMock()
mock_torch.Tensor = MockTensor
sys.modules['torch'] = mock_torch
sys.modules['torch.nn'] = MagicMock()
sys.modules['torch.nn.functional'] = MagicMock()

import backend.indexer
backend.indexer.FeatureExtractor = MockFeatureExtractor

from backend.indexer import (
    init_db,
    slice_video_into_segments,
    extract_audio_snippet,
    build_gemini_payload,
    call_gemini_multimodal,
    find_reusable_segment,
    annotate_video_segments,
    get_gemini_api_key
)

def test_slice_video_into_segments(tmp_path):
    db_file = tmp_path / "test_segments.db"
    init_db(str(db_file))
    
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    
    # 1. Insert video
    cursor.execute("""
    INSERT INTO videos (id, original_path, proxy_path, duration, fps, asr_processed)
    VALUES (1, 'video.mp4', 'proxy.mp4', 30.0, 30.0, 1)
    """)
    
    # 2. Insert keyframes
    # We will trigger a motion cut at 10.0s (motion score 8.0)
    for ts in [0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0, 30.0]:
        motion = 8.0 if ts == 10.0 else 0.5
        cursor.execute("""
        INSERT INTO keyframes (video_id, timestamp, frame_path, embedding, motion_score)
        VALUES (1, ?, ?, ?, ?)
        """, (ts, f"frame_{ts}.jpg", sqlite3.Binary(b"emb"), motion))
        
    # 3. Insert transcripts
    # We will trigger a silence gap between 20.0s and 25.0s (gap of 5.0s > 2.5s)
    cursor.execute("""
    INSERT INTO transcripts (video_id, start_time, end_time, text, embedding)
    VALUES (1, 1.0, 9.0, 'Hello world', ?)
    """, (sqlite3.Binary(b"emb"),))
    cursor.execute("""
    INSERT INTO transcripts (video_id, start_time, end_time, text, embedding)
    VALUES (1, 11.0, 20.0, 'Sasaki is here', ?)
    """, (sqlite3.Binary(b"emb"),))
    cursor.execute("""
    INSERT INTO transcripts (video_id, start_time, end_time, text, embedding)
    VALUES (1, 25.0, 29.0, 'LoliHouse ending', ?)
    """, (sqlite3.Binary(b"emb"),))
    
    conn.commit()
    conn.close()
    
    # Run slice_video_into_segments
    segments = slice_video_into_segments(1, str(db_file))
    
    # Verify slices
    assert len(segments) >= 3
    # Check that the first boundary cut occurred near 10.0s (due to motion score 8.0)
    assert any(abs(s["end_time"] - 10.0) < 0.1 for s in segments)
    # Check that a boundary cut occurred inside the silence gap (20.0 to 25.0s, cut at ~22.5s)
    assert any(abs(s["end_time"] - 22.5) < 0.1 for s in segments)
    
    # Verify transcripts and keyframes are grouped correctly
    first_seg = segments[0]
    assert "Hello world" in first_seg["transcript"]
    assert len(first_seg["keyframes"]) > 0

def test_find_reusable_segment(tmp_path):
    db_file = tmp_path / "test_reuse.db"
    init_db(str(db_file))
    
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    
    # Insert existing annotated segment (OP, video 1)
    # This segment starts at 10.0s. Since it's the only OP segment, op_start = 10.0.
    # Its relative offset relative to v.op_start is 10.0 - 10.0 = 0.0s.
    cursor.execute("""
    INSERT INTO video_segments (
        video_id, start_time, end_time, summary, tags, visual_style, 
        motion_intensity, key_objects, emotion_flow, is_op, is_ed, transcript
    ) VALUES (1, 10.0, 20.0, 'Cached OP summary', '["op", "cool"]', 'Neon', 'high', '["cigarette"]', 'tense', 1, 0, '心臓こじ開けて')
    """)
    conn.commit()
    
    # Try finding reusable segment for a new video segment (OP, relative_start = 0.5s)
    # 0.5s is within 1.5s of the cached relative offset 0.0s, so it should match!
    reused = find_reusable_segment(cursor, is_op=1, is_ed=0, relative_start=0.5)
    assert reused is not None
    assert reused["summary"] == "Cached OP summary"
    assert reused["visual_style"] == "Neon"
    
    # Try finding reusable segment with a relative_start too far away (e.g. 5.0s)
    not_reused = find_reusable_segment(cursor, is_op=1, is_ed=0, relative_start=5.0)
    assert not_reused is None
    
    conn.close()

@patch("backend.indexer.call_gemini_multimodal")
@patch("backend.indexer.extract_audio_snippet")
def test_annotate_video_segments_mocked(mock_extract, mock_gemini, tmp_path):
    db_file = tmp_path / "test_annotate.db"
    init_db(str(db_file))
    
    # Pre-populate database
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("INSERT INTO videos (id, original_path, duration) VALUES (1, 'video.mp4', 10.0)")
    cursor.execute("INSERT INTO keyframes (video_id, timestamp, frame_path) VALUES (1, 2.0, 'f1.jpg')")
    cursor.execute("INSERT INTO keyframes (video_id, timestamp, frame_path) VALUES (1, 5.0, 'f2.jpg')")
    cursor.execute("INSERT INTO keyframes (video_id, timestamp, frame_path) VALUES (1, 8.0, 'f3.jpg')")
    cursor.execute("INSERT INTO transcripts (video_id, start_time, end_time, text) VALUES (1, 1.0, 9.0, 'Hello')")
    conn.commit()
    conn.close()
    
    mock_extract.return_value = True
    mock_gemini.return_value = """
    ```json
    {
      "summary": "Mocked summary",
      "tags": ["mock", "test"],
      "visual_style": "Dark rain",
      "motion_intensity": "low",
      "key_objects": ["umbrella"],
      "emotion_flow": "neutral"
    }
    ```
    """
    
    extractor = MockFeatureExtractor()
    with patch("backend.indexer.get_gemini_api_key", return_value="dummy_key"):
        annotate_video_segments(1, "video.mp4", extractor, str(db_file))
        
    # Check that segment was annotated in DB
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("SELECT summary, tags, visual_style, motion_intensity FROM video_segments WHERE video_id = 1")
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row[0] == "Mocked summary"
    assert "mock" in row[1]
    assert row[2] == "Dark rain"
    assert row[3] == "low"

def test_real_gemini_multimodal_inference(tmp_path):
    api_key = get_gemini_api_key()
    if not api_key:
        pytest.skip("GOOGLE_API_KEY not found in environment, skipping real Gemini multimodal test.")
        
    print("\nRunning real Gemini Multimodal Inference Test...")
    
    # 1. Create a tiny dummy 100x100 JPEG image
    img_path = tmp_path / "dummy.jpg"
    from PIL import Image
    im = Image.new("RGB", (100, 100), color="blue")
    im.save(img_path)
    
    # 2. Extract a 2-second real audio clip from a workspace video to test audio input compatibility
    workspace_video = "/home/fenxy/editor/in/[LoliHouse] Super no Ura de Yani Suu Futari - 01 [Early Release][WebRip 1080p HEVC-10bit AAC].mkv"
    audio_clip_path = tmp_path / "clip.mp3"
    
    extracted = False
    if os.path.exists(workspace_video):
        extracted = extract_audio_snippet(workspace_video, 30.0, 32.0, str(audio_clip_path))
        
    payload = build_gemini_payload(
        start_time=30.0,
        end_time=32.0,
        transcript="哟 佐佐木",
        keyframe_paths=[str(img_path)],
        audio_snippet_path=str(audio_clip_path) if extracted else None
    )
    
    res = call_gemini_multimodal(payload, api_key)
    assert res is not None
    print(f"Real Gemini output:\n{res}")
    
    # Clean res and load JSON
    cleaned_res = res.strip()
    if cleaned_res.startswith("```json"):
        cleaned_res = cleaned_res.split("```json", 1)[1]
    if cleaned_res.endswith("```"):
        cleaned_res = cleaned_res.rsplit("```", 1)[0]
    cleaned_res = cleaned_res.strip()
    
    data = json.loads(cleaned_res)
    assert "summary" in data
    assert "tags" in data
    assert "visual_style" in data
    assert "motion_intensity" in data
    assert data["motion_intensity"] in ["low", "medium", "high"]
    assert "key_objects" in data
    assert "emotion_flow" in data
    print("Real Gemini Multimodal output matches format exactly!")
