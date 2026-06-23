/** Resolve the concrete clip shown for a lyric, including fallback continuation. */
export function resolveEffectiveSlot(timelineSlots, lyrics, index) {
    if (!lyrics) return null;
    if (timelineSlots[index]) return { ...timelineSlots[index], isFallback: false };

    for (let previous = index - 1; previous >= 0; previous--) {
        if (!timelineSlots[previous]) continue;
        const baseSlot = timelineSlots[previous];
        const currentLyric = lyrics[index];
        const baseLyric = lyrics[previous];
        let clipStart = baseSlot.clip_start + (currentLyric.start - baseLyric.start);
        if (baseSlot.video_duration && clipStart > baseSlot.video_duration - 0.1) {
            clipStart = Math.max(0, baseSlot.video_duration - 0.1);
        }
        return {
            video_path: baseSlot.video_path,
            video_name: baseSlot.video_name,
            proxy_url: baseSlot.proxy_url,
            clip_start: clipStart,
            clip_duration: currentLyric.end - currentLyric.start,
            video_duration: baseSlot.video_duration,
            isFallback: true,
            fallbackFromIndex: previous,
            keep_audio: baseSlot.keep_audio,
            transcript: baseSlot.transcript,
            speaker: baseSlot.speaker,
        };
    }

    const firstFilled = timelineSlots.find(slot => slot !== null);
    if (!firstFilled) return null;
    const currentLyric = lyrics[index];
    return {
        video_path: firstFilled.video_path,
        video_name: firstFilled.video_name,
        proxy_url: firstFilled.proxy_url,
        clip_start: firstFilled.clip_start,
        clip_duration: currentLyric.end - currentLyric.start,
        video_duration: firstFilled.video_duration,
        isFallback: true,
        fallbackFromIndex: timelineSlots.indexOf(firstFilled),
        keep_audio: firstFilled.keep_audio,
        transcript: firstFilled.transcript,
        speaker: firstFilled.speaker,
    };
}
