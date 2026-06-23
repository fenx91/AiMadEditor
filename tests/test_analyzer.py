import os
import sys
import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.analyzer import parse_lrc, parse_txt, analyze_audio_rhythm, analyze_music, ensure_intro_segment

# ─── 测试数据路径 ────────────────────────────────────────────────────────────────
DATA_DIR  = os.path.join(os.path.dirname(__file__), "data", "music")
AUDIO_MP3 = os.path.join(DATA_DIR, "Adam Lambert - Whataya Want from Me_H.mp3")

# 供测试用的内联 LRC（无需依赖外部 lrc 文件）
SAMPLE_LRC = """\
[ti:Whataya Want from Me]
[ar:Adam Lambert]
[00:10.00]First line of lyrics
[00:15.50]Second line of lyrics
[00:22.10]Third line with millisecond format
"""


def test_intro_segment_is_inserted_before_first_timed_lyric():
    lyrics = [
        {"start": 10.44, "end": 14.95, "text": "Hey slow it down"},
        {"start": 14.95, "end": 20.0, "text": "Whataya want from me"},
    ]

    result = ensure_intro_segment(lyrics)

    assert result[0] == {
        "start": 0.0,
        "end": 10.44,
        "text": "前奏 / Intro",
        "is_intro": True,
    }
    assert result[1:] == lyrics


def test_intro_segment_is_not_duplicated_when_timeline_starts_at_zero():
    lyrics = [{"start": 0.0, "end": 4.0, "text": "First line"}]
    assert ensure_intro_segment(lyrics) == lyrics


# ─── parse_lrc 单元测试 ──────────────────────────────────────────────────────────
def test_parse_lrc():
    total_duration = 30.0
    segments = parse_lrc(SAMPLE_LRC, total_duration)

    assert len(segments) == 3
    assert segments[0]["start"] == 10.0
    assert segments[0]["text"] == "First line of lyrics"
    assert segments[0]["end"] == 15.5

    assert segments[1]["start"] == 15.5
    assert segments[1]["text"] == "Second line of lyrics"
    assert segments[1]["end"] == 22.1

    assert segments[2]["start"] == 22.1
    assert segments[2]["text"] == "Third line with millisecond format"
    assert segments[2]["end"] == 30.0

# ─── parse_txt 单元测试 ──────────────────────────────────────────────────────────
def test_parse_txt():
    txt_content = """
    Line 1
    Line 2
    Line 3
    """
    total_duration = 30.0
    segments = parse_txt(txt_content, total_duration)

    assert len(segments) == 3
    assert segments[0]["start"] == 0.0
    assert segments[0]["end"] == 10.0
    assert segments[0]["text"] == "Line 1"

    assert segments[1]["start"] == 10.0
    assert segments[1]["end"] == 20.0

    assert segments[2]["start"] == 20.0
    assert segments[2]["end"] == 30.0

# ─── analyze_audio_rhythm 集成测试（需要真实音频文件）────────────────────────────
@pytest.mark.skipif(not os.path.exists(AUDIO_MP3), reason="测试音频不存在")
def test_analyze_audio_rhythm_real_mp3():
    result = analyze_audio_rhythm(AUDIO_MP3)

    # 返回结构完整
    assert "bpm" in result
    assert "duration" in result
    assert "beats" in result
    assert "onsets" in result
    assert "waveform" in result

    # BPM 在合理范围内（60~200）
    assert 60.0 <= result["bpm"] <= 200.0, f"BPM {result['bpm']} 超出合理范围"

    # 时长应在 200~260s 之间（歌曲约 3:47）
    assert 200 < result["duration"] < 260, f"时长 {result['duration']} 异常"

    # 应检测到节拍
    assert len(result["beats"]) > 50, "节拍数量过少"

    # 波形应有数据点
    assert len(result["waveform"]) > 0

    # 波形值应在 [0, 1]
    assert all(0.0 <= w <= 1.0 for w in result["waveform"]), "波形值超出 [0,1]"

    # BPM 应为 Python float，不是 numpy 类型（防止序列化失败）
    assert isinstance(result["bpm"], float), f"bpm 类型应为 float，实际为 {type(result['bpm'])}"

# ─── analyze_music 集成测试（音频 + 内联 LRC）────────────────────────────────────
@pytest.mark.skipif(not os.path.exists(AUDIO_MP3), reason="测试音频不存在")
def test_analyze_music_with_lrc():
    result = analyze_music(AUDIO_MP3, lyric_text=SAMPLE_LRC)

    assert "bpm" in result
    assert "duration" in result
    assert "lyrics" in result

    lyrics = result["lyrics"]
    assert len(lyrics) == 4, f"应有前奏加 3 段歌词，实际 {len(lyrics)}"

    # 每段歌词应包含 beats 字段
    for seg in lyrics:
        assert "beats" in seg, f"歌词段缺少 beats 字段: {seg}"
        assert "start" in seg
        assert "end" in seg
        assert "text" in seg

# ─── analyze_music 集成测试（音频 + 纯文本歌词）──────────────────────────────────
@pytest.mark.skipif(not os.path.exists(AUDIO_MP3), reason="测试音频不存在")
def test_analyze_music_with_plain_text():
    lyric_text = "Verse one\nVerse two\nVerse three"
    result = analyze_music(AUDIO_MP3, lyric_text=lyric_text)

    assert len(result["lyrics"]) == 3

    # 歌词时间段应覆盖整首歌
    total = result["duration"]
    assert result["lyrics"][-1]["end"] == pytest.approx(total, abs=1.0)
