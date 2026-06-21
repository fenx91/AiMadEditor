// State variables
let songData = null;
let activeSlotIndex = null;
let timelineSlots = []; // Array of { video_path, video_name, proxy_url, clip_start, clip_duration, frame_url }
let audioEl = new Audio();
let isPlaying = false;
let playheadInterval = null;
let allIndexedVideos = [];
let currentVolume = 0.8;
let isMuted = false;
let lastPreviewSlotIndex = null;
let activePlayer = null;
let preloadPlayer = null;

// DOM elements
const el = {
    indexDirInput: document.getElementById('index-dir-input'),
    indexDirBtn: document.getElementById('index-dir-btn'),
    modelStatus: document.getElementById('model-status'),
    
    audioUploadBox: document.getElementById('audio-upload-box'),
    lyricUploadBox: document.getElementById('lyric-upload-box'),
    audioFileInput: document.getElementById('audio-file-input'),
    lyricFileInput: document.getElementById('lyric-file-input'),
    audioName: document.getElementById('audio-name'),
    lyricName: document.getElementById('lyric-name'),
    processMusicBtn: document.getElementById('process-music-btn'),
    audioTrimmerCard: document.getElementById('audio-trimmer-card'),
    audioTrimStart: document.getElementById('audio-trim-start'),
    audioTrimEnd: document.getElementById('audio-trim-end'),
    trimAudioBtn: document.getElementById('trim-audio-btn'),
    
    lyricsList: document.getElementById('lyrics-list'),
    lyricsCount: document.getElementById('lyrics-count'),
    
    previewPlayerA: document.getElementById('preview-player-a'),
    previewPlayerB: document.getElementById('preview-player-b'),
    videoPlaceholder: document.getElementById('video-placeholder'),
    monitorVideoName: document.getElementById('monitor-video-name'),
    clipTrimmer: document.getElementById('clip-trimmer'),
    trimmerRange: document.getElementById('trimmer-range'),
    trimmerValue: document.getElementById('trimmer-value'),
    trimmerMaxLabel: document.getElementById('trimmer-max-label'),
    
    playBtn: document.getElementById('play-btn'),
    timeDisplay: document.getElementById('time-display'),
    bpmDisplay: document.getElementById('bpm-display'),
    waveformCanvas: document.getElementById('waveform-canvas'),
    timelineRuler: document.getElementById('timeline-ruler'),
    playhead: document.getElementById('playhead'),
    
    lyricTrackItems: document.getElementById('lyric-track-items'),
    videoTrackItems: document.getElementById('video-track-items'),
    
    activeLyricText: document.getElementById('active-lyric-text'),
    activeLyricMeta: document.getElementById('active-lyric-meta'),
    motionPreference: document.getElementById('motion-preference'),
    findMatchesBtn: document.getElementById('find-matches-btn'),
    candidatesList: document.getElementById('candidates-list'),
    candidatesCount: document.getElementById('candidates-count'),
    
    filledSlotsCount: document.getElementById('filled-slots-count'),
    totalSlotsCount: document.getElementById('total-slots-count'),
    estimatedDuration: document.getElementById('estimated-duration'),
    renderBtn: document.getElementById('render-btn'),
    
    modalOverlay: document.getElementById('modal-overlay'),
    modalTitle: document.getElementById('modal-title'),
    modalProgressBar: document.getElementById('modal-progress-bar'),
    modalStatusMsg: document.getElementById('modal-status-msg'),
    modalLogConsole: document.getElementById('modal-log-console'),
    modalFooter: document.getElementById('modal-footer'),
    modalCloseBtn: document.getElementById('modal-close-btn'),
    volumeSlider: document.getElementById('volume-slider'),
    volumeMuteBtn: document.getElementById('volume-mute-btn'),
    clearSlotBtn: document.getElementById('clear-slot-btn'),
    autoMatchAllBtn: document.getElementById('auto-match-all-btn'),
    
    // New Trimmer Controls
    trimmerInput: document.getElementById('trimmer-input'),
    trimBtnSub1s: document.getElementById('trim-btn-sub-1s'),
    trimBtnSub01s: document.getElementById('trim-btn-sub-01s'),
    trimBtnAdd01s: document.getElementById('trim-btn-add-01s'),
    trimBtnAdd1s: document.getElementById('trim-btn-add-1s'),
    
    // New Manual Match Controls
    manualVideoSelect: document.getElementById('manual-video-select'),
    manualClipStart: document.getElementById('manual-clip-start'),
    manualAssignBtn: document.getElementById('manual-assign-btn'),
    searchQueryInput: document.getElementById('search-query-input')
};

// Check backend status and fetch video pool on startup
async function init() {
    try {
        const res = await fetch('/api/videos');
        if (res.ok) {
            allIndexedVideos = await res.json();
            updateModelStatus(true, `已索引 ${allIndexedVideos.length} 个视频`);
            populateManualVideoSelect();
        } else {
            updateModelStatus(false, "后端连接失败");
        }
    } catch (e) {
        updateModelStatus(false, "无法连接后端 API");
    }
    activePlayer = el.previewPlayerA;
    preloadPlayer = el.previewPlayerB;
    setupEventListeners();
    updateVolume(); // Initialize volume levels on startup
    
    // Auto-preload test music and lyrics on startup
    preloadTestData();
}

function updateModelStatus(ok, text) {
    const dot = el.modelStatus.querySelector('.status-dot');
    const txt = el.modelStatus.querySelector('.status-text');
    dot.className = `status-dot ${ok ? 'green' : 'yellow'}`;
    txt.textContent = text;
}

function updateVolume() {
    const targetVolume = isMuted ? 0 : currentVolume;
    audioEl.volume = targetVolume;
    if (el.previewPlayerA) el.previewPlayerA.muted = true; // Ensure the preview video itself is always muted
    if (el.previewPlayerB) el.previewPlayerB.muted = true;
    
    // Update mute button icon
    if (isMuted || targetVolume === 0) {
        el.volumeMuteBtn.textContent = "🔇";
        el.volumeSlider.value = 0;
    } else if (targetVolume < 0.4) {
        el.volumeMuteBtn.textContent = "🔈";
        el.volumeSlider.value = currentVolume;
    } else {
        el.volumeMuteBtn.textContent = "🔊";
        el.volumeSlider.value = currentVolume;
    }
}

function getEffectiveSlot(index) {
    if (!songData) return null;
    if (timelineSlots[index]) {
        return {
            ...timelineSlots[index],
            isFallback: false
        };
    }
    // Find nearest previous filled slot (above source)
    for (let j = index - 1; j >= 0; j--) {
        if (timelineSlots[j]) {
            const baseSlot = timelineSlots[j];
            const currentLyric = songData.lyrics[index];
            const baseLyric = songData.lyrics[j];
            
            let clipStart = baseSlot.clip_start + (currentLyric.start - baseLyric.start);
            const duration = currentLyric.end - currentLyric.start;
            
            if (baseSlot.video_duration && clipStart > baseSlot.video_duration - 0.1) {
                clipStart = Math.max(0, baseSlot.video_duration - 0.1);
            }
            
            return {
                video_path: baseSlot.video_path,
                video_name: baseSlot.video_name,
                proxy_url: baseSlot.proxy_url,
                clip_start: clipStart,
                clip_duration: duration,
                video_duration: baseSlot.video_duration,
                isFallback: true,
                fallbackFromIndex: j
            };
        }
    }
    // If no previous filled slot, find the first filled slot in the entire timeline
    const firstFilled = timelineSlots.find(s => s !== null);
    if (firstFilled) {
        const currentLyric = songData.lyrics[index];
        return {
            video_path: firstFilled.video_path,
            video_name: firstFilled.video_name,
            proxy_url: firstFilled.proxy_url,
            clip_start: firstFilled.clip_start,
            clip_duration: currentLyric.end - currentLyric.start,
            video_duration: firstFilled.video_duration,
            isFallback: true,
            fallbackFromIndex: timelineSlots.indexOf(firstFilled)
        };
    }
    return null;
}

