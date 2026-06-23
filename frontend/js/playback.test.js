import test from 'node:test';
import assert from 'node:assert/strict';

import {
    calculateClipTime,
    detectSpeaker,
    findActiveLyricIndex,
    formatTime,
    shouldResync,
} from './playback.js';


test('playback calculations preserve timeline behavior', () => {
    const lyrics = [{ start: 0, end: 2 }, { start: 2, end: 5 }];
    assert.equal(findActiveLyricIndex(lyrics, 2.5), 1);
    assert.equal(calculateClipTime({ clip_start: 10 }, lyrics[1], 2.5), 10.5);
    assert.equal(shouldResync(10, 10.46), true);
    assert.equal(shouldResync(10, 10.44), false);
    assert.equal(formatTime(62.34), '01:02.3');
});


test('speaker detection keeps the existing character mapping', () => {
    assert.equal(detectSpeaker('Tayama at the store', ''), 'tayama');
    assert.equal(detectSpeaker('scene', '佐佐木回答'), 'sasaki');
    assert.equal(detectSpeaker('scene', '山田走进来'), 'yamada');
    assert.equal(detectSpeaker('scene', 'ordinary dialogue'), 'unknown');
});
