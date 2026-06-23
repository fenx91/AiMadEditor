import test from 'node:test';
import assert from 'node:assert/strict';

import {
    buildIndependentDialogueClips,
    findActiveIndependentDialogue,
    getDialogueMode,
    getIndependentDialogueValues,
} from './dialogue-track.js';

test('dialogue mode preserves linked audio compatibility', () => {
    assert.equal(getDialogueMode({ keep_audio: true }), 'linked');
    assert.equal(getDialogueMode({ dialogue_independent: true, keep_audio: true }), 'independent');
    assert.equal(getDialogueMode({}), 'off');
});

test('independent dialogue may extend beyond its visual segment', () => {
    const values = getIndependentDialogueValues({
        clip_start: 10,
        clip_duration: 1,
        video_duration: 30,
        dialogue_independent: true,
        dialogue_start_time: 5,
        dialogue_end_time: 8,
    }, { start: 5, end: 6 }, 20);

    assert.deepEqual(values, {
        start_time: 5,
        end_time: 8,
        clip_start: 10,
        clip_duration: 3,
    });
});

test('builds and resolves an independent dialogue track', () => {
    const clips = buildIndependentDialogueClips([{
        segments: [{
            video_path: 'scene.mp4',
            proxy_url: '/scene.mp4',
            clip_start: 12,
            clip_duration: 1,
            video_duration: 30,
            dialogue_independent: true,
            dialogue_start_time: 2,
            dialogue_end_time: 4.5,
            transcript: 'hello',
        }],
    }], [{ start: 2, end: 3 }], 10, () => 'sasaki');

    assert.equal(clips.length, 1);
    assert.equal(clips[0].speaker, 'sasaki');
    assert.equal(clips[0].clip_duration, 2.5);
    assert.equal(findActiveIndependentDialogue(clips, 4)?.transcript, 'hello');
    assert.equal(findActiveIndependentDialogue(clips, 4.5), null);
});
