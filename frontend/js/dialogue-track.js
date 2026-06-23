function finiteNumber(value, fallback) {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : fallback;
}

export function getDialogueMode(segment) {
    if (segment?.dialogue_independent) return 'independent';
    if (segment?.keep_audio) return 'linked';
    return 'off';
}

export function getIndependentDialogueValues(segment, lyric, songDuration) {
    const visualStart = lyric.start + finiteNumber(segment?.offset_start, 0);
    const visualDuration = Math.max(0.1, finiteNumber(
        segment?.clip_duration,
        finiteNumber(segment?.offset_end, lyric.end - lyric.start) - finiteNumber(segment?.offset_start, 0)
    ));
    const sourceStart = Math.max(0, finiteNumber(segment?.dialogue_clip_start, segment?.clip_start || 0));
    const maxSourceDuration = segment?.video_duration
        ? Math.max(0.1, finiteNumber(segment.video_duration, sourceStart + visualDuration) - sourceStart)
        : visualDuration;
    const startTime = Math.max(0, Math.min(songDuration, finiteNumber(segment?.dialogue_start_time, visualStart)));
    const defaultEnd = startTime + Math.min(visualDuration, maxSourceDuration);
    const endTime = Math.max(
        startTime + 0.1,
        Math.min(songDuration, startTime + maxSourceDuration, finiteNumber(segment?.dialogue_end_time, defaultEnd))
    );

    return {
        start_time: startTime,
        end_time: endTime,
        clip_start: sourceStart,
        clip_duration: endTime - startTime,
    };
}

export function buildIndependentDialogueClips(timelineSlots, lyrics, songDuration, resolveSpeaker) {
    if (!Array.isArray(timelineSlots) || !Array.isArray(lyrics)) return [];

    const clips = [];
    timelineSlots.forEach((slot, slotIndex) => {
        if (!slot || !lyrics[slotIndex]) return;
        const segments = Array.isArray(slot.segments) ? slot.segments : [slot];
        segments.forEach((segment, segmentIndex) => {
            if (!segment?.dialogue_independent || !segment.video_path) return;
            const timing = getIndependentDialogueValues(segment, lyrics[slotIndex], songDuration);
            clips.push({
                id: `dialogue-${slotIndex}-${segmentIndex}`,
                source_slot_index: slotIndex,
                source_segment_index: segmentIndex,
                video_path: segment.video_path,
                video_name: segment.video_name || segment.video_path.split(/[\\/]/).pop(),
                proxy_url: segment.proxy_url || '',
                start_time: timing.start_time,
                end_time: timing.end_time,
                clip_start: timing.clip_start,
                clip_duration: timing.clip_duration,
                transcript: segment.transcript || '',
                speaker: resolveSpeaker ? resolveSpeaker(segment) : (segment.speaker || 'unknown'),
                speaker_manual: Boolean(segment.speaker_manual),
            });
        });
    });

    return clips.sort((a, b) => a.start_time - b.start_time || a.source_slot_index - b.source_slot_index);
}

export function findActiveIndependentDialogue(clips, time) {
    if (!Array.isArray(clips)) return null;
    return clips.find(clip => time >= clip.start_time && time < clip.end_time) || null;
}
