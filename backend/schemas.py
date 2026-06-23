"""Pydantic request models shared by the API layer."""

from typing import List, Optional

from pydantic import BaseModel


class IndexRequest(BaseModel):
    directory: str
    force_refresh: bool = False


class MatchRequest(BaseModel):
    lyric_text: str
    motion_preference: str = "any"
    limit: int = 5
    lyric: Optional[str] = ""
    narrative_concept: Optional[str] = ""
    emotional_tone: Optional[str] = ""


class BatchMatchItem(BaseModel):
    index: int
    lyric_text: str
    motion_preference: str = "any"
    lyric: Optional[str] = ""
    narrative_concept: Optional[str] = ""
    emotional_tone: Optional[str] = ""


class BatchMatchRequest(BaseModel):
    items: List[BatchMatchItem]


class TimelineSlot(BaseModel):
    start_time: float
    end_time: float
    video_path: str
    clip_start: float
    clip_duration: float
    keep_audio: Optional[bool] = False
    transcript: Optional[str] = ""
    speaker: Optional[str] = "unknown"
    speaker_manual: Optional[bool] = False


class DialogueClip(BaseModel):
    start_time: float
    end_time: float
    video_path: str
    clip_start: float
    clip_duration: float
    transcript: Optional[str] = ""
    speaker: Optional[str] = "unknown"
    speaker_manual: Optional[bool] = False
    source_slot_index: Optional[int] = None
    source_segment_index: Optional[int] = None


class TrimRequest(BaseModel):
    audio_path: str
    lyric_path: Optional[str] = None
    start_time: float
    end_time: float


class RenderRequest(BaseModel):
    slots: List[TimelineSlot]
    audio_path: str
    lyrics: Optional[List[dict]] = None
    music_volume: Optional[float] = 1.0
    dialogue_volume: Optional[float] = 1.0
    range_start: Optional[float] = None
    range_end: Optional[float] = None
    setup_name: Optional[str] = None


class LyricLine(BaseModel):
    text: str
    start: float
    end: float


DEFAULT_USER_VISION = (
    "这是一首讲述两个打工人（佐佐木和田山）互相救赎的 AMV/MAD。"
    "故事从两人互不认识开始，工作的压力与疲惫让彼此 messed up，"
    "但他们 keep coming around，用陪伴和温暖悄悄疗愈对方，最终走向相互依靠。"
    "情感基调：从压抑、孤独 → 惊喜相遇 → 暧昧摩擦 → 互相治愈 → 温暖释怀。"
)


class ScriptPlanRequest(BaseModel):
    lyrics: List[LyricLine]
    user_vision: str = DEFAULT_USER_VISION


class RegenerateLineRequest(BaseModel):
    lyric_text: str
    current_prompt: str
    user_feedback: str
    user_vision: str


class RecommendVisionsRequest(BaseModel):
    lyrics: List[LyricLine]
