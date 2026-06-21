import os
import sys
import pytest
from unittest.mock import MagicMock

# Add directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

# Mock CLIP model/transformers/torch to skip loading them
class MockFeatureExtractor:
    def __init__(self):
        self.device = "cpu"

sys.modules['transformers'] = MagicMock()
class MockTensor:
    pass
mock_torch = MagicMock()
mock_torch.Tensor = MockTensor
sys.modules['torch'] = mock_torch
sys.modules['torch.nn'] = MagicMock()
sys.modules['torch.nn.functional'] = MagicMock()

import backend.indexer
backend.indexer.FeatureExtractor = MockFeatureExtractor
import backend.app
backend.app.FeatureExtractor = MockFeatureExtractor

from fastapi.testclient import TestClient
from backend.app import app

client = TestClient(app)

@pytest.mark.skip(reason="Requires headless Chrome system dependencies (libnss3) to run")
def test_real_rendering():
    # Verify input video exists
    video_dir = "/home/fenxy/editor/in"
    videos = [f for f in os.listdir(video_dir) if f.endswith((".mkv", ".mp4"))]
    if not videos:
        print("No video files found in /home/fenxy/editor/in. Skipping test.")
        return

    real_video_path = os.path.join(video_dir, videos[0])
    audio_path = "/home/fenxy/editor/tests/data/music/Adam Lambert - Whataya Want from Me_H.mp3"

    print(f"Using video: {real_video_path}")
    print(f"Using audio: {audio_path}")

    # Build 3 short slots (total ~10 seconds)
    slots = [
        {
            "start_time": 0.0,
            "end_time": 3.48,
            "video_path": real_video_path,
            "clip_start": 10.0,
            "clip_duration": 3.48
        },
        {
            "start_time": 3.48,
            "end_time": 6.96,
            "video_path": real_video_path,
            "clip_start": 20.0,
            "clip_duration": 3.48
        },
        {
            "start_time": 6.96,
            "end_time": 10.44,
            "video_path": real_video_path,
            "clip_start": 30.0,
            "clip_duration": 3.48
        }
    ]

    payload = {
        "slots": slots,
        "audio_path": audio_path
    }

    print("Sending render request to /api/render...")
    # This will run the real render command 'npx hyperframes render'
    response = client.post("/api/render", json=payload)
    print("Response status:", response.status_code)
    
    if response.status_code == 200:
        data = response.json()
        print("Render succeeded! Response data:")
        print(data)
        output_path = data.get("output_path")
        assert os.path.exists(output_path)
        print(f"Output video verified at: {output_path}")
    else:
        print("Render failed!")
        print(response.text)
        assert False, f"Render failed: {response.text}"

if __name__ == '__main__':
    test_real_rendering()