function hasVideoOverlap(cand, index) {
    if (!songData) return false;
    
    const lyric = songData.lyrics[index];
    const duration = lyric.end - lyric.start;
    const candStart = Math.max(0, cand.timestamp);
    const candEnd = candStart + duration;
    
    for (let j = 0; j < songData.lyrics.length; j++) {
        if (j === index) continue;
        
        const eff = getEffectiveSlot(j);
        if (eff && eff.video_path === cand.video_path) {
            const slotStart = eff.clip_start;
            const slotEnd = slotStart + eff.clip_duration;
            
            // Check for 1D interval overlap: candStart < slotEnd && slotStart < candEnd
            if (candStart < slotEnd && slotStart < candEnd) {
                return true; // Overlap detected!
            }
        }
    }
    return false;
}

function refreshTimelineBlocks() {
    if (!songData) return;
    
    for (let i = 0; i < songData.lyrics.length; i++) {
        const block = document.getElementById(`video-track-block-${i}`);
        if (!block) continue;
        
        const slot = timelineSlots[i];
        if (slot) {
            block.className = "track-block video-block";
            if (activeSlotIndex === i) {
                block.classList.add('active');
            }
            block.innerHTML = `<strong>${slot.video_name}</strong> (从 ${slot.clip_start.toFixed(1)}s)`;
            
            const statusText = document.getElementById(`lyric-slot-status-${i}`);
            if (statusText) {
                statusText.className = "lyric-slot-status filled";
                statusText.innerHTML = `🟢 <span>已匹配: ${slot.video_name}</span>`;
            }
            const lyricItem = document.querySelector(`.lyric-item[data-index="${i}"]`);
            if (lyricItem) lyricItem.classList.add('filled');
        } else {
            const effective = getEffectiveSlot(i);
            if (effective) {
                block.className = "track-block video-block fallback";
                if (activeSlotIndex === i) {
                    block.classList.add('active');
                }
                block.innerHTML = `<span class="fallback-label">延续 #${effective.fallbackFromIndex + 1}: ${effective.video_name}</span> (从 ${effective.clip_start.toFixed(1)}s)`;
                
                const statusText = document.getElementById(`lyric-slot-status-${i}`);
                if (statusText) {
                    statusText.className = "lyric-slot-status fallback";
                    statusText.innerHTML = `🔵 <span>延续: ${effective.video_name}</span>`;
                }
                const lyricItem = document.querySelector(`.lyric-item[data-index="${i}"]`);
                if (lyricItem) lyricItem.classList.remove('filled');
            } else {
                block.className = "track-block video-block empty";
                if (activeSlotIndex === i) {
                    block.classList.add('active');
                }
                block.innerHTML = `<em>空槽位</em>`;
                
                const statusText = document.getElementById(`lyric-slot-status-${i}`);
                if (statusText) {
                    statusText.className = "lyric-slot-status";
                    statusText.innerHTML = `<span class="dot-indicator"></span> <span>未匹配素材</span>`;
                }
                const lyricItem = document.querySelector(`.lyric-item[data-index="${i}"]`);
                if (lyricItem) lyricItem.classList.remove('filled');
            }
        }
    }
}

// Setup Event Listeners
function setupEventListeners() {
    // Indexing directory
    el.indexDirBtn.addEventListener('click', indexDirectory);
    
    // File uploads triggers
    el.audioUploadBox.addEventListener('click', () => el.audioFileInput.click());
    el.lyricUploadBox.addEventListener('click', () => el.lyricFileInput.click());
    
    el.audioFileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            el.audioName.textContent = e.target.files[0].name;
            checkProcessButtonState();
        }
    });
    
    el.lyricFileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            el.lyricName.textContent = e.target.files[0].name;
        }
    });
    
    // Drag & Drop
    setupDragAndDrop(el.audioUploadBox, el.audioFileInput, el.audioName);
    setupDragAndDrop(el.lyricUploadBox, el.lyricFileInput, el.lyricName);
    
    // Analyze
    el.processMusicBtn.addEventListener('click', processMusic);
    
    // Playback
    el.playBtn.addEventListener('click', togglePlayback);
    audioEl.addEventListener('timeupdate', updatePlayheadPosition);
    audioEl.addEventListener('ended', () => {
        isPlaying = false;
        el.playBtn.textContent = "▶";
        clearInterval(playheadInterval);
    });
    
    // Trimmer Range
    el.trimmerRange.addEventListener('input', handleTrimmerChange);
    
    // Audio Trimming Button
    el.trimAudioBtn.addEventListener('click', trimMusic);
    
    // Matching triggers
    el.findMatchesBtn.addEventListener('click', findMatches);
    
    // Render
    el.renderBtn.addEventListener('click', renderVideo);
    
    // Click on waveform to seek
    el.waveformCanvas.addEventListener('click', (e) => {
        if (!songData) return;
        const rect = el.waveformCanvas.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const pixelsPerSecond = 20;
        const targetTime = clickX / pixelsPerSecond;
        
        audioEl.currentTime = Math.max(0, Math.min(songData.duration, targetTime));
        updatePlayheadPosition();
        
        // If not playing, update the preview player for this time
        if (!isPlaying) {
            updateGlobalPreview(audioEl.currentTime);
        }
    });
    
    // Modals
    el.modalCloseBtn.addEventListener('click', () => {
        el.modalOverlay.style.display = 'none';
    });
    
    // Volume controls
    el.volumeSlider.addEventListener('input', (e) => {
        currentVolume = parseFloat(e.target.value);
        isMuted = currentVolume === 0;
        updateVolume();
    });
    
    el.volumeMuteBtn.addEventListener('click', () => {
        isMuted = !isMuted;
        updateVolume();
    });
    
    // Unlink and bulk match handlers
    el.clearSlotBtn.addEventListener('click', clearActiveSlot);
    el.autoMatchAllBtn.addEventListener('click', autoMatchAllSlots);

    // Trimmer Numerical Inputs & Adjustment Buttons
    if (el.trimmerInput) {
        el.trimmerInput.addEventListener('input', () => {
            if (activeSlotIndex === null) return;
            const slot = timelineSlots[activeSlotIndex];
            if (!slot) return;
            
            let val = parseFloat(el.trimmerInput.value);
            if (isNaN(val)) return;
            
            const maxStart = Math.max(0, slot.video_duration - slot.clip_duration);
            val = Math.max(0, Math.min(maxStart, val));
            
            slot.clip_start = val;
            el.trimmerRange.value = val;
            el.trimmerValue.textContent = `${val.toFixed(1)}s`;
            
            if (activePlayer) {
                activePlayer.currentTime = val;
            }
            
            refreshTimelineBlocks();
            if (el.manualClipStart) {
                el.manualClipStart.value = parseFloat(val.toFixed(1));
            }
        });
    }
    
    if (el.trimBtnSub1s) el.trimBtnSub1s.addEventListener('click', () => adjustTrimmerTime(-1.0));
    if (el.trimBtnSub01s) el.trimBtnSub01s.addEventListener('click', () => adjustTrimmerTime(-0.1));
    if (el.trimBtnAdd01s) el.trimBtnAdd01s.addEventListener('click', () => adjustTrimmerTime(0.1));
    if (el.trimBtnAdd1s) el.trimBtnAdd1s.addEventListener('click', () => adjustTrimmerTime(1.0));
    
    // Manual Video Selection & Timestamping
    if (el.manualVideoSelect) {
        el.manualVideoSelect.addEventListener('change', () => {
            if (activeSlotIndex === null) {
                el.manualVideoSelect.value = "";
                return alert("请先选择一个歌词卡点槽位！");
            }
            
            const selectedOption = el.manualVideoSelect.options[el.manualVideoSelect.selectedIndex];
            if (!selectedOption || !selectedOption.value) {
                el.manualAssignBtn.setAttribute('disabled', 'true');
                el.manualClipStart.value = "0.0";
                return;
            }
            
            const videoDuration = parseFloat(selectedOption.dataset.duration);
            const lyric = songData.lyrics[activeSlotIndex];
            const lyricDuration = lyric.end - lyric.start;
            const maxStart = Math.max(0, videoDuration - lyricDuration);
            
            el.manualClipStart.max = maxStart;
            
            let currentStart = parseFloat(el.manualClipStart.value) || 0.0;
            if (currentStart > maxStart) {
                currentStart = maxStart;
                el.manualClipStart.value = parseFloat(maxStart.toFixed(1));
            }
            
            el.manualAssignBtn.removeAttribute('disabled');
            
            // Preview the selected video at the selected start time
            const proxyUrl = selectedOption.dataset.proxyUrl;
            el.videoPlaceholder.style.display = 'none';
            el.monitorVideoName.textContent = "[手动选择预看] " + selectedOption.textContent.split(' (')[0];
            switchActivePlayer(proxyUrl, currentStart);
            activePlayer.currentTime = currentStart;
            activePlayer.pause();
        });
    }
    
    if (el.manualClipStart) {
        el.manualClipStart.addEventListener('input', () => {
            if (activeSlotIndex === null) return;
            const selectedOption = el.manualVideoSelect.options[el.manualVideoSelect.selectedIndex];
            if (!selectedOption || !selectedOption.value) return;
            
            const videoDuration = parseFloat(selectedOption.dataset.duration);
            const lyric = songData.lyrics[activeSlotIndex];
            const duration = lyric.end - lyric.start;
            const maxStart = Math.max(0, videoDuration - duration);
            
            let val = parseFloat(el.manualClipStart.value);
            if (isNaN(val)) return;
            
            if (val < 0) {
                val = 0;
                el.manualClipStart.value = "0.0";
            } else if (val > maxStart) {
                val = maxStart;
                el.manualClipStart.value = parseFloat(maxStart.toFixed(1));
            }
            
            // Sync preview player
            if (activePlayer) {
                activePlayer.currentTime = val;
            }
        });
    }
    
    if (el.manualAssignBtn) {
        el.manualAssignBtn.addEventListener('click', manualAssignVideo);
    }
}

