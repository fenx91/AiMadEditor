import os
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from backend.matcher import find_candidates, find_candidates_batch

class MockExtractor:
    pass

@patch('backend.matcher.call_gemini')
@patch('sqlite3.connect')
def test_find_candidates(mock_connect, mock_call_gemini):
    # Mock SQLite connection and cursor
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    
    # Sequential mock outputs for fetchone() calls
    fetch_results = [
        None,                              # 1. Cache table exists check (read) -> Cache miss
        (101, "path/to/frame1.jpg", 1.5),  # 2. Keyframe query for segment 1
        (102, "path/to/frame2.jpg", 2.5),  # 3. Keyframe query for segment 2
        None                               # 4. Cache table exists check (write) -> Skip write
    ]
    mock_cursor.fetchone.side_effect = fetch_results
    
    # Mock video segments database rows (14 columns including mad_score, scene_type)
    mock_cursor.fetchall.return_value = [
        (1, 10, 0.0, 5.0, "Sasaki commutes home tired", "[]", "night lighting", "low", "", "path/to/video1.mp4", "path/to/proxy1.mp4", 10.0, 7, "dialogue"),
        (2, 10, 5.0, 10.0, "Tayama smokes at convenience store back door", "[]", "dark alley", "medium", "", "path/to/video1.mp4", "path/to/proxy1.mp4", 10.0, 8, "emotional")
    ]
    
    # Mock Gemini response (returns matching segment IDs as JSON string)
    mock_call_gemini.return_value = "[1, 2]"
    
    extractor = MockExtractor()
    candidates = find_candidates("Sasaki feeling tired", extractor, db_path="data/test_metadata.db", limit=5, motion_preference="any")
    
    # Assertions
    assert len(candidates) == 2
    assert candidates[0]["video_id"] == 10
    assert candidates[0]["timestamp"] == 2.5  # midpoint of 0.0s - 5.0s
    assert candidates[1]["timestamp"] == 7.5  # midpoint of 5.0s - 10.0s
    assert candidates[0]["score"] == 100.0
    assert candidates[1]["score"] == 90.0
    assert candidates[0]["frame_path"] == "path/to/frame1.jpg"
    assert candidates[1]["frame_path"] == "path/to/frame2.jpg"

@patch('backend.matcher.call_gemini')
@patch('sqlite3.connect')
def test_find_candidates_batch(mock_connect, mock_call_gemini):
    # Mock SQLite connection and cursor
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    
    # Sequential mock outputs for fetchone() calls
    fetch_results = [
        (1,),                              # 1. Cache table exists check (read) -> True
        None,                              # 2. Check query_hash for item 0 -> Cache miss
        None,                              # 3. Check query_hash for item 1 -> Cache miss
        (1,),                              # 4. Cache table exists check (write) -> True
        (101, "path/to/frame1.jpg", 1.5),  # 5. Keyframe query for segment 1 (item 0 match)
        (102, "path/to/frame2.jpg", 2.5)   # 6. Keyframe query for segment 2 (item 1 match)
    ]
    mock_cursor.fetchone.side_effect = fetch_results
    
    # Mock video segments database rows (16 columns including mad_score, scene_type, is_op, is_ed)
    mock_cursor.fetchall.return_value = [
        (1, 10, 0.0, 5.0, "Sasaki commutes home tired", "[]", "night lighting", "low", "", "path/to/video1.mp4", "path/to/proxy1.mp4", 10.0, 7, "dialogue", 0, 0),
        (2, 10, 5.0, 10.0, "Tayama smokes at convenience store back door", "[]", "dark alley", "medium", "", "path/to/video1.mp4", "path/to/proxy1.mp4", 10.0, 8, "emotional", 0, 0)
    ]
    
    # Mock Gemini batch response
    mock_call_gemini.return_value = '{"0": [1], "1": [2]}'
    
    items = [
        {"index": 0, "lyric_text": "Sasaki feeling tired", "motion_preference": "any"},
        {"index": 1, "lyric_text": "Tayama smoking", "motion_preference": "any"}
    ]
    
    results = find_candidates_batch(items, db_path="data/test_metadata.db")
    
    # Assertions
    assert len(results) == 2
    assert 0 in results
    assert 1 in results
    assert len(results[0]) == 1
    assert len(results[1]) == 1
    assert results[0][0]["video_id"] == 10
    assert results[0][0]["timestamp"] == 2.5
    assert results[1][0]["timestamp"] == 7.5
    assert results[0][0]["frame_path"] == "path/to/frame1.jpg"
    assert results[1][0]["frame_path"] == "path/to/frame2.jpg"

@patch('backend.matcher.call_gemini')
@patch('sqlite3.connect')
def test_find_candidates_with_narrative_context(mock_connect, mock_call_gemini):
    # Mock SQLite connection and cursor
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    
    # Mock cursors for table check, frame checks, write checks
    mock_cursor.fetchone.side_effect = [
        None,                              # cache table check (read) -> miss
        (101, "path/to/frame1.jpg", 1.5),  # Keyframe query for segment 1
        None                               # cache table check (write) -> skip
    ]
    
    mock_cursor.fetchall.return_value = [
        (1, 10, 0.0, 5.0, "Sasaki commutes home tired", "[]", "night lighting", "low", "I am tired", "path/to/video1.mp4", "path/to/proxy1.mp4", 10.0, 7, "dialogue")
    ]
    
    mock_call_gemini.return_value = "[1]"
    
    extractor = MockExtractor()
    candidates = find_candidates(
        lyric_text="Sasaki feeling tired",
        extractor=extractor,
        db_path="data/test_metadata.db",
        limit=5,
        motion_preference="any",
        lyric="Tired night",
        narrative_concept="Show Sasaki walking in the rain",
        emotional_tone="melancholy"
    )
    
    assert len(candidates) == 1
    assert candidates[0]["video_id"] == 10
    
    # Verify mock_call_gemini prompt contained the context strings
    prompt_sent = mock_call_gemini.call_args[0][0]
    assert "Song Lyric (Text): \"Tired night\"" in prompt_sent
    assert "Narrative Concept/Storytelling Goal: \"Show Sasaki walking in the rain\"" in prompt_sent
    assert "Emotional Tone: \"melancholy\"" in prompt_sent
    assert "Evaluating character dialogue/voiceover" in prompt_sent


