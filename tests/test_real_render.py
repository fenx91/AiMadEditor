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

    dialogue_clips = [
        {
            "start_time": 2.0,
            "end_time": 5.5,  # Spans across Slot 0 (ends at 3.48) and Slot 1 (starts at 3.48)
            "video_path": real_video_path,
            "clip_start": 5.0,
            "clip_duration": 3.5,
            "transcript": "我本来是独立台词（跨视频片段且无画面）",
            "speaker": "Sasaki"
        }
    ]

    payload = {
        "slots": slots,
        "audio_path": audio_path,
        "dialogue_clips": dialogue_clips,
        "setup_name": "test"
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
        assert "mv_output_test.mp4" in output_path
        assert os.path.exists(output_path)
        print(f"Output video verified at: {output_path}")
        
        # Verify the generated template HTML to lock down independent dialogue behavior
        template_path = "/home/fenxy/editor/hyperframes_template/index_test.html"
        assert os.path.exists(template_path)
        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()
            
        # 1. Independent dialogue must be an <audio> element to prevent any visual output/interference on screen
        assert '<audio class="dialogue-layer"' in html or '<audio class="dialogue-layer" id="dialogue_video_0"' in html
        assert 'id="dialogue_video_0"' in html
        
        # 2. It must have the correct track index and timing attributes
        assert 'data-track-index="2"' in html
        assert 'data-start="2.0"' in html or 'data-start="2"' in html
        
        # 3. Make sure there is NO <video class="dialogue-layer"> that would cause visuals to render
        assert '<video class="dialogue-layer"' not in html
        print("Verification passed: Independent dialogue behavior is locked down (invisible audio-only spanning across slots).")
    else:
        print("Render failed!")
        print(response.text)
        assert False, f"Render failed: {response.text}"

@pytest.mark.skip(reason="Requires headless Chrome system dependencies (libnss3) to run")
def test_range_rendering():
    # Verify input video exists
    video_dir = "/home/fenxy/editor/in"
    videos = [f for f in os.listdir(video_dir) if f.endswith((".mkv", ".mp4"))]
    if not videos:
        print("No video files found. Skipping.")
        return

    real_video_path = os.path.join(video_dir, videos[0])
    audio_path = "/home/fenxy/editor/tests/data/music/Adam Lambert - Whataya Want from Me_H.mp3"

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

    dialogue_clips = [
        {
            "start_time": 2.0,
            "end_time": 5.5,  # Spans across Slot 0 and Slot 1
            "video_path": real_video_path,
            "clip_start": 5.0,
            "clip_duration": 3.5,
            "transcript": "我本来是独立台词（跨视频片段且无画面）",
            "speaker": "Sasaki"
        }
    ]

    # Range: from 3.0s to 7.0s (duration = 4.0s)
    # The dialogue clip starts at 2.0s, ends at 5.5s.
    # Shifted:
    # new_start = max(0.0, 2.0 - 3.0) = 0.0
    # new_end = min(4.0, 5.5 - 3.0) = 2.5
    # shift_offset = 3.0 - 2.0 = 1.0
    # new_clip_start = 5.0 + 1.0 = 6.0
    # new_clip_duration = 2.5
    payload = {
        "slots": slots,
        "audio_path": audio_path,
        "dialogue_clips": dialogue_clips,
        "range_start": 3.0,
        "range_end": 7.0,
        "setup_name": "test_range"
    }

    print("Sending range render request...")
    response = client.post("/api/render", json=payload)
    print("Response status:", response.status_code)
    
    if response.status_code == 200:
        data = response.json()
        output_path = data.get("output_path")
        assert "mv_output_test_range.mp4" in output_path
        assert os.path.exists(output_path)
        
        # Verify the generated template HTML has shifted properties
        template_path = "/home/fenxy/editor/hyperframes_template/index_test_range.html"
        assert os.path.exists(template_path)
        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()
            
        # Dialogue should start at 0.0s (since it starts before range_start and ends inside range)
        # Duration should be 2.5s
        assert '<audio class="dialogue-layer"' in html or '<audio class="dialogue-layer" id="dialogue_video_0"' in html
        assert 'data-start="0.0"' in html or 'data-start="0"' in html
        assert 'data-duration="2.5"' in html
        print("Verification passed: Range render dialogue shifting and filtering verified successfully.")
    else:
        assert False, f"Range render failed: {response.text}"

if __name__ == '__main__':
    test_real_rendering()
    test_range_rendering()