function setupDragAndDrop(box, input, display) {
    box.addEventListener('dragover', (e) => {
        e.preventDefault();
        box.style.borderColor = 'var(--color-primary)';
    });
    
    box.addEventListener('dragleave', () => {
        box.style.borderColor = 'var(--border-color)';
    });
    
    box.addEventListener('drop', (e) => {
        e.preventDefault();
        box.style.borderColor = 'var(--border-color)';
        if (e.dataTransfer.files.length > 0) {
            input.files = e.dataTransfer.files;
            display.textContent = e.dataTransfer.files[0].name;
            checkProcessButtonState();
        }
    });
}

function checkProcessButtonState() {
    if (el.audioFileInput.files.length > 0) {
        el.processMusicBtn.removeAttribute('disabled');
    }
}

// Show Modal Console
function showModal(title, initialMsg) {
    el.modalTitle.textContent = title;
    el.modalStatusMsg.textContent = initialMsg;
    el.modalProgressBar.style.width = '0%';
    el.modalLogConsole.textContent = '';
    el.modalFooter.style.display = 'none';
    el.modalOverlay.style.display = 'flex';
}

function updateModalProgress(percent, msg) {
    el.modalProgressBar.style.width = `${percent}%`;
    el.modalStatusMsg.textContent = msg;
}

function appendModalLog(log) {
    el.modalLogConsole.textContent += log + "\n";
    el.modalLogConsole.scrollTop = el.modalLogConsole.scrollHeight;
}

// 1. Index Directory
async function indexDirectory() {
    const dir = el.indexDirInput.value.trim();
    if (!dir) return alert("请输入合法的绝对路径！");
    
    showModal("🔍 索引本地视频中", `扫描目录: ${dir}...`);
    appendModalLog(`开始扫描并索引视频于: ${dir}`);
    appendModalLog(`提取关键帧并使用本地 CLIP 模型推理特征可能需要几分钟，请耐心等待...`);
    
    updateModalProgress(20, "后端解析视频帧特征中...");
    
    try {
        const res = await fetch('/api/index_videos', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ directory: dir })
        });
        
        const data = await res.json();
        if (res.ok) {
            updateModalProgress(100, "索引成功！");
            appendModalLog(`--- 索引完成 ---`);
            appendModalLog(`成功索引的视频总数: ${data.indexed_count}`);
            updateModelStatus(true, `已索引 ${data.indexed_count} 个视频`);
            
            // Reload all indexed videos
            const listRes = await fetch('/api/videos');
            if (listRes.ok) {
                allIndexedVideos = await listRes.json();
                populateManualVideoSelect();
            }
        } else {
            updateModalProgress(100, "索引出错！");
            appendModalLog(`错误原因: ${data.detail}`);
        }
    } catch (e) {
        updateModalProgress(100, "网络异常！");
        appendModalLog(`无法连接服务: ${e.message}`);
    }
    el.modalFooter.style.display = 'block';
}

// 2. Process Music & Lyrics
async function processMusic() {
    const audioFile = el.audioFileInput.files[0];
    const lyricFile = el.lyricFileInput.files[0];
    
    if (!audioFile) return;
    
    showModal("🎵 音频节奏与歌词分析", "正在上传并加载音频...");
    appendModalLog(`上传歌曲: ${audioFile.name}`);
    if (lyricFile) appendModalLog(`上传歌词: ${lyricFile.name}`);
    
    const formData = new FormData();
    formData.append("audio", audioFile);
    if (lyricFile) {
        formData.append("lyric", lyricFile);
    }
    
    updateModalProgress(40, "正在提取 BPM 与瞬态鼓点...");
    
    try {
        const res = await fetch('/api/upload_music', {
            method: 'POST',
            body: formData
        });
        
        const data = await res.json();
        if (res.ok) {
            updateModalProgress(100, "分析完成！");
            appendModalLog(`--- 音频分析完成 ---`);
            appendModalLog(`时长: ${data.duration}s`);
            appendModalLog(`BPM: ${data.bpm}`);
            appendModalLog(`节奏点数: ${data.beats.length}`);
            appendModalLog(`歌词段数: ${data.lyrics.length}`);
            
            songData = data;
            
            // Setup audio player
            audioEl.src = data.audio_url;
            el.playBtn.removeAttribute('disabled');
            el.bpmDisplay.textContent = `BPM: ${data.bpm}`;
            
            // Setup timeline slots
            timelineSlots = new Array(data.lyrics.length).fill(null).map(() => null);
            
            // Draw UI
            renderLyricsList(data.lyrics);
            drawWaveform();
            renderTimelineTracks(data.lyrics);
            
            // Setup Footer Stats
            el.totalSlotsCount.textContent = data.lyrics.length;
            el.filledSlotsCount.textContent = "0";
            el.estimatedDuration.textContent = data.duration.toFixed(1);
            
            // Enable auto-match button
            el.autoMatchAllBtn.removeAttribute('disabled');
            
            // Setup Trimmer UI
            el.audioTrimmerCard.style.display = 'block';
            el.audioTrimStart.value = 0;
            el.audioTrimStart.max = Math.floor(data.duration);
            el.audioTrimEnd.value = Math.floor(data.duration);
            el.audioTrimEnd.max = Math.floor(data.duration);
            
            setTimeout(() => {
                el.modalOverlay.style.display = 'none';
            }, 1000);
        } else {
            updateModalProgress(100, "分析失败！");
            appendModalLog(`错误: ${data.detail}`);
            el.modalFooter.style.display = 'block';
        }
    } catch (e) {
        updateModalProgress(100, "网络异常！");
        appendModalLog(`连接失败: ${e.message}\n${e.stack}`);
        console.error(e);
        el.modalFooter.style.display = 'block';
    }
}

