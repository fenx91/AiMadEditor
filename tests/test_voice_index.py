import os
import sys
import pytest
import sqlite3
from unittest.mock import MagicMock, patch

# Add directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

# Mock FeatureExtractor class *before* importing backend modules so it doesn't load the model
class MockFeatureExtractor:
    def __init__(self):
        self.device = "cpu"
    def get_image_embedding(self, image_path):
        import numpy as np
        return np.ones(512, dtype=np.float32)
    def get_text_embedding(self, text):
        import numpy as np
        # Return a deterministic vector so we can test cosine similarities
        # If text is "Hello world", return ones; if it's "Goodbye", return minus ones
        if "Hello" in text:
            return np.ones(512, dtype=np.float32) / 22.627 # L2 normalized (sqrt(512) is ~22.627)
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
import backend.matcher

backend.indexer.FeatureExtractor = MockFeatureExtractor
backend.matcher.FeatureExtractor = MockFeatureExtractor

from backend.indexer import init_db, index_video_file
from backend.matcher import find_candidates

@patch("backend.indexer.has_audio")
@patch("backend.indexer.extract_audio")
@patch("backend.indexer.transcribe_audio_with_gemini")
@patch("backend.indexer.get_video_info")
@patch("backend.indexer.process_video_media")
@patch("backend.indexer.calculate_motion_scores")
def test_voice_indexing_and_matching(
    mock_motion, mock_media, mock_video_info, mock_transcribe, mock_extract, mock_has_audio
):
    # Setup mocks
    mock_has_audio.return_value = True
    mock_extract.return_value = True
    mock_transcribe.return_value = [
        {"start": 1.2, "end": 3.5, "text": "Hello world from the astronaut"}
    ]
    mock_video_info.return_value = (5.0, 30.0) # 5 seconds, 30 fps
    
    mock_media.return_value = (
        "data/proxies/dummy_proxy.mp4",
        [
            {"timestamp": 0.0, "frame_path": "data/keyframes/dummy_frame_0.jpg"},
            {"timestamp": 1.0, "frame_path": "data/keyframes/dummy_frame_1.jpg"},
            {"timestamp": 2.0, "frame_path": "data/keyframes/dummy_frame_2.jpg"},
            {"timestamp": 3.0, "frame_path": "data/keyframes/dummy_frame_3.jpg"},
            {"timestamp": 4.0, "frame_path": "data/keyframes/dummy_frame_4.jpg"}
        ]
    )
    mock_motion.return_value = [0.1, 0.2, 0.3, 0.4, 0.5]
    
    test_db = "data/test_voice_metadata.db"
    init_db(test_db)
    
    try:
        extractor = MockFeatureExtractor()
        video_path = "/home/fenxy/editor/in/test_video.mp4"
        
        # 1. Index the video
        video_id = index_video_file(video_path, extractor, db_path=test_db)
        assert video_id is not None
        
        # 2. Check that the transcripts were written to the db
        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()
        cursor.execute("SELECT start_time, end_time, text FROM transcripts WHERE video_id = ?", (video_id,))
        rows = cursor.fetchall()
        conn.close()
        
        assert len(rows) == 1
        assert rows[0][0] == 1.2
        assert rows[0][1] == 3.5
        assert rows[0][2] == "Hello world from the astronaut"
        
        # 3. Test find_candidates with text query matching the transcript
        cands = find_candidates("Hello world", extractor, db_path=test_db, limit=5)
        assert len(cands) > 0
        
        # Ensure that transcript boosting or matching occurred
        # Frame at 2.0s or 3.0s should fall within [1.2, 3.5] and have transcript text attached
        matching_cands_with_transcript = [c for c in cands if "transcript_text" in c]
        assert len(matching_cands_with_transcript) > 0
        assert matching_cands_with_transcript[0]["transcript_text"] == "Hello world from the astronaut"
        
    finally:
        if os.path.exists(test_db):
            try:
                os.remove(test_db)
            except OSError:
                pass
