import test from 'node:test';
import assert from 'node:assert/strict';

import { resolveEffectiveSlot } from './timeline-model.js';


const lyrics = [
    { start: 0, end: 2 },
    { start: 2, end: 5 },
    { start: 5, end: 7 },
];


test('returns a directly assigned slot without fallback', () => {
    const slot = { clip_start: 8, video_path: 'a.mp4' };
    assert.deepEqual(resolveEffectiveSlot([slot], lyrics, 0), { ...slot, isFallback: false });
});


test('continues the nearest previous clip across empty lyric slots', () => {
    const slot = {
        clip_start: 8,
        video_path: 'a.mp4',
        video_name: 'a',
        proxy_url: '/a',
        video_duration: 20,
        keep_audio: true,
        transcript: 'hello',
    };
    const result = resolveEffectiveSlot([slot, null, null], lyrics, 2);
    assert.equal(result.clip_start, 13);
    assert.equal(result.clip_duration, 2);
    assert.equal(result.fallbackFromIndex, 0);
    assert.equal(result.isFallback, true);
});


test('uses the first future clip when no previous clip exists', () => {
    const future = { clip_start: 4, video_path: 'b.mp4', video_duration: 10 };
    const result = resolveEffectiveSlot([null, future, null], lyrics, 0);
    assert.equal(result.video_path, 'b.mp4');
    assert.equal(result.fallbackFromIndex, 1);
});