// 2b. Trim Music
async function trimMusic() {
    if (!songData) return;
    
    const startVal = parseFloat(el.audioTrimStart.value);
    const endVal = parseFloat(el.audioTrimEnd.value);
    
    if (isNaN(startVal) || isNaN(endVal) || startVal < 0 || endVal <= startVal) {
        return alert("请输入合法的起始和结束时间！");
    }
    
    showModal("✂️ 音频剪辑进行中", "正在根据指定时间范围截取音频与歌词...");
    appendModalLog(`原始音频: ${songData.audio_path}`);
    appendModalLog(`裁剪区间: ${startVal}s - ${endVal}s (时长: ${(endVal - startVal).toFixed(1)}s)`);
    
    updateModalProgress(40, "正在提取节奏特征与同步歌词...");
    
    try {
        const res = await fetch('/api/trim_music', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                audio_path: songData.audio_path,
                lyric_path: songData.lyric_path,
                start_time: startVal,
                end_time: endVal
            })
        });
        
        const data = await res.json();
        if (res.ok) {
            updateModalProgress(100, "裁剪并重构成功！");
            appendModalLog(`\n--- 音频裁剪分析成功 ---`);
            appendModalLog(`新音频时长: ${data.duration}s`);
            appendModalLog(`BPM: ${data.bpm}`);
            appendModalLog(`重构后卡点数: ${data.lyrics.length}`);
            
            // Clean timelineSlots and selection
            songData = data;
            activeSlotIndex = null;
            timelineSlots = new Array(data.lyrics.length).fill(null).map(() => null);
            
            // Re-render UI
            renderLyricsList(data.lyrics);
            drawWaveform();
            renderTimelineTracks(data.lyrics);
            
            // Update stats
            el.totalSlotsCount.textContent = data.lyrics.length;
            el.filledSlotsCount.textContent = "0";
            el.estimatedDuration.textContent = data.duration.toFixed(1);
            
            // Update trimmer range limit to match new duration
            el.audioTrimStart.value = 0;
            el.audioTrimStart.max = Math.floor(data.duration);
            el.audioTrimEnd.value = Math.floor(data.duration);
            el.audioTrimEnd.max = Math.floor(data.duration);
            
            // Reset preview player
            audioEl.src = data.audio_url;
            el.playBtn.removeAttribute('disabled');
            el.bpmDisplay.textContent = `BPM: ${data.bpm}`;
            
            // Enable auto-match button
            el.autoMatchAllBtn.removeAttribute('disabled');
            
            setTimeout(() => {
                el.modalOverlay.style.display = 'none';
            }, 1000);
        } else {
            updateModalProgress(100, "裁剪失败！");
            appendModalLog(`错误: ${data.detail}`);
            el.modalFooter.style.display = 'block';
        }
    } catch (e) {
        updateModalProgress(100, "网络异常！");
        appendModalLog(`连接失败: ${e.message}\n${e.stack}`);
        el.modalFooter.style.display = 'block';
    }
}

// Draw Waveform and beats ruler
function drawWaveform() {
    if (!songData || !songData.waveform) return;
    
    const canvas = el.waveformCanvas;
    const ctx = canvas.getContext('2d');
    
    // Fit canvas width to container size
    const container = canvas.parentElement;
    // We scale width proportional to song duration to enable horizontal scrolling
    // Say 15 pixels per second of audio
    const pixelsPerSecond = 20;
    const totalWidth = Math.max(container.clientWidth, songData.duration * pixelsPerSecond);
    canvas.width = totalWidth;
    canvas.style.width = `${totalWidth}px`;
    
    // Adjust ruler and tracks width
    document.getElementById('timeline-ruler').style.width = `${totalWidth}px`;
    document.getElementById('lyric-track-items').style.width = `${totalWidth}px`;
    document.getElementById('video-track-items').style.width = `${totalWidth}px`;
    
    const w = canvas.width;
    const h = canvas.height;
    
    ctx.clearRect(0, 0, w, h);
    
    // Draw grid
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.03)';
    ctx.lineWidth = 1;
    for (let x = 0; x < w; x += 50) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
    }
    
    // Draw waveform bars
    const barsCount = songData.waveform.length;
    const barWidth = w / barsCount;
    
    ctx.fillStyle = 'rgba(0, 242, 254, 0.25)'; // Cyan translucent
    for (let i = 0; i < barsCount; i++) {
        const val = songData.waveform[i];
        const barHeight = val * (h - 10);
        const x = i * barWidth;
        const y = (h - barHeight) / 2;
        
        ctx.fillRect(x, y, Math.max(1, barWidth - 1), barHeight);
    }
    
    // Draw Beats
    ctx.strokeStyle = 'rgba(127, 0, 255, 0.4)'; // Purple beats indicator
    ctx.lineWidth = 1.5;
    songData.beats.forEach(beatTime => {
        const x = beatTime * pixelsPerSecond;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
    });
    
    // Draw Timeline ruler numbers
    const ruler = el.timelineRuler;
    ruler.innerHTML = '';
    const step = 5; // Label every 5 seconds
    for (let t = 0; t < songData.duration; t += step) {
        const label = document.createElement('div');
        label.className = 'time-ruler-label';
        label.style.left = `${t * pixelsPerSecond}px`;
        label.style.position = 'absolute';
        label.style.fontSize = '9px';
        label.style.fontFamily = 'var(--font-mono)';
        label.style.color = 'var(--text-muted)';
        
        const m = Math.floor(t / 60);
        const s = Math.floor(t % 60);
        label.textContent = `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
        ruler.appendChild(label);
    }
}

// Playhead sync
function togglePlayback() {
    if (!songData) return;
    
    if (isPlaying) {
        audioEl.pause();
        el.playBtn.textContent = "▶";
        isPlaying = false;
        clearInterval(playheadInterval);
        
        // Pause preview player and restore selected slot preview or current time preview
        pauseBothPlayers();
        if (activeSlotIndex !== null) {
            updatePreviewPlayerForSlot(activeSlotIndex);
        } else {
            updateGlobalPreview(audioEl.currentTime);
        }
    } else {
        audioEl.play();
        el.playBtn.textContent = "⏸";
        isPlaying = true;
        playheadInterval = setInterval(updatePlayheadPosition, 50);
    }
}

function updatePlayheadPosition() {
    if (!songData) return;
    
    const curr = audioEl.currentTime;
    const dur = audioEl.duration || songData.duration;
    
    // Format timer
    el.timeDisplay.textContent = `${formatTime(curr)} / ${formatTime(dur)}`;
    
    // Move visual playhead
    const pixelsPerSecond = 20;
    const playheadPos = curr * pixelsPerSecond;
    el.playhead.style.left = `${playheadPos}px`;
    
    // Update Video Preview Player in Real-Time
    updateGlobalPreview(curr);
    
    // Auto-scroll timeline to follow playhead if playing
    if (isPlaying) {
        const scrollContainer = el.playhead.parentElement.parentElement;
        const containerWidth = scrollContainer.clientWidth;
        const scrollLeft = scrollContainer.scrollLeft;
        
        if (playheadPos > scrollLeft + containerWidth * 0.7) {
            scrollContainer.scrollLeft = playheadPos - containerWidth * 0.3;
        }
    }
}

function updateGlobalPreview(curr) {
    if (!songData) return;
    
    const activeIndex = songData.lyrics.findIndex(l => curr >= l.start && curr < l.end);
    const effective = activeIndex !== -1 ? getEffectiveSlot(activeIndex) : null;
    
    if (effective) {
        // Show video player
        el.videoPlaceholder.style.display = 'none';
        
        let label = effective.video_name;
        if (effective.isFallback) {
            label = `[延续] ${effective.video_name}`;
        }
        el.monitorVideoName.textContent = `[预览模式] ${label}`;
        
        // Ensure active player has target source loaded and is visible
        switchActivePlayer(effective.proxy_url, effective.clip_start);
        
        // Calculate the target time in the video
        const clipTime = effective.clip_start + (curr - songData.lyrics[activeIndex].start);
        
        // Control play/pause & precise sync
        if (isPlaying) {
            if (activePlayer.paused) {
                activePlayer.play().catch(() => {});
                activePlayer.currentTime = clipTime;
            } else {
                const timeDiff = Math.abs(activePlayer.currentTime - clipTime);
                if (timeDiff > 1.0 || activeIndex !== lastPreviewSlotIndex) {
                    activePlayer.currentTime = clipTime;
                }
            }
        } else {
            activePlayer.pause();
            activePlayer.currentTime = clipTime;
        }
        
        // Lookahead and preload the NEXT clip to avoid load stuttering!
        const nextIndex = activeIndex + 1;
        if (nextIndex < songData.lyrics.length) {
            const nextEffective = getEffectiveSlot(nextIndex);
            if (nextEffective && nextEffective.proxy_url !== effective.proxy_url) {
                preloadVideo(nextEffective.proxy_url, nextEffective.clip_start);
            }
        }
        
        lastPreviewSlotIndex = activeIndex;
    } else {
        // Show placeholder if no clip matched
        pauseBothPlayers();
        el.previewPlayerA.style.display = 'none';
        el.previewPlayerB.style.display = 'none';
        el.videoPlaceholder.style.display = 'flex';
        el.monitorVideoName.textContent = "未匹配素材 (空隙)";
        lastPreviewSlotIndex = null;
    }
}

function formatTime(secs) {
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    const ms = Math.floor((secs % 1) * 10);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}.${ms}`;
}

