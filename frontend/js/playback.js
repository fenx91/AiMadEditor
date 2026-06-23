/** Pure playback calculations shared by preview controls. */
export function findActiveLyricIndex(lyrics, currentTime) {
    return lyrics.findIndex(lyric => currentTime >= lyric.start && currentTime < lyric.end);
}

export function calculateClipTime(slot, lyric, currentTime) {
    return slot.clip_start + (currentTime - lyric.start);
}

export function shouldResync(actualTime, expectedTime, threshold = 0.45) {
    return Math.abs(actualTime - expectedTime) > threshold;
}

export function formatTime(seconds) {
    const minutes = Math.floor(seconds / 60);
    const wholeSeconds = Math.floor(seconds % 60);
    const tenths = Math.floor((seconds % 1) * 10);
    return `${minutes.toString().padStart(2, '0')}:${wholeSeconds.toString().padStart(2, '0')}.${tenths}`;
}

export function detectSpeaker(summary, transcript) {
    if (!summary) return 'unknown';
    const normalizedSummary = summary.toLowerCase();
    const normalizedTranscript = transcript ? transcript.toLowerCase() : '';
    if (normalizedSummary.includes('tayama') || normalizedSummary.includes('田山') || normalizedTranscript.includes('田山')) return 'tayama';
    if (normalizedSummary.includes('sasaki') || normalizedSummary.includes('佐佐木') || normalizedTranscript.includes('佐佐木')) return 'sasaki';
    if (normalizedSummary.includes('yamada') || normalizedSummary.includes('山田') || normalizedTranscript.includes('山田')) return 'yamada';
    return 'unknown';
}
