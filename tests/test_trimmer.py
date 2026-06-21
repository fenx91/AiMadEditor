import os
import sys
import pytest

# Add directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.analyzer import trim_audio_file, offset_lyrics

def test_offset_lyrics():
    mock_lyrics = [
        {"start": 10.0, "end": 15.0, "text": "Lyric 1"},
        {"start": 15.0, "end": 20.0, "text": "Lyric 2"},
        {"start": 20.0, "end": 30.0, "text": "Lyric 3"},
        {"start": 30.0, "end": 40.0, "text": "Lyric 4"},
    ]
    
    # Trim from 15.0 to 35.0 (duration 20.0)
    trimmed = offset_lyrics(mock_lyrics, 15.0, 35.0)
    
    # Expected results:
    # Lyric 1: completely before 15.0, skipped
    # Lyric 2: start=0.0, end=5.0, text="Lyric 2"
    # Lyric 3: start=5.0, end=15.0, text="Lyric 3"
    # Lyric 4: start=15.0, end=20.0 (clipped at 35.0 - 15.0 = 20.0), text="Lyric 4"
    assert len(trimmed) == 3
    assert trimmed[0] == {"start": 0.0, "end": 5.0, "text": "Lyric 2"}
    assert trimmed[1] == {"start": 5.0, "end": 15.0, "text": "Lyric 3"}
    assert trimmed[2] == {"start": 15.0, "end": 20.0, "text": "Lyric 4"}

def test_trim_audio_file():
    audio_path = "/home/fenxy/editor/tests/data/music/Adam Lambert - Whataya Want from Me_H.mp3"
    if not os.path.exists(audio_path):
        pytest.skip("Test audio file does not exist")
        
    out_path = "/tmp/test_trim_output.mp3"
    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except OSError:
            pass
        
    trim_audio_file(audio_path, out_path, 10.0, 20.0)
    
    assert os.path.exists(out_path)
    assert os.path.getsize(out_path) > 0
    
    # Check duration using librosa
    import librosa
    y, sr = librosa.load(out_path, sr=22050)
    duration = librosa.get_duration(y=y, sr=sr)
    # Expected duration is ~10 seconds
    assert 9.5 <= duration <= 10.5
    
    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except OSError:
            pass