// Render lyrics list & timeline items
function renderLyricsList(lyrics) {
    el.lyricsList.innerHTML = '';
    el.lyricsCount.textContent = `${lyrics.length} 行`;
    
    lyrics.forEach((lyric, index) => {
        const item = document.createElement('div');
        item.className = 'lyric-item';
        item.setAttribute('data-index', index);
        
        item.innerHTML = `
            <div class="lyric-time">[${formatTime(lyric.start)} - ${formatTime(lyric.end)}]</div>
            <div class="lyric-text">${lyric.text}</div>
            <div class="lyric-slot-status" id="lyric-slot-status-${index}">
                <span class="dot-indicator"></span> <span>未匹配素材</span>
            </div>
        `;
        
        item.addEventListener('click', () => selectSlot(index));
        el.lyricsList.appendChild(item);
    });
}

function renderTimelineTracks(lyrics) {
    el.lyricTrackItems.innerHTML = '';
    el.videoTrackItems.innerHTML = '';
    
    const pixelsPerSecond = 20;
    
    lyrics.forEach((lyric, index) => {
        const width = (lyric.end - lyric.start) * pixelsPerSecond;
        const left = lyric.start * pixelsPerSecond;
        
        // Lyric track block
        const lyricBlock = document.createElement('div');
        lyricBlock.className = 'track-block lyric-block';
        lyricBlock.style.left = `${left}px`;
        lyricBlock.style.width = `${width}px`;
        lyricBlock.textContent = lyric.text;
        lyricBlock.setAttribute('data-index', index);
        lyricBlock.addEventListener('click', () => selectSlot(index));
        el.lyricTrackItems.appendChild(lyricBlock);
        
        // Video track block (placeholder)
        const videoBlock = document.createElement('div');
        videoBlock.className = 'track-block video-block empty';
        videoBlock.style.left = `${left}px`;
        videoBlock.style.width = `${width}px`;
        videoBlock.innerHTML = `<em>空槽位</em>`;
        videoBlock.setAttribute('data-index', index);
        videoBlock.id = `video-track-block-${index}`;
        videoBlock.addEventListener('click', () => selectSlot(index));
        el.videoTrackItems.appendChild(videoBlock);
    });
    refreshTimelineBlocks();
}

