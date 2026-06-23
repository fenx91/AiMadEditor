import test from 'node:test';
import assert from 'node:assert/strict';

import {
    calculateClipTime,
    detectSpeaker,
    findActiveLyricIndex,
    formatTime,
    mutePreloadPlayer,
    resolveSpeaker,
    seekToLyric,
    shouldShowLyricSubtitle,
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


test('muting the preload player never interrupts active dialogue audio', () => {
    const activePlayer = { muted: false };
    const preloadPlayer = { muted: false };

    mutePreloadPlayer(preloadPlayer, activePlayer);

    assert.equal(activePlayer.muted, false);
    assert.equal(preloadPlayer.muted, true);
});


test('speaker detection keeps the existing character mapping', () => {
    assert.equal(detectSpeaker('Tayama at the store', ''), 'tayama');
    assert.equal(detectSpeaker('scene', '佐佐木回答'), 'sasaki');
    assert.equal(detectSpeaker('scene', '山田走进来'), 'yamada');
    assert.equal(detectSpeaker('scene', 'ordinary dialogue'), 'unknown');
});

test('manual speaker override takes precedence over automatic detection', () => {
    assert.equal(resolveSpeaker('scene', '佐佐木回答'), 'sasaki');
    assert.equal(resolveSpeaker('scene', '佐佐木回答', 'unknown', true), 'unknown');
    assert.equal(resolveSpeaker('scene', '佐佐木回答', 'yamada', true), 'yamada');
});

test('clicking a lyric block seeks the music clock to that lyric', () => {
    const audioPlayer = { currentTime: 0 };

    assert.equal(seekToLyric(audioPlayer, { start: 12.5 }), true);
    assert.equal(audioPlayer.currentTime, 12.5);
});

test('intro timing slots do not render as lyric subtitles', () => {
    assert.equal(shouldShowLyricSubtitle({ text: 'Intro', is_intro: true }), false);
    assert.equal(shouldShowLyricSubtitle({ text: 'Actual lyric' }), true);
});
