import os
import sys
import pytest
import sqlite3
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
    parse_srt,
    parse_lrc,
    parse_ass,
    find_matching_subtitle_file,
    init_db,
    index_video_file
)

def test_parse_ass(tmp_path):
    ass_content = """[Script Info]
Title: Test ASS Subtitle

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:01:14.22,0:01:16.85,Default,,0,0,0,,お姉さん、{\b1}タバコ{\b0}。
Dialogue: 0,0:02:10.00,0:02:15.50,Default,,0,0,0,,Line 2 \\N Line 2 break
"""
    ass_file = tmp_path / "test.ass"
    ass_file.write_text(ass_content, encoding="utf-8")
    
    segments = parse_ass(str(ass_file))
    assert len(segments) == 2
    assert segments[0]["start"] == 74.22
    assert segments[0]["end"] == 76.85
    assert segments[0]["text"] == "お姉さん、タバコ。"
    assert segments[1]["start"] == 130.0
    assert segments[1]["end"] == 135.5
    assert segments[1]["text"] == "Line 2   Line 2 break"

def test_parse_ass_deduplication(tmp_path):
    ass_content = """[Script Info]
Title: Test ASS Subtitle Deduplication

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:08.15,0:00:13.95,OP - JP,,0,0,0,,{\fad(520,520)\blur0\t(0,520,\blur4)\c&HFFFFFF&\1a&HFF&}心臓こじ開けて　さらっと食べて
Dialogue: 1,0:00:08.15,0:00:13.95,OP - JP,,0,0,0,,{\fad(520,520)\bord0\be4\t(0,790,\be0)\move(958,12,960,10,0,520)}心臓こじ開けて　さらっと食べて
Dialogue: 0,0:00:08.15,0:00:13.95,OP - CN,,0,0,0,,{\fad(520,520)\blur0\t(0,520,\blur4)\c&HFFFFFF&\1a&HFF&}撬开心脏 平静食用之
Dialogue: 1,0:00:08.15,0:00:13.95,OP - CN,,0,0,0,,{\fad(520,520)\bord0\be4\t(0,790,\be0)\move(958,1072,960,1070,0,520)}撬开心脏 平静食用之
"""
    ass_file = tmp_path / "dedup.ass"
    ass_file.write_text(ass_content, encoding="utf-8")
    
    segments = parse_ass(str(ass_file))
    assert len(segments) == 2
    assert segments[0]["text"] == "心臓こじ開けて　さらっと食べて"
    assert segments[1]["text"] == "撬开心脏 平静食用之"

def test_find_matching_subtitle_file(tmp_path):
    # Setup folders
    video_dir = tmp_path / "in"
    video_dir.mkdir()
    sub_dir = video_dir / "subtitles"
    sub_dir.mkdir()
    
    # Create video file matching Episode 1
    video_path = video_dir / "[LoliHouse] Super no Ura - 01 [1080p].mkv"
    video_path.write_text("video")
    
    # Create matching and non-matching subtitles in subtitles subfolder
    sub1 = sub_dir / "Super no Ura E01.chs.ass"
    sub1.write_text("dialogue 1")
    sub2 = sub_dir / "Super no Ura E01.cht.ass"
    sub2.write_text("dialogue 1 trad")
    sub3 = sub_dir / "Super no Ura E02.chs.ass"
    sub3.write_text("dialogue 2")
    
    matched = find_matching_subtitle_file(str(video_path))
    assert matched is not None
    # Should prioritize Simplified Chinese (.chs.ass)
    assert os.path.basename(matched) == "Super no Ura E01.chs.ass"

def test_parse_srt(tmp_path):
    srt_content = """1
00:00:01,200 --> 00:00:03,500
Hello world from SRT

2
00:00:04,000 --> 00:00:06,850
This is another segment
"""
    srt_file = tmp_path / "test.srt"
    srt_file.write_text(srt_content, encoding="utf-8")
    
    segments = parse_srt(str(srt_file))
    assert len(segments) == 2
    assert segments[0]["start"] == 1.2
    assert segments[0]["end"] == 3.5
    assert segments[0]["text"] == "Hello world from SRT"
    assert segments[1]["start"] == 4.0
    assert segments[1]["end"] == 6.85
    assert segments[1]["text"] == "This is another segment"

def test_parse_lrc(tmp_path):
    lrc_content = """[00:01.20]Hello from LRC
[00:04.00]This is another LRC
"""
    lrc_file = tmp_path / "test.lrc"
    lrc_file.write_text(lrc_content, encoding="utf-8")
    
    segments = parse_lrc(str(lrc_file))
    assert len(segments) == 2
    assert segments[0]["start"] == 1.2
    assert segments[0]["end"] == 4.0
    assert segments[0]["text"] == "Hello from LRC"
    assert segments[1]["start"] == 4.0
    assert segments[1]["end"] == 8.0
    assert segments[1]["text"] == "This is another LRC"

@patch("backend.indexer.get_video_info")
@patch("backend.indexer.process_video_media")
@patch("backend.indexer.calculate_motion_scores")
@patch("backend.indexer.transcribe_audio")
def test_index_video_file_with_subtitles(
    mock_transcribe, mock_motion, mock_media, mock_video_info, tmp_path
):
    mock_video_info.return_value = (10.0, 30.0)
    mock_media.return_value = ("proxy.mp4", [{"timestamp": 0.0, "frame_path": "frame_0.jpg"}])
    mock_motion.return_value = [0.1]
    
    # Create a dummy video file path
    video_path = tmp_path / "my_video.mp4"
    video_path.write_text("dummy video content")
    
    # Create srt next to it
    srt_content = """1
00:00:01,000 --> 00:00:05,000
Subtitle line
"""
    srt_path = tmp_path / "my_video.srt"
    srt_path.write_text(srt_content, encoding="utf-8")
    
    db_path = tmp_path / "sub_test.db"
    init_db(str(db_path))
    
    extractor = MockFeatureExtractor()
    vid_id = index_video_file(str(video_path), extractor, db_path=str(db_path))
    
    # Check transcripts table
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT start_time, end_time, text FROM transcripts WHERE video_id = ?", (vid_id,))
    rows = cursor.fetchall()
    conn.close()
    
    assert len(rows) == 1
    assert rows[0][0] == 1.0
    assert rows[0][1] == 5.0
    assert rows[0][2] == "Subtitle line"
    
    # Verify ASR was NOT called since subtitles were loaded
    mock_transcribe.assert_not_called()