// Select a Slot (lyric segment)
function selectSlot(index) {
    if (activeSlotIndex !== null) {
        // Deselect previous
        document.querySelector(`.lyric-item[data-index="${activeSlotIndex}"]`)?.classList.remove('active');
        document.querySelector(`.lyric-block[data-index="${activeSlotIndex}"]`)?.classList.remove('active');
        document.querySelector(`.video-block[data-index="${activeSlotIndex}"]`)?.classList.remove('active');
    }
    
    activeSlotIndex = index;
    
    // Mark active in UI
    document.querySelector(`.lyric-item[data-index="${index}"]`)?.classList.add('active');
    document.querySelector(`.lyric-block[data-index="${index}"]`)?.classList.add('active');
    document.querySelector(`.video-block[data-index="${index}"]`)?.classList.add('active');
    
    // Scroll active lyric item into view
    document.querySelector(`.lyric-item[data-index="${index}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    
    // Update AI matching panel details
    const lyric = songData.lyrics[index];
    el.activeLyricText.textContent = lyric.text;
    const dur = lyric.end - lyric.start;
    el.activeLyricMeta.textContent = `时间区间: ${lyric.start.toFixed(1)}s - ${lyric.end.toFixed(1)}s (时长: ${dur.toFixed(1)}s)`;
    
    // Reset/Clear the custom search input on slot change so it doesn't leak
    if (el.searchQueryInput) {
        el.searchQueryInput.value = "";
    }
    
    // Sync manual video and timestamp selection controls
    const slot = timelineSlots[index];
    if (slot) {
        if (el.manualVideoSelect) {
            el.manualVideoSelect.value = slot.video_path;
        }
        if (el.manualClipStart) {
            el.manualClipStart.value = parseFloat(slot.clip_start.toFixed(1));
            const maxStart = Math.max(0, slot.video_duration - slot.clip_duration);
            el.manualClipStart.max = maxStart;
        }
        if (el.manualAssignBtn) {
            el.manualAssignBtn.removeAttribute('disabled');
        }
    } else {
        if (el.manualVideoSelect) {
            el.manualVideoSelect.value = "";
        }
        if (el.manualClipStart) {
            el.manualClipStart.value = "0.0";
            el.manualClipStart.removeAttribute('max');
        }
        if (el.manualAssignBtn) {
            el.manualAssignBtn.setAttribute('disabled', 'true');
        }
    }
    
    // Enable match button
    el.findMatchesBtn.removeAttribute('disabled');
    
    // Clear candidates list, show empty state helper
    el.candidatesList.innerHTML = `<div class="empty-state"><p>点击 "语义匹配此段" 开始匹配</p></div>`;
    
    // Update Monitor / Preview Player
    updatePreviewPlayerForSlot(index);
    
    // Show/hide clear slot button based on whether slot has a source
    if (timelineSlots[index]) {
        el.clearSlotBtn.style.display = 'block';
    } else {
        el.clearSlotBtn.style.display = 'none';
    }
}

// Update monitor player when slot selected or edited
function updatePreviewPlayerForSlot(index) {
    const slot = timelineSlots[index];
    
    if (slot) {
        // Show video player
        el.videoPlaceholder.style.display = 'none';
        el.monitorVideoName.textContent = slot.video_name;
        
        // Trimmer panel
        el.clipTrimmer.style.display = 'block';
        el.trimmerRange.value = slot.clip_start;
        // Limit range. Max start time is video_duration - clip_duration
        const maxStart = Math.max(0, slot.video_duration - slot.clip_duration);
        el.trimmerRange.max = maxStart;
        el.trimmerMaxLabel.textContent = `${maxStart.toFixed(1)}s`;
        el.trimmerValue.textContent = `${slot.clip_start.toFixed(1)}s`;
        
        if (el.trimmerInput) {
            el.trimmerInput.value = parseFloat(slot.clip_start.toFixed(1));
            el.trimmerInput.max = maxStart;
        }
        
        // Load video proxy in active player
        switchActivePlayer(slot.proxy_url, slot.clip_start);
        activePlayer.currentTime = slot.clip_start;
        activePlayer.pause();
    } else {
        // Check if there is a fallback slot
        const effective = getEffectiveSlot(index);
        if (effective) {
            el.videoPlaceholder.style.display = 'none';
            el.monitorVideoName.textContent = `[延续] ${effective.video_name}`;
            
            // Hide trimmer panel (can't trim fallback)
            el.clipTrimmer.style.display = 'none';
            
            switchActivePlayer(effective.proxy_url, effective.clip_start);
            activePlayer.currentTime = effective.clip_start;
            activePlayer.pause();
        } else {
            // Clear trimmer and players
            el.clipTrimmer.style.display = 'none';
            pauseBothPlayers();
            el.previewPlayerA.style.display = 'none';
            el.previewPlayerB.style.display = 'none';
            el.videoPlaceholder.style.display = 'flex';
            el.monitorVideoName.textContent = "未加载素材";
            
            el.previewPlayerA.removeAttribute('src');
            el.previewPlayerA.removeAttribute('data-current-src');
            el.previewPlayerB.removeAttribute('src');
            el.previewPlayerB.removeAttribute('data-current-src');
        }
    }
}

// Trigger trimmer slide change
function handleTrimmerChange() {
    if (activeSlotIndex === null) return;
    const slot = timelineSlots[activeSlotIndex];
    if (!slot) return;
    
    const val = parseFloat(el.trimmerRange.value);
    slot.clip_start = val;
    el.trimmerValue.textContent = `${val.toFixed(1)}s`;
    
    if (el.trimmerInput) {
        el.trimmerInput.value = parseFloat(val.toFixed(1));
    }
    if (el.manualClipStart) {
        el.manualClipStart.value = parseFloat(val.toFixed(1));
    }
    
    // Seek active player to see frame
    if (activePlayer) {
        activePlayer.currentTime = val;
    }
    
    // Refresh all timeline blocks since a change in start time affects downstream fallbacks
    refreshTimelineBlocks();
}

// 3. AI Matches Query
async function findMatches() {
    if (activeSlotIndex === null || !songData) return;
    
    const lyric = songData.lyrics[activeSlotIndex];
    let text = el.searchQueryInput && el.searchQueryInput.value.trim() ? el.searchQueryInput.value.trim() : lyric.text;
    const motion = el.motionPreference.value;
    
    el.candidatesList.innerHTML = `
        <div class="spinner-container" style="padding: 20px 0;">
            <div class="double-bounce1"></div>
            <div class="double-bounce2"></div>
        </div>
        <p style="font-size:11px; text-align:center; color:var(--text-secondary);">AI 语义特征向量比对中...</p>
    `;
    
    try {
        const res = await fetch('/api/match', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                lyric_text: text,
                motion_preference: motion,
                limit: 5
            })
        });
        
        const candidates = await res.json();
        if (res.ok) {
            renderCandidatesList(candidates);
        } else {
            el.candidatesList.innerHTML = `<div class="empty-state"><p>匹配失败: ${candidates.detail}</p></div>`;
        }
    } catch (e) {
        el.candidatesList.innerHTML = `<div class="empty-state"><p>请求失败: ${e.message}</p></div>`;
    }
}

function renderCandidatesList(candidates) {
    el.candidatesList.innerHTML = '';
    el.candidatesCount.textContent = `Top ${candidates.length}`;
    
    if (candidates.length === 0) {
        el.candidatesList.innerHTML = `<div class="empty-state"><p>未找到符合条件的视频素材，请先索引视频。</p></div>`;
        return;
    }
    
    candidates.forEach((cand, idx) => {
        const card = document.createElement('div');
        card.className = 'candidate-card';
        
        const scorePct = Math.round(cand.similarity * 100);
        const fileName = cand.video_path.split('/').pop();
        
        card.innerHTML = `
            <div class="cand-badge">#${idx+1} Match</div>
            <div class="candidate-thumbnail">
                <img src="${cand.frame_url}" alt="keyframe" />
            </div>
            <div class="candidate-meta">
                <div class="cand-name" title="${fileName}">${fileName}</div>
                <div class="cand-stats">
                    <span class="cand-score">${scorePct}% 匹配度</span>
                    <span class="cand-motion">运动度: ${cand.motion_score.toFixed(1)}</span>
                </div>
                <div class="cand-stats">
                    <span class="cand-time">定位点: ${cand.timestamp.toFixed(1)}s</span>
                    <button class="btn btn-primary" style="font-size:10px; padding:3px 8px; border-radius:4px;">采用</button>
                </div>
            </div>
        `;
        
        // Clicking card previews the proxy video starting at the keyframe time
        card.addEventListener('click', (e) => {
            if (e.target.tagName !== 'BUTTON') {
                el.videoPlaceholder.style.display = 'none';
                el.monitorVideoName.textContent = fileName;
                
                switchActivePlayer(cand.proxy_url, Math.max(0, cand.timestamp));
                activePlayer.currentTime = Math.max(0, cand.timestamp);
                activePlayer.play().catch(() => {});
            }
        });
        
        // Clicking "Use" button assigns the candidate to the active slot
        card.querySelector('button').addEventListener('click', () => {
            assignCandidateToActiveSlot(cand);
        });
        
        el.candidatesList.appendChild(card);
    });
}

function assignCandidateToActiveSlot(cand) {
    if (activeSlotIndex === null || !songData) return;
    
    const lyric = songData.lyrics[activeSlotIndex];
    const duration = lyric.end - lyric.start;
    const fileName = cand.video_path.split('/').pop();
    
    // Place video such that the detected keyframe is near the start
    // clip_start starts at keyframe timestamp, but make sure we don't exceed video duration
    const clip_start = Math.max(0, cand.timestamp);
    
    timelineSlots[activeSlotIndex] = {
        video_path: cand.video_path,
        video_name: fileName,
        proxy_url: cand.proxy_url,
        clip_start: clip_start,
        clip_duration: duration,
        video_duration: cand.duration
    };
    
    // Refresh all blocks on the timeline
    refreshTimelineBlocks();
    
    // Update Monitor / Previews
    updatePreviewPlayerForSlot(activeSlotIndex);
    
    // Show clear slot button since it's now filled
    el.clearSlotBtn.style.display = 'block';
    
    // Update global timeline filled counters
    updateFooterStats();
}

function updateFooterStats() {
    const filledCount = timelineSlots.filter(s => s !== null).length;
    el.filledSlotsCount.textContent = filledCount;
    
    if (filledCount > 0) {
        el.renderBtn.removeAttribute('disabled');
    } else {
        el.renderBtn.setAttribute('disabled', 'true');
    }
}

function clearActiveSlot() {
    if (activeSlotIndex === null) return;
    
    timelineSlots[activeSlotIndex] = null;
    
    // Refresh timeline blocks and footer stats
    refreshTimelineBlocks();
    updateFooterStats();
    
    // Update monitor preview
    updatePreviewPlayerForSlot(activeSlotIndex);
    
    // Hide clear slot button
    el.clearSlotBtn.style.display = 'none';
}

async function autoMatchAllSlots() {
    if (!songData) return;
    
    showModal("🤖 一键智能卡点匹配", "正在分析所有卡点并匹配最佳画面...");
    appendModalLog(`开始对 ${songData.lyrics.length} 个卡点执行智能匹配...`);
    
    const motion = el.motionPreference.value;
    let successCount = 0;
    
    for (let i = 0; i < songData.lyrics.length; i++) {
        const lyric = songData.lyrics[i];
        
        // Skip slots that are already filled to preserve user's choices
        if (timelineSlots[i] !== null) {
            appendModalLog(`卡点 #${i+1} [已存在素材]: 跳过`);
            continue;
        }
        
        const progressPct = Math.round((i / songData.lyrics.length) * 100);
        updateModalProgress(progressPct, `正在匹配卡点 #${i+1}/${songData.lyrics.length}: "${lyric.text}"`);
        
        // Collect video paths of the previous 4 slots to avoid repeats
        const recentlyUsedPaths = [];
        const lookbackWindow = 4;
        for (let j = Math.max(0, i - lookbackWindow); j < i; j++) {
            const eff = getEffectiveSlot(j);
            if (eff && eff.video_path) {
                recentlyUsedPaths.push(eff.video_path);
            }
        }
        
        try {
            const res = await fetch('/api/match', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    lyric_text: lyric.text,
                    motion_preference: motion,
                    limit: 5 // Get top 5 matches to allow deduplication fallback
                })
            });
            
            if (res.ok) {
                const candidates = await res.json();
                if (candidates && candidates.length > 0) {
                    // Find the best candidate based on tiered matching rules:
                    let selectedCand = null;
                    
                    // Tier 1: No overlap AND not recently used in sliding lookback window
                    for (const cand of candidates) {
                        if (!recentlyUsedPaths.includes(cand.video_path) && !hasVideoOverlap(cand, i)) {
                            selectedCand = cand;
                            break;
                        }
                    }
                    
                    // Tier 2: No overlap (allow adjacent repeat if playing separate non-overlapping frames)
                    if (!selectedCand) {
                        for (const cand of candidates) {
                            if (!hasVideoOverlap(cand, i)) {
                                selectedCand = cand;
                                appendModalLog(`卡点 #${i+1}: 采用最近使用的视频，但选择无画面重叠的片段`);
                                break;
                            }
                        }
                    }
                    
                    // Tier 3: Fallback to absolute best match if all candidates overlap
                    if (!selectedCand) {
                        selectedCand = candidates[0];
                        appendModalLog(`卡点 #${i+1}: 所有候选画面均有时间轴重叠，执行首选兜底`);
                    }
                    
                    const duration = lyric.end - lyric.start;
                    const fileName = selectedCand.video_path.split('/').pop();
                    const clip_start = Math.max(0, selectedCand.timestamp);
                    
                    timelineSlots[i] = {
                        video_path: selectedCand.video_path,
                        video_name: fileName,
                        proxy_url: selectedCand.proxy_url,
                        clip_start: clip_start,
                        clip_duration: duration,
                        video_duration: selectedCand.duration
                    };
                    successCount++;
                    appendModalLog(`卡点 #${i+1} 匹配成功: -> ${fileName} (从 ${clip_start.toFixed(1)}s)`);
                } else {
                    appendModalLog(`卡点 #${i+1} 匹配失败: 视频库中未找到候选片段`);
                }
            } else {
                appendModalLog(`卡点 #${i+1} 匹配错误: 服务器返回 ${res.status}`);
            }
        } catch (e) {
            appendModalLog(`卡点 #${i+1} 匹配异常: ${e.message}`);
        }
    }
    
    updateModalProgress(100, `智能匹配完成！成功填充 ${successCount} 个卡点`);
    appendModalLog(`--- 一键智能匹配完成 ---`);
    appendModalLog(`成功匹配: ${successCount} 个卡点`);
    
    // Refresh timeline and footer stats
    refreshTimelineBlocks();
    updateFooterStats();
    
    // If a slot is currently active, update its preview
    if (activeSlotIndex !== null) {
        updatePreviewPlayerForSlot(activeSlotIndex);
        
        // Update cancel button visibility
        if (timelineSlots[activeSlotIndex]) {
            el.clearSlotBtn.style.display = 'block';
        } else {
            el.clearSlotBtn.style.display = 'none';
        }
    }
    
    el.modalFooter.style.display = 'block';
}

