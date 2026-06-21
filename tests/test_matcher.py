import os
import sys
import pytest
from unittest.mock import MagicMock, patch
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from backend.matcher import find_candidates

class MockExtractor:
    def get_text_embedding(self, text):
        # Return a normalized vector of ones
        v = np.ones(512, dtype=np.float32)
        return v / np.linalg.norm(v)

@patch('sqlite3.connect')
def test_find_candidates(mock_connect):
    # Mock SQLite connection and cursor
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    
    # Create mock keyframe data
    # 512 dimensions normalized
    v = np.ones(512, dtype=np.float32)
    norm_v = v / np.linalg.norm(v)
    emb_blob = norm_v.tobytes()
    
    # row format: kf.id, kf.video_id, kf.timestamp, kf.frame_path, kf.embedding, kf.motion_score, v.original_path, v.proxy_path, v.duration
    mock_cursor.fetchall.return_value = [
        (1, 10, 2.5, "path/to/frame1.jpg", emb_blob, 2.0, "path/to/video1.mp4", "path/to/proxy1.mp4", 10.0),
        (2, 10, 5.0, "path/to/frame2.jpg", emb_blob, 4.0, "path/to/video1.mp4", "path/to/proxy1.mp4", 10.0)
    ]
    
    extractor = MockExtractor()
    candidates = find_candidates("test lyric", extractor, db_path="data/test_metadata.db", limit=5, motion_preference="any")
    
    # Since we deduplicate keyframes in the same video within 2.0s, and 2.5 and 5.0 are 2.5s apart, both should be kept!
    assert len(candidates) == 2
    
    # Cosine similarity of two identical normalized vectors is 1.0
    assert abs(candidates[0]["similarity"] - 1.0) < 1e-5
    assert candidates[0]["video_id"] == 10
