import os
import sys
import pytest
from unittest.mock import MagicMock, patch
import numpy as np

# Add directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

# Mock FeatureExtractor class *before* importing backend.app so it doesn't try to load the model
class MockFeatureExtractor:
    def __init__(self):
        self.device = "cpu"
    def get_image_embedding(self, image_path):
        return np.ones(512, dtype=np.float32)
    def get_text_embedding(self, text):
        return np.ones(512, dtype=np.float32)

# Mock torch, all its submodules, and transformers BEFORE importing any backend module.
# Without mocking torch.nn / torch.nn.functional, Python cannot resolve
# "import torch.nn.functional as F" inside indexer.py even when torch itself is mocked.
sys.modules['transformers'] = MagicMock()

class MockTensor:
    pass

mock_torch = MagicMock()
mock_torch.Tensor = MockTensor
sys.modules['torch'] = mock_torch
sys.modules['torch.nn'] = MagicMock()
sys.modules['torch.nn.functional'] = MagicMock()

# Now import the backend packages so that patch() can resolve 'backend.indexer.*'
import backend.indexer  # noqa: E402
import backend.app      # noqa: E402

# Directly replace FeatureExtractor with the mock in both modules
backend.indexer.FeatureExtractor = MockFeatureExtractor
backend.app.FeatureExtractor = MockFeatureExtractor

from backend.app import app          # noqa: E402  (uses cached module)
from backend.indexer import init_db  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(app)

def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    # Since frontend/index.html is served if it exists, check for either the real page or fallback string.
    assert "HYPER" in response.text or "AI MV Script Server" in response.text

def test_api_get_videos_empty():
    test_db = "data/test_metadata.db"
    init_db(test_db)
    try:
        with patch('backend.app.DB_PATH', test_db):
            response = client.get("/api/videos")
            assert response.status_code == 200
            assert isinstance(response.json(), list)
    finally:
        if os.path.exists(test_db):
            try:
                os.remove(test_db)
            except OSError:
                pass

def test_api_video_file_not_found():
    response = client.get("/api/video_file?path=nonexistent_file.mp4")
    assert response.status_code == 404

def test_api_video_segments_and_match():
    test_db = "data/test_segments_api.db"
    init_db(test_db)
    
    import sqlite3
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    
    # Insert a dummy video
    cursor.execute("""
    INSERT INTO videos (id, original_path, proxy_path, duration, fps, asr_processed)
    VALUES (10, 'video_10.mp4', 'proxy_10.mp4', 100.0, 30.0, 1)
    """)
    
    # Insert a dummy keyframe
    # embedding should be 512 floats
    import numpy as np
    dummy_emb = np.ones(512, dtype=np.float32).tobytes()
    cursor.execute("""
    INSERT INTO keyframes (id, video_id, timestamp, frame_path, embedding, motion_score)
    VALUES (1, 10, 15.0, 'frame_15.jpg', ?, 2.5)
    """, (sqlite3.Binary(dummy_emb),))
    
    # Insert segment metadata
    cursor.execute("""
    INSERT INTO video_segments (
        video_id, start_time, end_time, summary, tags, visual_style, 
        motion_intensity, key_objects, emotion_flow, is_op, is_ed, transcript, mad_score, scene_type
    ) VALUES (
        10, 10.0, 20.0, 'Gemini Summary', '["tag1", "tag2"]', 'Visual Style', 
        'medium', '["obj1"]', 'Neutral Flow', 0, 0, 'Transcript Text', 8, 'dialogue'
    )
    """)
    conn.commit()
    conn.close()
    
    try:
        # Patch the app's DB_PATH and extractor
        with patch('backend.app.DB_PATH', test_db), \
             patch('backend.app.extractor', MockFeatureExtractor()):
            
            # Test 1: Get Video Segments
            response = client.get("/api/videos/10/segments")
            assert response.status_code == 200
            segments = response.json()
            assert len(segments) == 1
            assert segments[0]["summary"] == "Gemini Summary"
            assert segments[0]["tags"] == ["tag1", "tag2"]
            assert segments[0]["key_objects"] == ["obj1"]
            
            # Test 2: Match API includes segment information
            match_req = {
                "lyric_text": "hello",
                "limit": 5,
                "motion_preference": "any"
            }
            response = client.post("/api/match", json=match_req)
            assert response.status_code == 200
            candidates = response.json()
            assert len(candidates) >= 1
            
            # The candidate timestamp is 15.0s, which falls in segment [10.0s - 20.0s]
            cand = next(c for c in candidates if c["video_id"] == 10 and c["timestamp"] == 15.0)
            assert cand["segment"] is not None
            assert cand["segment"]["summary"] == "Gemini Summary"
            assert cand["segment"]["start_time"] == 10.0
            assert cand["segment"]["end_time"] == 20.0

            # Test 3: Batch Match API includes segment information
            batch_req = {
                "items": [
                    {
                        "index": 0,
                        "lyric_text": "hello",
                        "motion_preference": "any"
                    }
                ]
            }
            response = client.post("/api/batch_match", json=batch_req)
            assert response.status_code == 200
            batch_res = response.json()
            assert "0" in batch_res
            candidates_batch = batch_res["0"]
            assert len(candidates_batch) >= 1
            cand_b = next(c for c in candidates_batch if c["video_id"] == 10 and c["timestamp"] == 15.0)
            assert cand_b["segment"] is not None
            assert cand_b["segment"]["summary"] == "Gemini Summary"
            assert cand_b["segment"]["start_time"] == 10.0
            assert cand_b["segment"]["end_time"] == 20.0
            
    finally:
        if os.path.exists(test_db):
            try:
                os.remove(test_db)
            except OSError:
                pass