// 4. Render Video
async function renderVideo() {
    if (timelineSlots.filter(s => s !== null).length === 0) return;
    if (!songData) return;
    
    // Build JSON data payload
    // Filter only filled slots or fill empty slots with a placeholder loop
    const slotsPayload = [];
    
    for (let i = 0; i < songData.lyrics.length; i++) {
        const lyric = songData.lyrics[i];
        const effective = getEffectiveSlot(i);
        
        if (effective) {
            slotsPayload.push({
                start_time: lyric.start,
                end_time: lyric.end,
                video_path: effective.video_path,
                clip_start: effective.clip_start,
                clip_duration: lyric.end - lyric.start
            });
        }
    }
    
    showModal("🎬 HyperFrames 渲染出片中", "组装剪辑脚本工程并导出视频帧...");
    appendModalLog(`开始构建 HyperFrames 剪辑项目...`);
    appendModalLog(`卡点个数: ${slotsPayload.length}`);
    appendModalLog(`音频背景轨: ${songData.audio_path}`);
    
    updateModalProgress(30, "正在生成 HyperFrames HTML 模板...");
    
    try {
        const res = await fetch('/api/render', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                slots: slotsPayload,
                audio_path: songData.audio_path
            })
        });
        
        const data = await res.json();
        if (res.ok) {
            updateModalProgress(100, "渲染成功！");
            appendModalLog(`\n--- 渲染出片成功 ---`);
            appendModalLog(`输出绝对路径: ${data.output_path}`);
            appendModalLog(`预览链接: ${data.output_url}`);
            
            // Preview the output MP4 in monitor player!
            el.videoPlaceholder.style.display = 'none';
            el.monitorVideoName.textContent = "MV_Output.mp4";
            
            switchActivePlayer(data.output_url, 0);
            activePlayer.currentTime = 0;
            activePlayer.play().catch(() => {});
        } else {
            updateModalProgress(100, "渲染发生错误！");
            appendModalLog(`\n--- 渲染异常终端信息 ---`);
            appendModalLog(`执行指令: ${data.cmd || ''}`);
            appendModalLog(`错误原因: ${data.detail}`);
        }
    } catch (e) {
        updateModalProgress(100, "网络通信异常！");
        appendModalLog(`连接渲染端发生错误: ${e.message}`);
    }
    el.modalFooter.style.display = 'block';
}

