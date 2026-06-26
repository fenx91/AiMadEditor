import json
import os
import sys

# Add directories to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

# Mock CLIP model/transformers/torch to skip loading them
from unittest.mock import MagicMock
sys.modules['transformers'] = MagicMock()
mock_torch = MagicMock()
class MockTensor: pass
mock_torch.Tensor = MockTensor
sys.modules['torch'] = mock_torch
sys.modules['torch.nn'] = MagicMock()
sys.modules['torch.nn.functional'] = MagicMock()

import backend.indexer
class MockFeatureExtractor:
    def __init__(self): self.device = "cpu"
backend.indexer.FeatureExtractor = MockFeatureExtractor
import backend.app
backend.app.FeatureExtractor = MockFeatureExtractor

from backend.schemas import RenderRequest, TimelineSlot, DialogueClip
from backend.render_service import render_video

# 1. Load setup 1.json
setup_path = "data/setups/1.json"
print(f"Loading setup: {setup_path}")
with open(setup_path, "r", encoding="utf-8") as f:
    setup_data = json.load(f)

# 2. Build RenderRequest with range limits for 30s test
setup_data["setup_name"] = "test_30s"
setup_data["range_start"] = 0.0
setup_data["range_end"] = 30.0

# Reconstruct slots and dialogue_clips as models
setup_data["slots"] = [TimelineSlot(**s) for s in setup_data["slots"]]
if "dialogue_clips" in setup_data and setup_data["dialogue_clips"]:
    setup_data["dialogue_clips"] = [DialogueClip(**d) for d in setup_data["dialogue_clips"]]

req = RenderRequest(**setup_data)

# 3. Trigger render
try:
    print("Starting 30s test render via render_video...")
    res = render_video(req)
    print("\nRender result:", res)
except Exception as e:
    print("Render failed with exception:", e)
