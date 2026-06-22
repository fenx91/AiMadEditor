import os
import sys
import pytest
from unittest.mock import MagicMock, patch

# Add directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

# Mock FeatureExtractor class *before* importing backend.app so it doesn't try to load the model
class MockFeatureExtractor:
    def __init__(self):
        self.device = "cpu"
    def get_image_embedding(self, image_path):
        import numpy as np
        return np.ones(512, dtype=np.float32)
    def get_text_embedding(self, text):
        import numpy as np
        return np.ones(512, dtype=np.float32)

class MockTensor:
    pass

sys.modules['transformers'] = MagicMock()
mock_torch = MagicMock()
mock_torch.Tensor = MockTensor
sys.modules['torch'] = mock_torch
sys.modules['torch.nn'] = MagicMock()
sys.modules['torch.nn.functional'] = MagicMock()

import backend.indexer
import backend.app

backend.indexer.FeatureExtractor = MockFeatureExtractor
backend.app.FeatureExtractor = MockFeatureExtractor

from backend.app import app
from fastapi.testclient import TestClient

client = TestClient(app)

@patch("backend.app.call_gemini")
def test_generate_script_plan(mock_call):
    test_db = "data/test_script_plan.db"
    if os.path.exists(test_db):
        try:
            os.remove(test_db)
        except OSError:
            pass
            
    # Mock Gemini response: new section-based format
    mock_call.return_value = """{
      "sections": [
        {
          "section_name": "Verse 1",
          "mood_arc": "loneliness -> yearning",
          "narrative_concept": "An astronaut alone on Mars, reflecting on Earth.",
          "visual_pacing": "slow",
          "lines": [
            {
              "index": 0,
              "lyric": "Whataya want from me",
              "visual_prompt": "An astronaut standing on a desolate red sand dune under a dusty pink sky, looking at their cracked visor.",
              "motion_preference": "low",
              "emotional_tone": "loneliness and despair"
            }
          ]
        }
      ]
    }"""
    
    payload = {
        "lyrics": [
            {"text": "Whataya want from me", "start": 0.0, "end": 4.5}
        ],
        "user_vision": "astronaut on Mars"
    }
    
    with patch("backend.app.DB_PATH", test_db):
        response = client.post("/api/generate_script_plan", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    # Output should be flattened list
    assert len(data) == 1
    assert data[0]["index"] == 0
    assert data[0]["lyric"] == "Whataya want from me"
    assert "astronaut" in data[0]["visual_prompt"]
    assert data[0]["motion_preference"] == "low"
    assert data[0]["emotional_tone"] == "loneliness and despair"
    # Verify section metadata is attached
    assert data[0]["section_name"] == "Verse 1"
    assert data[0]["mood_arc"] == "loneliness -> yearning"
    
    # Check that mock_call was called with correct argument types
    assert mock_call.call_count == 1
    # Check that prompt text contains user vision
    called_prompt = mock_call.call_args[0][0]
    assert "astronaut on Mars" in called_prompt


@patch("backend.app.call_gemini")
def test_regenerate_script_line(mock_call):
    # Mock Gemini response
    mock_call.return_value = """
    {
      "visual_prompt": "An astronaut running desperately from a massive dust storm, motion blur, intense orange lighting.",
      "motion_preference": "high",
      "emotional_tone": "panic and urgency"
    }
    """
    
    payload = {
        "lyric_text": "Whataya want from me",
        "current_prompt": "An astronaut standing on a dune.",
        "user_feedback": "make him run from a dust storm and speed up",
        "user_vision": "astronaut on Mars"
    }
    
    response = client.post("/api/regenerate_script_line", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert data["visual_prompt"] == "An astronaut running desperately from a massive dust storm, motion blur, intense orange lighting."
    assert data["motion_preference"] == "high"
    assert data["emotional_tone"] == "panic and urgency"
    
    assert mock_call.call_count == 1
    called_prompt = mock_call.call_args[0][0]
    assert "dust storm" in called_prompt