// --- New Helper Functions for Manual and Dual Player Control ---

// Populates manual video select dropdown from allIndexedVideos
function populateManualVideoSelect() {
    if (!el.manualVideoSelect) return;
    
    el.manualVideoSelect.innerHTML = '<option value="">-- 请选择索引库中的视频 --</option>';
    allIndexedVideos.forEach(vid => {
        const option = document.createElement('option');
        option.value = vid.original_path;
        const fileName = vid.original_path.split('/').pop();
        option.textContent = `${fileName} (${vid.duration.toFixed(1)}s)`;
        option.dataset.proxyUrl = vid.proxy_url;
        option.dataset.duration = vid.duration;
        el.manualVideoSelect.appendChild(option);
    });
}

// Adjusts the clip trimmer start time by a step value (amount)
function adjustTrimmerTime(amount) {
    if (activeSlotIndex === null) return;
    const slot = timelineSlots[activeSlotIndex];
    if (!slot) return;
    
    let val = slot.clip_start + amount;
    const maxStart = Math.max(0, slot.video_duration - slot.clip_duration);
    val = Math.max(0, Math.min(maxStart, val));
    
    slot.clip_start = val;
    el.trimmerRange.value = val;
    el.trimmerValue.textContent = `${val.toFixed(1)}s`;
    
    if (el.trimmerInput) {
        el.trimmerInput.value = parseFloat(val.toFixed(1));
    }
    if (el.manualClipStart) {
        el.manualClipStart.value = parseFloat(val.toFixed(1));
    }
    
    if (activePlayer) {
        activePlayer.currentTime = val;
    }
    
    refreshTimelineBlocks();
}

// Manually assigns the chosen video and start timestamp to the active slot
function manualAssignVideo() {
    if (activeSlotIndex === null || !songData) return;
    
    const selectedOption = el.manualVideoSelect.options[el.manualVideoSelect.selectedIndex];
    if (!selectedOption || !selectedOption.value) {
        return alert("请先选择一个视频素材！");
    }
    
    const videoPath = selectedOption.value;
    const proxyUrl = selectedOption.dataset.proxyUrl;
    const videoDuration = parseFloat(selectedOption.dataset.duration);
    
    const lyric = songData.lyrics[activeSlotIndex];
    const duration = lyric.end - lyric.start;
    
    let clipStart = parseFloat(el.manualClipStart.value);
    if (isNaN(clipStart) || clipStart < 0) {
        clipStart = 0;
    }
    
    const maxStart = Math.max(0, videoDuration - duration);
    clipStart = Math.min(maxStart, clipStart);
    
    const fileName = videoPath.split('/').pop();
    
    timelineSlots[activeSlotIndex] = {
        video_path: videoPath,
        video_name: fileName,
        proxy_url: proxyUrl,
        clip_start: clipStart,
        clip_duration: duration,
        video_duration: videoDuration
    };
    
    // Refresh timeline blocks, stats, and monitor preview
    refreshTimelineBlocks();
    updateFooterStats();
    updatePreviewPlayerForSlot(activeSlotIndex);
    
    el.clearSlotBtn.style.display = 'block';
}

// Dual Player Preloader & Switcher
function switchActivePlayer(targetSrc, targetTime) {
    if (!activePlayer || !preloadPlayer) return;
    
    let nextActive = null;
    let nextPreload = null;
    
    if (el.previewPlayerA.dataset.currentSrc === targetSrc) {
        nextActive = el.previewPlayerA;
        nextPreload = el.previewPlayerB;
    } else if (el.previewPlayerB.dataset.currentSrc === targetSrc) {
        nextActive = el.previewPlayerB;
        nextPreload = el.previewPlayerA;
    } else {
        // Neither has it loaded, load it on the current active player
        nextActive = activePlayer;
        nextPreload = preloadPlayer;
        
        nextActive.src = targetSrc;
        nextActive.dataset.currentSrc = targetSrc;
        nextActive.load();
    }
    
    // Switch active player references if needed
    if (nextActive !== activePlayer) {
        activePlayer.pause();
        activePlayer.style.display = 'none';
        
        activePlayer = nextActive;
        preloadPlayer = nextPreload;
        
        activePlayer.style.display = 'block';
    } else {
        activePlayer.style.display = 'block';
        preloadPlayer.style.display = 'none';
    }
    
    activePlayer.muted = true;
    preloadPlayer.muted = true;
}

function pauseBothPlayers() {
    if (el.previewPlayerA) el.previewPlayerA.pause();
    if (el.previewPlayerB) el.previewPlayerB.pause();
}

function preloadVideo(src, time) {
    if (!src || !preloadPlayer || !activePlayer) return;
    if (activePlayer.dataset.currentSrc === src) return;
    
    if (preloadPlayer.dataset.currentSrc !== src) {
        preloadPlayer.src = src;
        preloadPlayer.dataset.currentSrc = src;
        preloadPlayer.load();
        preloadPlayer.currentTime = time;
        preloadPlayer.muted = true;
    } else {
        // Already loaded, just make sure it seeks to preload time
        if (Math.abs(preloadPlayer.currentTime - time) > 0.5) {
            preloadPlayer.currentTime = time;
        }
    }
}

async function preloadTestData() {
    try {
        console.log("Preloading test data...");
        // Show status in UI or upload labels
        el.audioName.textContent = "Adam Lambert - Whataya Want from Me_H.mp3 (加载中...)";
        el.lyricName.textContent = "Adam Lambert - Whataya Want from Me_H.lrc (加载中...)";
        
        const res = await fetch('/api/load_test_data', { method: 'POST' });
        if (res.ok) {
            const data = await res.json();
            songData = data;
            
            // Setup audio player
            audioEl.src = data.audio_url;
            el.playBtn.removeAttribute('disabled');
            el.bpmDisplay.textContent = `BPM: ${data.bpm}`;
            
            // Setup timeline slots
            timelineSlots = new Array(data.lyrics.length).fill(null).map(() => null);
            
            // Draw UI
            renderLyricsList(data.lyrics);
            drawWaveform();
            renderTimelineTracks(data.lyrics);
            
            // Setup Footer Stats
            el.totalSlotsCount.textContent = data.lyrics.length;
            el.filledSlotsCount.textContent = "0";
            el.estimatedDuration.textContent = data.duration.toFixed(1);
            
            // Enable auto-match button
            el.autoMatchAllBtn.removeAttribute('disabled');
            
            // Setup Trimmer UI
            el.audioTrimmerCard.style.display = 'block';
            el.audioTrimStart.value = 0;
            el.audioTrimStart.max = Math.floor(data.duration);
            el.audioTrimEnd.value = Math.floor(data.duration);
            el.audioTrimEnd.max = Math.floor(data.duration);
            
            el.audioName.textContent = "Adam Lambert - Whataya Want from Me_H.mp3 (已预载)";
            el.lyricName.textContent = "Adam Lambert - Whataya Want from Me_H.lrc (已预载)";
            console.log("Test data preloaded successfully!");
        } else {
            console.warn("Failed to preload test data");
            el.audioName.textContent = "未选择文件";
            el.lyricName.textContent = "未选择文件";
        }
    } catch (e) {
        console.error("Error preloading test data:", e);
        el.audioName.textContent = "未选择文件";
        el.lyricName.textContent = "未选择文件";
    }
}

// Start everything
window.addEventListener('DOMContentLoaded', init);
