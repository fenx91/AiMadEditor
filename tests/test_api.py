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
