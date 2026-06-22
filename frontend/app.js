// Global error logging for debugging
window.addEventListener('error', (e) => {
    alert(`JS Error: ${e.message} at ${e.filename}:${e.lineno}:${e.colno}`);
});
window.addEventListener('unhandledrejection', (e) => {
    alert(`Unhandled Promise Rejection: ${e.reason}`);
});

function browserLog(msg) {
    const consoleDiv = document.getElementById('browser-debug-console');
    if (consoleDiv) {
        consoleDiv.textContent += `\n[${new Date().toLocaleTimeString()}] ${msg}`;
        consoleDiv.scrollTop = consoleDiv.scrollHeight;
    }
    console.log("[BrowserDebug]", msg);
}

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
let scriptPlan = null;
let currentBrowserVideoId = null;
let currentBrowserTranscripts = [];
let currentBrowserSegments = [];
let currentBrowserTab = 'transcripts';

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
    searchQueryInput: document.getElementById('search-query-input'),
    
    // Tabbed Script Planner Controls
    tabPlannerBtn: document.getElementById('tab-planner-btn'),
    tabMatcherBtn: document.getElementById('tab-matcher-btn'),
    panelPlannerContent: document.getElementById('panel-planner-content'),
    panelMatcherContent: document.getElementById('panel-matcher-content'),
    userVisionInput: document.getElementById('user-vision-input'),
    generateScriptBtn: document.getElementById('generate-script-btn'),
    regenerateScriptBtn: document.getElementById('regenerate-script-btn'),
    scriptStatusBadge: document.getElementById('script-status-badge'),
    scriptLinesList: document.getElementById('script-lines-list'),
    applyScriptContainer: document.getElementById('apply-script-container'),
    applyScriptBtn: document.getElementById('apply-script-btn'),
    scriptHighLevelPanel: document.getElementById('script-high-level-panel'),
    toggleHighLevelBtn: document.getElementById('toggle-high-level-btn'),
    highLevelContent: document.getElementById('high-level-content'),
    
    // Recommended story vision elements
    recommendedVisionsContainer: document.getElementById('recommended-visions-container'),
    recommendedVisionsList: document.getElementById('recommended-visions-list'),
    visionsLoading: document.getElementById('visions-loading'),
    
    // Modal Cancel Buttons
    modalRunningActions: document.getElementById('modal-running-actions'),
    modalCancelBtn: document.getElementById('modal-cancel-btn'),
    
    // Video Browser Modal Controls
    videoBrowserModal: document.getElementById('video-browser-modal'),
    videoBrowserCloseBtn: document.getElementById('video-browser-close-btn'),
    browserVideoList: document.getElementById('browser-video-list'),
    browserPreviewPlayer: document.getElementById('browser-preview-player'),
    browserPlayerPlaceholder: document.getElementById('browser-player-placeholder'),
    browserTranscriptCount: document.getElementById('browser-transcript-count'),
    browserTranscriptList: document.getElementById('browser-transcript-list')
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
    // Dynamically sync active preview player's volume and muted state based on keep_audio status
    if (activePlayer) {
        let shouldKeepAudio = false;
        if (isPlaying) {
            const curr = audioEl.currentTime;
            if (songData) {
                const activeIndex = songData.lyrics.findIndex(l => curr >= l.start && curr < l.end);
                const effective = activeIndex !== -1 ? getEffectiveSlot(activeIndex) : null;
                if (effective && !effective.isFallback && effective.keep_audio) {
                    shouldKeepAudio = true;
                }
            }
        } else {
            if (activeSlotIndex !== null && timelineSlots[activeSlotIndex]) {
                if (timelineSlots[activeSlotIndex].keep_audio) {
                    shouldKeepAudio = true;
                }
            }
        }
        
        if (shouldKeepAudio && !isMuted) {
            activePlayer.muted = false;
            activePlayer.volume = targetVolume * 0.8;
        } else {
            activePlayer.muted = true;
        }
    }
    if (preloadPlayer) preloadPlayer.muted = true;
    
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
            const micBadge = slot.keep_audio ? '<span class="mic-badge" style="font-size: 10px; margin-right: 4px; padding: 1px 3px; background: rgba(0, 242, 254, 0.2); border: 1px solid rgba(0, 242, 254, 0.4); border-radius: 3px;" title="已启用原声混合">🎙️</span>' : '';
            block.innerHTML = `${micBadge}<strong>${slot.video_name}</strong> (从 ${slot.clip_start.toFixed(1)}s)`;
            
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

    // Video Browser Modal event handlers
    el.modelStatus.addEventListener('click', openVideoBrowser);
    el.videoBrowserCloseBtn.addEventListener('click', closeVideoBrowser);
    el.videoBrowserModal.addEventListener('click', (e) => {
        if (e.target === el.videoBrowserModal) {
            closeVideoBrowser();
        }
    });

    // Video Browser Tabs
    const tabTranscriptsBtn = document.getElementById('browser-tab-transcripts-btn');
    const tabSegmentsBtn = document.getElementById('browser-tab-segments-btn');
    if (tabTranscriptsBtn) {
        tabTranscriptsBtn.addEventListener('click', () => switchBrowserTab('transcripts'));
    }
    if (tabSegmentsBtn) {
        tabSegmentsBtn.addEventListener('click', () => switchBrowserTab('segments'));
    }

    // Event delegation for browser video list clicks
    const browserVideoList = document.getElementById('browser-video-list');
    if (browserVideoList) {
        browserVideoList.addEventListener('click', async (e) => {
            const item = e.target.closest('.browser-video-item');
            browserLog(`browser-video-list click event captured. Target tag: <${e.target.tagName}>, classes: "${e.target.className}", item found: ${item ? "yes" : "no"}`);
            if (!item) return;
            
            const index = Array.from(browserVideoList.querySelectorAll('.browser-video-item')).indexOf(item);
            browserLog(`Clicked video item index: ${index}`);
            if (index === -1) return;
            
            const video = allIndexedVideos[index];
            if (!video) {
                browserLog("ERROR: No video object found in allIndexedVideos for index " + index);
                return;
            }
            
            try {
                // Clear active styles from all video items
                browserVideoList.querySelectorAll('.browser-video-item').forEach(elItem => {
                    elItem.classList.remove('active');
                    elItem.style.background = 'rgba(255, 255, 255, 0.02)';
                    elItem.style.borderColor = 'var(--border-color)';
                    elItem.style.color = 'var(--text-secondary)';
                    elItem.style.boxShadow = 'none';
                });
                
                // Set active styles for the clicked item
                item.classList.add('active');
                item.style.background = 'rgba(0, 242, 254, 0.1)';
                item.style.borderColor = 'var(--color-primary)';
                item.style.color = '#fff';
                item.style.boxShadow = '0 0 8px rgba(0, 242, 254, 0.15)';
                
                browserLog(`Triggering selectBrowserVideo for ID: ${video.id}`);
                await selectBrowserVideo(video);
            } catch (err) {
                browserLog("EXCEPTION inside video list click handler: " + err.message);
                alert("选择视频出错: " + err.message);
            }
        });
    }

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
    
    // Tab switching event listeners
    if (el.tabPlannerBtn && el.tabMatcherBtn) {
        el.tabPlannerBtn.addEventListener('click', () => switchTab('planner'));
        el.tabMatcherBtn.addEventListener('click', () => switchTab('matcher'));
    }
    
    // Generate script plan
    if (el.generateScriptBtn) {
        el.generateScriptBtn.addEventListener('click', () => generateScriptPlan(false));
    }
    
    // Reset cache and regenerate
    if (el.regenerateScriptBtn) {
        el.regenerateScriptBtn.addEventListener('click', () => generateScriptPlan(true));
    }
    
    // Apply script plan
    if (el.applyScriptBtn) {
        el.applyScriptBtn.addEventListener('click', applyScriptAndMatchAll);
    }
    
    // Toggle high level story panel visibility
    if (el.toggleHighLevelBtn && el.highLevelContent) {
        el.toggleHighLevelBtn.addEventListener('click', () => {
            const isHidden = el.highLevelContent.style.display === 'none';
            if (isHidden) {
                el.highLevelContent.style.display = 'flex';
                el.toggleHighLevelBtn.textContent = '收起';
            } else {
                el.highLevelContent.style.display = 'none';
                el.toggleHighLevelBtn.textContent = '展开';
            }
        });
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

async function indexDirectory() {
    const dir = el.indexDirInput.value.trim();
    if (!dir) return alert("请输入合法的绝对路径！");
    
    showModal("🔍 索引本地视频中", `扫描目录: ${dir}...`);
    appendModalLog(`开始扫描并索引视频于: ${dir}`);
    appendModalLog(`提取关键帧并使用本地 CLIP 模型推理特征可能需要几分钟，请耐心等待...`);

    const forceRefreshCheckbox = document.getElementById('force-refresh-cache');
    const forceRefresh = forceRefreshCheckbox ? forceRefreshCheckbox.checked : false;
    
    if (forceRefresh) {
        appendModalLog(`提示：用户开启了“强制刷新缓存”，将清空该目录下的数据库缓存并完全重做索引特征与转写。`);
    }
    
    updateModalProgress(20, "后端解析视频帧特征中...");
    
    try {
        const res = await fetch('/api/index_videos', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ directory: dir, force_refresh: forceRefresh })
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
            if (el.generateScriptBtn) el.generateScriptBtn.removeAttribute('disabled');
            if (el.regenerateScriptBtn) el.regenerateScriptBtn.removeAttribute('disabled');
            
            // Fetch AI story vision recommendations based on lyrics and DB video content
            fetchStoryVisionRecommendations();
            
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
            if (el.generateScriptBtn) el.generateScriptBtn.removeAttribute('disabled');
            if (el.regenerateScriptBtn) el.regenerateScriptBtn.removeAttribute('disabled');
            
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
        
        // Sync unmuting based on keep_audio
        const targetVolume = isMuted ? 0 : currentVolume;
        if (effective.keep_audio && !effective.isFallback && !isMuted) {
            activePlayer.muted = false;
            activePlayer.volume = targetVolume * 0.8;
        } else {
            activePlayer.muted = true;
        }
        
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
        if (scriptPlan && scriptPlan[index]) {
            el.searchQueryInput.placeholder = `AI大纲提示词: ${scriptPlan[index].visual_prompt}`;
            if (el.motionPreference && scriptPlan[index].motion_preference) {
                el.motionPreference.value = scriptPlan[index].motion_preference;
            }
        } else {
            el.searchQueryInput.placeholder = "留空默认使用当前歌词语义进行匹配...";
        }
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
        
        // Sync unmuting based on keep_audio
        const targetVolume = isMuted ? 0 : currentVolume;
        if (slot.keep_audio && !isMuted) {
            activePlayer.muted = false;
            activePlayer.volume = targetVolume * 0.8;
        } else {
            activePlayer.muted = true;
        }
        
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
            activePlayer.muted = true; // Fallbacks are always muted
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
    let text = el.searchQueryInput && el.searchQueryInput.value.trim() ? el.searchQueryInput.value.trim() : null;
    if (!text) {
        if (scriptPlan && scriptPlan[activeSlotIndex] && scriptPlan[activeSlotIndex].visual_prompt) {
            text = scriptPlan[activeSlotIndex].visual_prompt;
        } else {
            text = lyric.text;
        }
    }
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
                limit: 5,
                lyric: lyric ? lyric.text : "",
                narrative_concept: (scriptPlan && scriptPlan[activeSlotIndex]) ? (scriptPlan[activeSlotIndex].narrative_concept || "") : "",
                emotional_tone: (scriptPlan && scriptPlan[activeSlotIndex]) ? (scriptPlan[activeSlotIndex].emotional_tone || "") : ""
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
        card.style.cssText = "display: flex; flex-direction: column; gap: 6px; padding: 10px;";
        
        const scorePct = Math.round(cand.similarity * 100);
        const fileName = cand.video_path.split('/').pop();
        const hasSeg = !!cand.segment;
        
        card.innerHTML = `
            <div style="display: flex; gap: 10px; width: 100%; align-items: flex-start; justify-content: space-between; position: relative;">
                <div class="cand-badge" style="position: static; margin-bottom: 4px;">#${idx+1} Match</div>
                ${hasSeg ? `
                <div class="ai-badge" style="font-size: 9px; padding: 2px 6px; background: linear-gradient(135deg, #00f2fe 0%, #4facfe 100%); color: #000; border-radius: 4px; font-weight: bold; cursor: pointer; display: flex; align-items: center; gap: 2px;" title="Gemini 多模态深度场景分析已生成">
                    ✨ AI 场景
                </div>
                ` : ''}
            </div>
            
            <div style="display: flex; gap: 10px; width: 100%; align-items: center;">
                <div class="candidate-thumbnail">
                    <img src="${cand.frame_url}" alt="keyframe" />
                </div>
                <div class="candidate-meta" style="flex: 1; min-width: 0;">
                    <div class="cand-name" title="${fileName}">${fileName}</div>
                    <div class="cand-stats">
                        <span class="cand-score">${scorePct}% 匹配度</span>
                        <span class="cand-motion">运动度: ${cand.motion_score.toFixed(1)}</span>
                    </div>
                    <div class="cand-stats">
                        <span class="cand-time">定位点: ${cand.timestamp.toFixed(1)}s</span>
                        <div style="display: flex; gap: 6px;">
                            ${hasSeg ? `<button class="btn btn-secondary ai-toggle-btn" style="font-size:10px; padding:3px 8px; border-radius:4px; border-color: rgba(0, 242, 254, 0.3); color: var(--color-primary);">AI 分析</button>` : ''}
                            <button class="btn btn-primary use-btn" style="font-size:10px; padding:3px 8px; border-radius:4px;">采用</button>
                        </div>
                    </div>
                    ${cand.transcript_text ? `
                    <div class="cand-transcript" style="font-size: 10px; color: var(--color-primary); background: rgba(0, 242, 254, 0.08); border: 1px solid rgba(0, 242, 254, 0.2); border-radius: 4px; padding: 4px 6px; margin-top: 6px; display: flex; align-items: center; gap: 4px; line-height: 1.2;">
                        <span>💬</span>
                        <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500;" title="台词: ${cand.transcript_text} (相似度: ${Math.round(cand.transcript_similarity * 100)}%)">"${cand.transcript_text}"</span>
                    </div>
                    ` : ''}
                </div>
            </div>
            
            ${hasSeg ? `
            <div class="ai-details-panel" style="display: none; background: rgba(0, 242, 254, 0.03); border: 1px solid rgba(0, 242, 254, 0.12); border-radius: 6px; padding: 10px; margin-top: 4px; font-size: 11px; color: var(--text-secondary); display: flex; flex-direction: column; gap: 6px; line-height: 1.4;">
                <div style="color: #fff; font-weight: 600; display: flex; justify-content: space-between; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 4px; margin-bottom: 2px;">
                    <span>✨ Gemini 多模态联合理解</span>
                    <span style="font-family: monospace; font-size: 10px; color: var(--color-primary);">区间: ${cand.segment.start_time.toFixed(1)}s - ${cand.segment.end_time.toFixed(1)}s</span>
                </div>
                <div><strong>🎬 画面描述:</strong> <span style="color: #eee;">${cand.segment.summary || '无'}</span></div>
                <div><strong>🎨 视觉风格:</strong> <span style="color: #eee;">${cand.segment.visual_style || '无'}</span></div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                    <div><strong>🕺 运动强度:</strong> <span style="color: var(--color-primary);">${cand.segment.motion_intensity === 'high' ? '🔥 高' : cand.segment.motion_intensity === 'medium' ? '⚡ 中' : '❄️ 低'}</span></div>
                    <div><strong>❤️ 情感起伏:</strong> <span style="color: #eee;">${cand.segment.emotion_flow || '无'}</span></div>
                </div>
                <div>
                    <strong>🏷️ 标签:</strong>
                    <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px;">
                        ${cand.segment.tags.map(t => `<span style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 3px; padding: 1px 4px; font-size: 9px; color: #ccc;">${t}</span>`).join('')}
                    </div>
                </div>
                <div style="display: flex; justify-content: flex-end; margin-top: 4px; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 6px;">
                    <button class="btn btn-secondary play-segment-btn" style="font-size: 9px; padding: 2px 6px; border-radius: 3px; display: flex; align-items: center; gap: 2px;">
                        ▶ 播放当前分析片段
                    </button>
                </div>
            </div>
            ` : ''}
        `;
        
        // Clicking card previews the proxy video starting at the keyframe time (unless clicking buttons/AI details)
        card.addEventListener('click', (e) => {
            if (e.target.tagName !== 'BUTTON' && !e.target.closest('.ai-details-panel') && !e.target.closest('.ai-badge') && !e.target.closest('.ai-toggle-btn')) {
                el.videoPlaceholder.style.display = 'none';
                el.monitorVideoName.textContent = fileName;
                
                switchActivePlayer(cand.proxy_url, Math.max(0, cand.timestamp));
                activePlayer.currentTime = Math.max(0, cand.timestamp);
                activePlayer.play().catch(() => {});
            }
        });
        
        // Toggle AI details panel
        if (hasSeg) {
            const aiBtn = card.querySelector('.ai-toggle-btn');
            const aiBadge = card.querySelector('.ai-badge');
            const detailsPanel = card.querySelector('.ai-details-panel');
            
            detailsPanel.style.display = 'none';
            
            const toggleDetails = (evt) => {
                evt.stopPropagation();
                if (detailsPanel.style.display === 'none') {
                    detailsPanel.style.display = 'flex';
                    if (aiBtn) aiBtn.textContent = '收起分析';
                } else {
                    detailsPanel.style.display = 'none';
                    if (aiBtn) aiBtn.textContent = 'AI 分析';
                }
            };
            
            if (aiBtn) aiBtn.addEventListener('click', toggleDetails);
            if (aiBadge) aiBadge.addEventListener('click', toggleDetails);
            
            // Play segment button logic
            const playSegBtn = card.querySelector('.play-segment-btn');
            if (playSegBtn) {
                playSegBtn.addEventListener('click', (evt) => {
                    evt.stopPropagation();
                    el.videoPlaceholder.style.display = 'none';
                    el.monitorVideoName.textContent = fileName;
                    
                    switchActivePlayer(cand.proxy_url, Math.max(0, cand.segment.start_time));
                    activePlayer.currentTime = Math.max(0, cand.segment.start_time);
                    activePlayer.play().catch(() => {});
                    
                    browserLog(`Playing Gemini segment from ${cand.segment.start_time.toFixed(1)}s to ${cand.segment.end_time.toFixed(1)}s`);
                });
            }
        }
        
        // Clicking "Use" button assigns the candidate to the active slot
        card.querySelector('.use-btn').addEventListener('click', (e) => {
            e.stopPropagation();
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
    
    const transcript = (cand.segment && cand.segment.transcript) ? cand.segment.transcript : "";
    let keep_audio = false;
    if (transcript && cand.segment) {
        const score = cand.segment.mad_score || 5;
        const type = cand.segment.scene_type || "";
        if (type === "emotional" || score >= 8) {
            keep_audio = true;
        }
    }
    
    timelineSlots[activeSlotIndex] = {
        video_path: cand.video_path,
        video_name: fileName,
        proxy_url: cand.proxy_url,
        clip_start: clip_start,
        clip_duration: duration,
        video_duration: cand.duration,
        transcript: transcript,
        keep_audio: keep_audio
    };
    
    // Refresh all blocks on the timeline
    refreshTimelineBlocks();
    renderScriptOutline();
    
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
    
    let isCancelled = false;
    
    // Set up cancellation event handler
    el.modalCancelBtn.onclick = () => {
        isCancelled = true;
        appendModalLog("⚠️ 正在取消匹配任务...");
    };
    
    showModal("🤖 一键智能卡点匹配", "正在分析所有卡点并匹配最佳画面...");
    // Show cancel button, hide close button
    el.modalRunningActions.style.display = 'flex';
    el.modalFooter.style.display = 'none';
    
    appendModalLog(`开始对 ${songData.lyrics.length} 个卡点执行智能匹配...`);
    
    const motion = el.motionPreference.value;
    let successCount = 0;
    
    // 1. Gather all empty slot indices
    const emptySlotIndices = [];
    for (let i = 0; i < songData.lyrics.length; i++) {
        if (timelineSlots[i] === null) {
            emptySlotIndices.push(i);
        } else {
            appendModalLog(`卡点 #${i+1} [已存在素材]: 跳过`);
        }
    }
    
    if (emptySlotIndices.length === 0) {
        appendModalLog("所有卡点均已存在素材，无需匹配。");
        updateModalProgress(100, "智能匹配完成！无须更新。");
        el.modalRunningActions.style.display = 'none';
        el.modalFooter.style.display = 'block';
        return;
    }
    
    // 2. Chunk indices into batches of 20
    const chunkSize = 20;
    const chunks = [];
    for (let i = 0; i < emptySlotIndices.length; i += chunkSize) {
        chunks.push(emptySlotIndices.slice(i, i + chunkSize));
    }
    
    appendModalLog(`共需匹配 ${emptySlotIndices.length} 个槽位，分 ${chunks.length} 批次并行处理...`);
    
    try {
        let completedChunksCount = 0;
        
        const chunkPromises = chunks.map(async (chunk, chunkIdx) => {
            if (isCancelled) return;
            
            // Build request items for this chunk
            const items = chunk.map(idx => {
                const lyric = songData.lyrics[idx];
                let promptText = lyric.text;
                let motionPref = motion;
                let concept = "";
                let tone = "";
                if (scriptPlan && scriptPlan[idx]) {
                    promptText = scriptPlan[idx].visual_prompt || lyric.text;
                    motionPref = scriptPlan[idx].motion_preference || motion;
                    concept = scriptPlan[idx].narrative_concept || "";
                    tone = scriptPlan[idx].emotional_tone || "";
                }
                return {
                    index: idx,
                    lyric_text: promptText,
                    motion_preference: motionPref,
                    lyric: lyric ? lyric.text : "",
                    narrative_concept: concept,
                    emotional_tone: tone
                };
            });
            
            // Fetch batch match API
            const res = await fetch('/api/batch_match', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items })
            });
            
            if (isCancelled) return;
            
            if (!res.ok) {
                throw new Error(`批次 #${chunkIdx + 1} 请求失败: ${res.status}`);
            }
            
            const batchResults = await res.json();
            if (isCancelled) return;
            
            // Process the matched results for each index in the chunk
            for (const idx of chunk) {
                if (isCancelled) break;
                
                const lyric = songData.lyrics[idx];
                const candidates = batchResults[idx];
                
                // Collect video paths of the previous 4 slots to avoid repeats
                const recentlyUsedPaths = [];
                const lookbackWindow = 4;
                for (let j = Math.max(0, idx - lookbackWindow); j < idx; j++) {
                    const eff = getEffectiveSlot(j);
                    if (eff && eff.video_path) {
                        recentlyUsedPaths.push(eff.video_path);
                    }
                }
                
                if (candidates && candidates.length > 0) {
                    let selectedCand = null;
                    
                    // Tier 1: No overlap AND not recently used
                    for (const cand of candidates) {
                        if (!recentlyUsedPaths.includes(cand.video_path) && !hasVideoOverlap(cand, idx)) {
                            selectedCand = cand;
                            break;
                        }
                    }
                    
                    // Tier 2: No overlap
                    if (!selectedCand) {
                        for (const cand of candidates) {
                            if (!hasVideoOverlap(cand, idx)) {
                                selectedCand = cand;
                                appendModalLog(`卡点 #${idx+1}: 采用最近使用的视频，但选择无画面重叠的片段`);
                                break;
                            }
                        }
                    }
                    
                    // Tier 3: Fallback
                    if (!selectedCand) {
                        selectedCand = candidates[0];
                        appendModalLog(`卡点 #${idx+1}: 所有候选画面均有时间轴重叠，执行首选兜底`);
                    }
                    
                    const duration = lyric.end - lyric.start;
                    const fileName = selectedCand.video_path.split('/').pop();
                    const clip_start = Math.max(0, selectedCand.timestamp);
                    
                    const transcript = (selectedCand.segment && selectedCand.segment.transcript) ? selectedCand.segment.transcript : "";
                    let keep_audio = false;
                    if (transcript && selectedCand.segment) {
                        const score = selectedCand.segment.mad_score || 5;
                        const type = selectedCand.segment.scene_type || "";
                        if (type === "emotional" || score >= 8) {
                            keep_audio = true;
                        }
                    }
                    
                    timelineSlots[idx] = {
                        video_path: selectedCand.video_path,
                        video_name: fileName,
                        proxy_url: selectedCand.proxy_url,
                        clip_start: clip_start,
                        clip_duration: duration,
                        video_duration: selectedCand.duration,
                        transcript: transcript,
                        keep_audio: keep_audio
                    };
                    successCount++;
                    appendModalLog(`卡点 #${idx+1} 匹配成功: -> ${fileName} (从 ${clip_start.toFixed(1)}s)`);
                } else {
                    appendModalLog(`卡点 #${idx+1} 匹配失败: 未找到候选片段`);
                }
            }
            
            completedChunksCount++;
            const progressPct = Math.round((completedChunksCount / chunks.length) * 100);
            updateModalProgress(progressPct, `正在处理匹配结果... (${completedChunksCount}/${chunks.length} 批次)`);
        });
        
        await Promise.all(chunkPromises);
        
        if (isCancelled) {
            appendModalLog("❌ 一键智能匹配任务已被取消。");
            updateModalProgress(0, "已取消匹配任务");
            el.modalRunningActions.style.display = 'none';
            el.modalFooter.style.display = 'block';
            return;
        }
        
        updateModalProgress(100, `智能匹配完成！成功填充 ${successCount} 个卡点`);
        appendModalLog(`--- 一键智能匹配完成 ---`);
        appendModalLog(`成功匹配: ${successCount} 个卡点`);
        
    } catch (err) {
        appendModalLog(`一键匹配发生错误: ${err.message}`);
        updateModalProgress(0, "匹配出错");
    } finally {
        // Hide cancel actions, show close button
        el.modalRunningActions.style.display = 'none';
        el.modalFooter.style.display = 'block';
    }
    
    // Refresh timeline and footer stats
    refreshTimelineBlocks();
    updateFooterStats();
    
    // If a slot is currently active, update its preview
    if (activeSlotIndex !== null) {
        updatePreviewPlayerForSlot(activeSlotIndex);
        if (timelineSlots[activeSlotIndex]) {
            el.clearSlotBtn.style.display = 'block';
        } else {
            el.clearSlotBtn.style.display = 'none';
        }
    }
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
                clip_duration: lyric.end - lyric.start,
                keep_audio: effective.isFallback ? false : (effective.keep_audio || false),
                transcript: effective.isFallback ? "" : (effective.transcript || "")
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
        video_duration: videoDuration,
        transcript: "",
        keep_audio: false
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
        console.log("[v3] Preloading test data...");
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
            if (el.generateScriptBtn) el.generateScriptBtn.removeAttribute('disabled');
            if (el.regenerateScriptBtn) el.regenerateScriptBtn.removeAttribute('disabled');
            
            // Fetch AI story vision recommendations based on lyrics and DB video content
            fetchStoryVisionRecommendations();
            
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

// --- Tab Switching and Script Planner Logic ---

function switchTab(tabName) {
    if (!el.tabPlannerBtn || !el.tabMatcherBtn || !el.panelPlannerContent || !el.panelMatcherContent) return;
    
    if (tabName === 'planner') {
        el.tabPlannerBtn.classList.add('active');
        el.tabPlannerBtn.style.borderBottomColor = 'var(--color-primary)';
        el.tabPlannerBtn.style.color = '#fff';
        
        el.tabMatcherBtn.classList.remove('active');
        el.tabMatcherBtn.style.borderBottomColor = 'transparent';
        el.tabMatcherBtn.style.color = 'var(--text-secondary)';
        
        el.panelPlannerContent.style.display = 'flex';
        el.panelMatcherContent.style.display = 'none';
    } else {
        el.tabMatcherBtn.classList.add('active');
        el.tabMatcherBtn.style.borderBottomColor = 'var(--color-primary)';
        el.tabMatcherBtn.style.color = '#fff';
        
        el.tabPlannerBtn.classList.remove('active');
        el.tabPlannerBtn.style.borderBottomColor = 'transparent';
        el.tabPlannerBtn.style.color = 'var(--text-secondary)';
        
        el.panelMatcherContent.style.display = 'flex';
        el.panelPlannerContent.style.display = 'none';
    }
}

// Generate script plan outline by querying Gemini
async function generateScriptPlan(clearCache = false) {
    if (!songData) return alert("请先上传或分析歌曲！");
    
    const defaultVision = "这是一首讲述两个打工人（佐佐木和田山）互相救赎的 AMV/MAD。故事从两人互不认识开始，工作的压力与疲惫让彼此 messed up，但他们 keep coming around，用陪伴和温暖悄悄疗愈对方，最终走向相互依靠。情感基调：从压抑、孤独 → 惊喜相遇 → 暧昧摩擦 → 互相治愈 → 温暖释怀。";
    const userVision = (el.userVisionInput && el.userVisionInput.value.trim()) ? el.userVisionInput.value.trim() : defaultVision;
    
    // If clear cache requested, call DELETE first
    if (clearCache) {
        try {
            await fetch('/api/script_outline_cache', { method: 'DELETE' });
        } catch (e) {
            console.warn('Failed to clear outline cache:', e);
        }
    }
    
    showModal("✍️ 生成创意分镜脚本中", clearCache ? "已清除缓存，AI 大模型正在重新规划大纲..." : "AI 大模型正在通读歌词，规划视觉镜头大纲...");
    appendModalLog("开始解析创作视角与情感起伏...");
    appendModalLog(`构想设定: "${userVision.substring(0, 40)}..."`);
    
    updateModalProgress(40, "正在调用 Gemini-3.5-Flash 大模型进行分镜规划...");
    
    // Prepare lyrics list for backend
    const lyricsPayload = songData.lyrics.map(l => ({
        text: l.text,
        start: l.start,
        end: l.end
    }));
    
    try {
        const res = await fetch('/api/generate_script_plan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                lyrics: lyricsPayload,
                user_vision: userVision
            })
        });
        
        const data = await res.json();
        if (res.ok) {
            updateModalProgress(100, "大纲生成成功！");
            appendModalLog("--- 脚本分镜规划生成完成 ---");
            appendModalLog(`成功生成了 ${data.length} 条分镜镜头描述。`);
            
            scriptPlan = data;
            
            // Render the lines
            renderScriptOutline();
            
            // Update status badge
            if (el.scriptStatusBadge) {
                el.scriptStatusBadge.textContent = "已生成";
                el.scriptStatusBadge.style.color = "var(--color-success)";
                el.scriptStatusBadge.style.borderColor = "var(--color-success)";
            }
            
            // Show apply button container
            if (el.applyScriptContainer) {
                el.applyScriptContainer.style.display = 'block';
            }
            
            setTimeout(() => {
                el.modalOverlay.style.display = 'none';
            }, 1000);
        } else {
            updateModalProgress(100, "生成失败！");
            appendModalLog(`错误原因: ${data.detail}`);
            el.modalFooter.style.display = 'block';
        }
    } catch (e) {
        updateModalProgress(100, "网络异常！");
        appendModalLog(`连接失败: ${e.message}`);
        el.modalFooter.style.display = 'block';
    }
}

// Fetch and display recommended story concepts based on lyrics and DB video segments
async function fetchStoryVisionRecommendations() {
    if (!songData || !songData.lyrics || songData.lyrics.length === 0) return;
    
    // Reset and show container
    if (el.recommendedVisionsContainer) el.recommendedVisionsContainer.style.display = 'block';
    if (el.visionsLoading) el.visionsLoading.style.display = 'inline';
    if (el.recommendedVisionsList) el.recommendedVisionsList.innerHTML = '';
    
    try {
        const payload = {
            lyrics: songData.lyrics.map(l => ({
                text: l.text,
                start: l.start,
                end: l.end
            }))
        };
        
        const res = await fetch('/api/recommend_story_visions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (res.ok) {
            const recommendations = await res.json();
            if (el.recommendedVisionsList) {
                el.recommendedVisionsList.innerHTML = '';
                recommendations.forEach(item => {
                    const card = document.createElement('div');
                    card.style.cssText = "padding: 6px 10px; background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 6px; cursor: pointer; transition: all 0.2s; font-size: 11px; display: flex; flex-direction: column; gap: 3px;";
                    
                    // Add hover styles dynamically
                    card.addEventListener('mouseenter', () => {
                        card.style.background = 'rgba(255, 255, 255, 0.07)';
                        card.style.borderColor = 'var(--color-primary)';
                    });
                    card.style.color = '#eee';
                    card.addEventListener('mouseleave', () => {
                        card.style.background = 'rgba(255, 255, 255, 0.03)';
                        card.style.borderColor = 'rgba(255, 255, 255, 0.08)';
                    });
                    
                    card.innerHTML = `
                        <div style="font-weight: 600; color: var(--color-primary); font-size: 11.5px; display: flex; align-items: center; gap: 4px;">🎯 ${item.title}</div>
                        <div style="font-size: 10.5px; color: var(--text-secondary); line-height: 1.3;">${item.description}</div>
                    `;
                    
                    // Click handler to auto-populate user vision input
                    card.addEventListener('click', () => {
                        if (el.userVisionInput) {
                            el.userVisionInput.value = item.description;
                            // Trigger subtle border flash animation to denote success
                            el.userVisionInput.style.borderColor = 'var(--color-primary)';
                            el.userVisionInput.style.boxShadow = '0 0 8px rgba(255, 74, 150, 0.3)';
                            setTimeout(() => {
                                el.userVisionInput.style.borderColor = '';
                                el.userVisionInput.style.boxShadow = '';
                            }, 500);
                        }
                    });
                    el.recommendedVisionsList.appendChild(card);
                });
            }
        } else {
            console.error("Failed to load story vision recommendations:", await res.text());
            if (el.recommendedVisionsList) {
                el.recommendedVisionsList.innerHTML = '<div style="font-size: 10.5px; color: var(--text-muted); padding: 5px;">暂无可用创意推荐</div>';
            }
        }
    } catch (e) {
        console.error("Error loading story vision recommendations:", e);
        if (el.recommendedVisionsList) {
            el.recommendedVisionsList.innerHTML = '<div style="font-size: 10.5px; color: var(--text-muted); padding: 5px;">网络连接异常</div>';
        }
    } finally {
        if (el.visionsLoading) el.visionsLoading.style.display = 'none';
    }
}

// Renders the editable script plan table
function renderScriptOutline() {
    if (!el.scriptLinesList || !scriptPlan) return;
    
    // Extract unique sections for high-level story panel
    const uniqueSections = [];
    const seenSections = new Set();
    
    // Section colors mapped for reference
    const sectionColors = [
        'rgba(99, 102, 241, 0.25)',   // indigo - Verse
        'rgba(236, 72, 153, 0.25)',   // pink - Chorus
        'rgba(16, 185, 129, 0.25)',   // emerald - Bridge
        'rgba(245, 158, 11, 0.25)',   // amber - Outro
        'rgba(59, 130, 246, 0.25)',   // blue
        'rgba(168, 85, 247, 0.25)',   // purple
    ];
    const sectionBorderColors = [
        'rgba(99, 102, 241, 0.6)',
        'rgba(236, 72, 153, 0.6)',
        'rgba(16, 185, 129, 0.6)',
        'rgba(245, 158, 11, 0.6)',
        'rgba(59, 130, 246, 0.6)',
        'rgba(168, 85, 247, 0.6)',
    ];

    scriptPlan.forEach(line => {
        if (line.section_name && !seenSections.has(line.section_name)) {
            seenSections.add(line.section_name);
            uniqueSections.push({
                section_name: line.section_name,
                mood_arc: line.mood_arc || '',
                narrative_concept: line.narrative_concept || '',
                visual_pacing: line.visual_pacing || ''
            });
        }
    });

    if (el.scriptHighLevelPanel && el.highLevelContent) {
        if (uniqueSections.length > 0) {
            el.scriptHighLevelPanel.style.display = 'block';
            el.highLevelContent.innerHTML = '';
            uniqueSections.forEach((sec, idx) => {
                const borderCol = sectionBorderColors[idx % sectionBorderColors.length];
                const bgCol = sectionColors[idx % sectionColors.length];
                const item = document.createElement('div');
                item.style.cssText = `
                    padding: 8px 10px;
                    border-left: 3px solid ${borderCol};
                    background: rgba(255, 255, 255, 0.015);
                    border-radius: 4px;
                    display: flex;
                    flex-direction: column;
                    gap: 3px;
                `;
                item.innerHTML = `
                    <div style="display: flex; justify-content: space-between; font-weight: 600; color: #fff; font-size: 11px; align-items: center;">
                        <span style="font-size: 11.5px; color: #00f2fe;">${sec.section_name} <span style="font-size: 9.5px; color: var(--text-muted); font-weight: normal; margin-left: 4px;">(${sec.visual_pacing === 'slow' ? '慢速节奏' : sec.visual_pacing === 'fast' ? '快速节奏' : '常规节奏'})</span></span>
                        <span style="font-size: 10px; color: var(--color-primary); background: rgba(255, 74, 150, 0.1); padding: 1px 5px; border-radius: 3px;">${sec.mood_arc}</span>
                    </div>
                    ${sec.narrative_concept ? `<div style="font-size: 10px; color: #b4b4c6; line-height: 1.4; font-style: italic;">${sec.narrative_concept}</div>` : ''}
                `;
                el.highLevelContent.appendChild(item);
            });
        } else {
            el.scriptHighLevelPanel.style.display = 'none';
        }
    }
    
    el.scriptLinesList.innerHTML = '';
    
    // Section colors are already declared at the top of the function
    
    let currentSection = null;
    let sectionIndex = -1;
    
    scriptPlan.forEach((line, index) => {
        // Insert section divider badge when section changes
        const lineSectionName = line.section_name || null;
        if (lineSectionName && lineSectionName !== currentSection) {
            currentSection = lineSectionName;
            sectionIndex = (sectionIndex + 1) % sectionColors.length;
            
            const sectionHeader = document.createElement('div');
            sectionHeader.style.cssText = `
                display: flex; align-items: center; gap: 8px; margin: 12px 0 4px 0;
                padding: 6px 10px; border-radius: 6px;
                background: ${sectionColors[sectionIndex]};
                border-left: 3px solid ${sectionBorderColors[sectionIndex]};
            `;
            sectionHeader.innerHTML = `
                <span style="font-size: 11px; font-weight: 600; color: #fff; letter-spacing: 0.03em;">
                    ${lineSectionName}
                </span>
                ${line.mood_arc ? `<span style="font-size: 10px; color: rgba(255,255,255,0.55); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">· ${line.mood_arc}</span>` : ''}
            `;
            el.scriptLinesList.appendChild(sectionHeader);
        }
        
        const slot = timelineSlots[index];
        const dialogueHtml = (slot && slot.transcript) ? `
            <div class="card-dialogue-container" style="margin-top: 4px; padding: 6px; background: rgba(0,242,254,0.04); border: 1px solid rgba(0,242,254,0.1); border-radius: 6px; display: flex; flex-direction: column; gap: 4px;">
                <div style="font-size: 9.5px; color: #00f2fe; font-weight: 600; display: flex; align-items: center; justify-content: space-between;">
                    <span>🎙️ 原声台词对白</span>
                    <label style="display: flex; align-items: center; gap: 3px; font-weight: normal; cursor: pointer; user-select: none;">
                        <input type="checkbox" class="script-keep-audio-checkbox" data-index="${index}" ${slot.keep_audio ? 'checked' : ''} style="cursor: pointer; margin: 0; width: 12px; height: 12px;" /> 混合原声
                    </label>
                </div>
                <div style="font-size: 10px; color: #e4e4f0; line-height: 1.3;">"${slot.transcript}"</div>
            </div>
        ` : '';

        const card = document.createElement('div');
        card.className = 'script-line-card';
        card.style.cssText = "background: rgba(0,0,0,0.25); border: 1px solid var(--border-color); border-radius: 8px; padding: 10px; display: flex; flex-direction: column; gap: 6px;";
        
        card.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.03); padding-bottom: 4px; margin-bottom: 2px;">
                <span style="font-size: 10px; color: var(--color-primary); font-family: var(--font-mono);">分镜 #${index + 1}</span>
                <span style="font-size: 9px; color: var(--text-muted); text-align: right;" title="${line.emotional_tone || ''}">${line.emotional_tone ? '🎭 ' + line.emotional_tone.substring(0, 15) + '...' : ''}</span>
            </div>
            <div style="font-size: 11px; color: var(--text-secondary); font-style: italic; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                歌词: "${line.lyric}"
            </div>
            <div style="display: flex; flex-direction: column; gap: 4px;">
                <label style="font-size: 9px; color: var(--text-muted);">画面匹配提示词:</label>
                <textarea class="script-prompt-input" data-index="${index}" style="width: 100%; height: 40px; padding: 5px; background: rgba(0,0,0,0.4); border: 1px solid var(--border-color); border-radius: 4px; color: #fff; font-size: 11px; font-family: var(--font-sans); resize: none; outline: none;">${line.visual_prompt}</textarea>
            </div>
            ${dialogueHtml}
            <div style="display: flex; gap: 8px; align-items: center; justify-content: space-between; margin-top: 4px;">
                <div style="display: flex; align-items: center; gap: 4px;">
                    <label style="font-size: 9px; color: var(--text-muted);">运动感:</label>
                    <select class="script-motion-select" data-index="${index}" style="background: #0f0f18; border: 1px solid var(--border-color); border-radius: 4px; color: #fff; font-size: 10px; padding: 2px 4px; outline: none;">
                        <option value="low" ${line.motion_preference === 'low' ? 'selected' : ''}>Low (慢)</option>
                        <option value="medium" ${line.motion_preference === 'medium' ? 'selected' : ''}>Medium (中)</option>
                        <option value="high" ${line.motion_preference === 'high' ? 'selected' : ''}>High (快)</option>
                    </select>
                </div>
                <button class="btn btn-secondary script-regen-btn" data-index="${index}" style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(255,255,255,0.02);">
                    🔄 局部重写
                </button>
            </div>
        `;
        
        // Listen to changes in prompt text
        card.querySelector('.script-prompt-input').addEventListener('input', (e) => {
            scriptPlan[index].visual_prompt = e.target.value;
        });
        
        // Listen to changes in motion select
        card.querySelector('.script-motion-select').addEventListener('change', (e) => {
            scriptPlan[index].motion_preference = e.target.value;
        });
        
        // Listen to single line regenerate
        card.querySelector('.script-regen-btn').addEventListener('click', () => {
            regenerateScriptLine(index);
        });
        
        // Listen to keep audio checkbox change
        const audioCheckbox = card.querySelector('.script-keep-audio-checkbox');
        if (audioCheckbox) {
            audioCheckbox.addEventListener('change', (e) => {
                if (timelineSlots[index]) {
                    timelineSlots[index].keep_audio = e.target.checked;
                    refreshTimelineBlocks();
                    if (activeSlotIndex === index) {
                        updatePreviewPlayerForSlot(index);
                    }
                }
            });
        }
        
        el.scriptLinesList.appendChild(card);
    });
}




// Regenerates a single line's storyboard using Gemini based on user prompt feedback
async function regenerateScriptLine(index) {
    if (!scriptPlan || !scriptPlan[index]) return;
    
    const feedback = prompt(`请输入您对分镜 #${index + 1} 的画面修改意见 (例如: "让他走在大雨滂沱的赛博朋克废墟街道中" )：`);
    if (!feedback) return; // user cancelled
    
    const line = scriptPlan[index];
    const userVision = el.userVisionInput ? el.userVisionInput.value.trim() : "";
    
    // Disable regen button and show spinner
    const btn = document.querySelector(`.script-regen-btn[data-index="${index}"]`);
    if (btn) {
        btn.textContent = "⏳...";
        btn.setAttribute('disabled', 'true');
    }
    
    try {
        const res = await fetch('/api/regenerate_script_line', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                lyric_text: line.lyric,
                current_prompt: line.visual_prompt,
                user_feedback: feedback,
                user_vision: userVision
            })
        });
        
        const data = await res.json();
        if (res.ok) {
            scriptPlan[index].visual_prompt = data.visual_prompt;
            scriptPlan[index].motion_preference = data.motion_preference;
            scriptPlan[index].emotional_tone = data.emotional_tone;
            
            // Re-render
            renderScriptOutline();
        } else {
            alert(`局部改写失败: ${data.detail}`);
            if (btn) {
                btn.textContent = "🔄 局部重写";
                btn.removeAttribute('disabled');
            }
        }
    } catch (e) {
        alert(`网络异常: ${e.message}`);
        if (btn) {
            btn.textContent = "🔄 局部重写";
            btn.removeAttribute('disabled');
        }
    }
}

// Applies script plan & runs bulk auto matcher
function applyScriptAndMatchAll() {
    if (!scriptPlan) return;
    
    // Switch to matcher tab
    switchTab('matcher');
    
    // Trigger bulk card matching
    autoMatchAllSlots();
}

// Video & Transcript Browser Modal Logic
async function openVideoBrowser() {
    browserLog("openVideoBrowser: Modal opening triggered.");
    const modal = document.getElementById('video-browser-modal');
    if (modal) {
        modal.style.display = 'flex';
        browserLog("openVideoBrowser: modal display set to flex.");
    } else {
        browserLog("openVideoBrowser ERROR: #video-browser-modal element not found.");
    }
    
    // Pause main playback if playing
    if (isPlaying) {
        browserLog("openVideoBrowser: Pausing main playback.");
        togglePlayback();
    }
    // Pause both main preview players
    pauseBothPlayers();
    
    // Fetch latest videos and populate list
    try {
        browserLog("openVideoBrowser: Fetching fresh list of videos from /api/videos...");
        const res = await fetch('/api/videos');
        if (res.ok) {
            allIndexedVideos = await res.json();
            browserLog(`openVideoBrowser: Fetched ${allIndexedVideos.length} videos from API.`);
            updateModelStatus(true, `已索引 ${allIndexedVideos.length} 个视频`);
            populateManualVideoSelect();
        } else {
            browserLog(`openVideoBrowser ERROR: Fetch failed with status ${res.status}`);
        }
    } catch (e) {
        browserLog("openVideoBrowser EXCEPTION: " + e.message);
        console.error("Failed to refresh videos in browser:", e);
    }
    
    populateBrowserVideoList();
}

function closeVideoBrowser() {
    browserLog("closeVideoBrowser: Modal closing.");
    const modal = document.getElementById('video-browser-modal');
    const player = document.getElementById('browser-preview-player');
    const placeholder = document.getElementById('browser-player-placeholder');
    const listContainer = document.getElementById('browser-transcript-list');
    const segmentListContainer = document.getElementById('browser-segment-list');
    const countBadge = document.getElementById('browser-transcript-count');
    
    if (modal) modal.style.display = 'none';
    if (player) {
        player.pause();
        player.src = "";
        player.load();
    }
    if (placeholder) placeholder.style.display = 'flex';
    if (listContainer) listContainer.innerHTML = '<div class="empty-state" style="padding:30px 0;"><p>选择左侧视频以加载台词对白</p></div>';
    if (segmentListContainer) segmentListContainer.innerHTML = '<div class="empty-state" style="padding:30px 0;"><p>选择左侧视频以加载 Gemini 场景分析</p></div>';
    if (countBadge) countBadge.textContent = `0 句`;
    
    // Reset state
    currentBrowserVideoId = null;
    currentBrowserTranscripts = [];
    currentBrowserSegments = [];
    switchBrowserTab('transcripts'); // reset tab to transcripts
}

function populateBrowserVideoList() {
    browserLog("populateBrowserVideoList: Rendering video items. Count: " + allIndexedVideos.length);
    const list = document.getElementById('browser-video-list');
    if (!list) {
        browserLog("populateBrowserVideoList ERROR: #browser-video-list element not found.");
        return;
    }
    
    list.innerHTML = '';
    if (allIndexedVideos.length === 0) {
        browserLog("populateBrowserVideoList: allIndexedVideos is empty.");
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.style.padding = '20px 0';
        empty.innerHTML = '<p>暂无已索引视频，请在上方输入路径并点击“索引视频”。</p>';
        list.appendChild(empty);
        return;
    }
    
    allIndexedVideos.forEach(video => {
        const item = document.createElement('div');
        item.className = 'browser-video-item';
        const videoName = (video.original_path || "未知视频").split('/').pop().split('\\').pop();
        item.textContent = videoName;
        item.title = video.original_path || "";
        
        // Inline styles to guarantee rendering even if CSS is cached
        item.style.cursor = 'pointer';
        item.style.padding = '8px 12px';
        item.style.borderRadius = '6px';
        item.style.background = 'rgba(255, 255, 255, 0.02)';
        item.style.border = '1px solid var(--border-color)';
        item.style.fontSize = '12px';
        item.style.color = 'var(--text-secondary)';
        item.style.transition = 'all 0.2s ease';
        item.style.wordBreak = 'break-all';
        
        // Hover effects via JS
        item.addEventListener('mouseenter', () => {
            if (!item.classList.contains('active')) {
                item.style.background = 'rgba(255, 255, 255, 0.06)';
                item.style.borderColor = 'rgba(0, 242, 254, 0.4)';
                item.style.color = '#fff';
            }
        });
        item.addEventListener('mouseleave', () => {
            if (!item.classList.contains('active')) {
                item.style.background = 'rgba(255, 255, 255, 0.02)';
                item.style.borderColor = 'var(--border-color)';
                item.style.color = 'var(--text-secondary)';
            }
        });
        
        list.appendChild(item);
    });
    browserLog("populateBrowserVideoList: All items appended.");
}

async function selectBrowserVideo(video) {
    browserLog(`selectBrowserVideo: Starting selection for ID: ${video.id}`);
    currentBrowserVideoId = video.id;
    currentBrowserTranscripts = [];
    currentBrowserSegments = [];
    
    const player = document.getElementById('browser-preview-player');
    const placeholder = document.getElementById('browser-player-placeholder');
    const listContainer = document.getElementById('browser-transcript-list');
    const segmentListContainer = document.getElementById('browser-segment-list');
    const countBadge = document.getElementById('browser-transcript-count');
    
    if (video.proxy_url) {
        browserLog(`selectBrowserVideo: proxy_url found: "${video.proxy_url}"`);
        if (player) {
            player.src = video.proxy_url;
            player.load();
            player.play().then(() => {
                browserLog("selectBrowserVideo: Video playback started successfully.");
            }).catch(e => {
                browserLog("selectBrowserVideo: Playback promise failed (expected if user didn't interact first): " + e.message);
            });
        } else {
            browserLog("selectBrowserVideo ERROR: #browser-preview-player not found.");
        }
        if (placeholder) placeholder.style.display = 'none';
    } else {
        browserLog("selectBrowserVideo WARNING: proxy_url is empty.");
        if (player) player.src = "";
        if (placeholder) {
            placeholder.style.display = 'flex';
            placeholder.textContent = "无法播放该视频 (没有代理预览文件)";
        }
    }
    
    if (listContainer) {
        listContainer.innerHTML = '<div class="loading-state" style="padding:20px; text-align:center; color:#9a9ab0;"><span class="spinner">⌛</span> 正在加载台词对白...</div>';
    }
    if (segmentListContainer) {
        segmentListContainer.innerHTML = '<div class="loading-state" style="padding:20px; text-align:center; color:#9a9ab0;"><span class="spinner">⌛</span> 正在加载 Gemini 场景分析...</div>';
    }
    if (countBadge) countBadge.textContent = `加载中...`;
    
    // Fetch transcripts
    try {
        const url = `/api/videos/${video.id}/transcripts`;
        browserLog(`selectBrowserVideo: Fetching transcripts from "${url}"`);
        const res = await fetch(url);
        if (res.ok) {
            currentBrowserTranscripts = await res.json();
            browserLog(`selectBrowserVideo: Transcripts loaded: ${currentBrowserTranscripts.length}`);
        } else {
            browserLog(`selectBrowserVideo: Fetch transcripts failed with HTTP status ${res.status}`);
        }
    } catch (e) {
        browserLog(`selectBrowserVideo transcripts fetch EXCEPTION: ${e.message}`);
    }
    
    // Fetch segments
    try {
        const url = `/api/videos/${video.id}/segments`;
        browserLog(`selectBrowserVideo: Fetching segments from "${url}"`);
        const res = await fetch(url);
        if (res.ok) {
            currentBrowserSegments = await res.json();
            browserLog(`selectBrowserVideo: Segments loaded: ${currentBrowserSegments.length}`);
        } else {
            browserLog(`selectBrowserVideo: Fetch segments failed with HTTP status ${res.status}`);
        }
    } catch (e) {
        browserLog(`selectBrowserVideo segments fetch EXCEPTION: ${e.message}`);
    }
    
    // Render the active tab
    renderActiveBrowserTab();
}

function renderBrowserTranscripts(transcripts) {
    browserLog(`renderBrowserTranscripts: Starting render for ${transcripts.length} entries.`);
    const listContainer = document.getElementById('browser-transcript-list');
    const countBadge = document.getElementById('browser-transcript-count');
    const player = document.getElementById('browser-preview-player');
    
    if (!listContainer) {
        browserLog("renderBrowserTranscripts ERROR: #browser-transcript-list not found.");
        return;
    }
    
    // Programmatically ensure dimensions and flex behavior to override cache or parent flex collapse
    listContainer.style.height = '320px';
    listContainer.style.flexShrink = '0';
    
    listContainer.innerHTML = '';
    if (countBadge) countBadge.textContent = `${transcripts.length} 句`;
    
    if (transcripts.length === 0) {
        browserLog("renderBrowserTranscripts: 0 transcripts to display.");
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.style.padding = '30px 0';
        empty.style.textAlign = 'center';
        empty.style.color = '#9a9ab0';
        empty.innerHTML = '<p>该视频未检测到或未生成台词对白</p>';
        listContainer.appendChild(empty);
        return;
    }
    
    transcripts.forEach(transcript => {
        const item = document.createElement('div');
        item.className = 'browser-transcript-item';
        item.dataset.startTime = transcript.start_time;
        item.dataset.endTime = transcript.end_time || (transcript.start_time + 3.0);
        
        // Hardcoded inline styles for transcript list item
        item.style.display = 'flex';
        item.style.gap = '12px';
        item.style.alignItems = 'flex-start';
        item.style.padding = '8px 10px';
        item.style.borderRadius = '6px';
        item.style.cursor = 'pointer';
        item.style.background = 'rgba(255, 255, 255, 0.01)';
        item.style.border = '1px solid transparent';
        item.style.transition = 'all 0.2s ease';
        
        const timeTag = document.createElement('span');
        timeTag.className = 'browser-transcript-time';
        timeTag.textContent = formatTime(transcript.start_time);
        
        // Hardcoded inline styles for time tag
        timeTag.style.fontFamily = "'JetBrains Mono', monospace";
        timeTag.style.color = '#00f0ff';
        timeTag.style.fontSize = '11px';
        timeTag.style.fontWeight = '500';
        timeTag.style.background = 'rgba(0, 242, 254, 0.08)';
        timeTag.style.padding = '2px 6px';
        timeTag.style.borderRadius = '4px';
        timeTag.style.flexShrink = '0';
        
        const textSpan = document.createElement('span');
        textSpan.className = 'browser-transcript-text';
        textSpan.textContent = transcript.text;
        
        // Hardcoded inline styles for transcript text
        textSpan.style.color = '#9a9ab0';
        textSpan.style.fontSize = '12px';
        textSpan.style.lineHeight = '1.4';
        textSpan.style.flexGrow = '1';
        textSpan.style.wordBreak = 'break-word';
        textSpan.style.transition = 'color 0.2s ease';
        
        item.appendChild(timeTag);
        item.appendChild(textSpan);
        
        // Hover listeners
        item.addEventListener('mouseenter', () => {
            if (!item.classList.contains('playing')) {
                item.style.background = 'rgba(255, 255, 255, 0.04)';
                item.style.borderColor = 'rgba(255, 255, 255, 0.05)';
                textSpan.style.color = '#ffffff';
            }
        });
        item.addEventListener('mouseleave', () => {
            if (!item.classList.contains('playing')) {
                item.style.background = 'rgba(255, 255, 255, 0.01)';
                item.style.borderColor = 'transparent';
                textSpan.style.color = '#9a9ab0';
            }
        });
        
        item.addEventListener('click', () => {
            browserLog(`Transcript item click: seeking player to start_time: ${transcript.start_time}s`);
            if (player) {
                player.currentTime = transcript.start_time;
                player.play().catch(e => console.log("Play failed on seek:", e));
            }
            highlightPlayingTranscript(item);
        });
        
        listContainer.appendChild(item);
    });
    const compStyle = window.getComputedStyle(listContainer);
    browserLog(`renderBrowserTranscripts: Completed rendering ${transcripts.length} nodes.`);
    browserLog(`[DIAGNOSTIC] listContainer: clientHeight=${listContainer.clientHeight}px, offsetHeight=${listContainer.offsetHeight}px, scrollHeight=${listContainer.scrollHeight}px`);
    browserLog(`[DIAGNOSTIC] listContainer Styles: display=${compStyle.display}, height=${compStyle.height}, max-height=${compStyle.maxHeight}, flexShrink=${compStyle.flexShrink}`);
    
    // Trace parent hierarchy
    let parent = listContainer.parentElement;
    let depth = 1;
    while (parent && parent.tagName !== 'BODY') {
        const pStyle = window.getComputedStyle(parent);
        browserLog(`[DIAGNOSTIC] Parent L${depth} (<${parent.tagName}> id="${parent.id || ''}" class="${parent.className || ''}"): display=${pStyle.display}, height=${pStyle.height}, maxHeight=${pStyle.maxHeight}, flex=${pStyle.flex || (pStyle.flexGrow + ' ' + pStyle.flexShrink + ' ' + pStyle.flexBasis)}`);
        parent = parent.parentElement;
        depth++;
    }
}

function highlightPlayingTranscript(activeItem) {
    const listContainer = document.getElementById('browser-transcript-list');
    if (!listContainer) return;
    
    const items = listContainer.querySelectorAll('.browser-transcript-item');
    items.forEach(item => {
        const textSpan = item.querySelector('.browser-transcript-text');
        if (item === activeItem) {
            item.classList.add('playing');
            item.style.background = 'rgba(0, 242, 254, 0.05)';
            item.style.borderColor = 'rgba(0, 242, 254, 0.2)';
            if (textSpan) {
                textSpan.style.color = '#ffffff';
                textSpan.style.fontWeight = '500';
            }
            item.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } else {
            item.classList.remove('playing');
            item.style.background = 'rgba(255, 255, 255, 0.01)';
            item.style.borderColor = 'transparent';
            if (textSpan) {
                textSpan.style.color = 'var(--text-secondary)';
                textSpan.style.fontWeight = 'normal';
            }
        }
    });
}

// Synchronize transcript scroll position on timeupdate
document.addEventListener('DOMContentLoaded', () => {
    const player = document.getElementById('browser-preview-player');
    if (player) {
        player.addEventListener('timeupdate', () => {
            const currTime = player.currentTime;
            const listContainer = document.getElementById('browser-transcript-list');
            if (!listContainer) return;
            const items = listContainer.querySelectorAll('.browser-transcript-item');
            let activeItem = null;
            
            items.forEach(item => {
                const start = parseFloat(item.dataset.startTime);
                const end = parseFloat(item.dataset.endTime);
                if (currTime >= start && currTime <= end) {
                    activeItem = item;
                }
            });
            
            if (activeItem && !activeItem.classList.contains('playing')) {
                highlightPlayingTranscript(activeItem);
            }
        });
    }
});

// Start everything
window.addEventListener('DOMContentLoaded', init);

function switchBrowserTab(tab) {
    currentBrowserTab = tab;
    
    const transcriptsBtn = document.getElementById('browser-tab-transcripts-btn');
    const segmentsBtn = document.getElementById('browser-tab-segments-btn');
    const transcriptsContainer = document.getElementById('browser-transcript-list-container');
    const segmentsContainer = document.getElementById('browser-segment-list-container');
    
    if (!transcriptsBtn || !segmentsBtn || !transcriptsContainer || !segmentsContainer) return;
    
    if (tab === 'transcripts') {
        transcriptsBtn.classList.add('active');
        transcriptsBtn.style.background = 'rgba(0,242,254,0.12)';
        transcriptsBtn.style.borderColor = 'rgba(0,242,254,0.25)';
        transcriptsBtn.style.color = '#fff';
        transcriptsBtn.style.border = '1px solid var(--border-color)';
        
        segmentsBtn.classList.remove('active');
        segmentsBtn.style.background = 'transparent';
        segmentsBtn.style.borderColor = 'transparent';
        segmentsBtn.style.color = 'var(--text-secondary)';
        segmentsBtn.style.border = '1px solid transparent';
        
        transcriptsContainer.style.display = 'block';
        segmentsContainer.style.display = 'none';
    } else {
        segmentsBtn.classList.add('active');
        segmentsBtn.style.background = 'rgba(0,242,254,0.12)';
        segmentsBtn.style.borderColor = 'rgba(0,242,254,0.25)';
        segmentsBtn.style.color = '#fff';
        segmentsBtn.style.border = '1px solid var(--border-color)';
        
        transcriptsBtn.classList.remove('active');
        transcriptsBtn.style.background = 'transparent';
        transcriptsBtn.style.borderColor = 'transparent';
        transcriptsBtn.style.color = 'var(--text-secondary)';
        transcriptsBtn.style.border = '1px solid transparent';
        
        transcriptsContainer.style.display = 'none';
        segmentsContainer.style.display = 'block';
    }
    
    renderActiveBrowserTab();
}

function renderActiveBrowserTab() {
    const countBadge = document.getElementById('browser-transcript-count');
    
    if (currentBrowserTab === 'transcripts') {
        if (countBadge) countBadge.textContent = `${currentBrowserTranscripts.length} 句`;
        renderBrowserTranscripts(currentBrowserTranscripts);
    } else {
        if (countBadge) countBadge.textContent = `${currentBrowserSegments.length} 个片段`;
        renderBrowserSegments(currentBrowserSegments);
    }
}

function renderBrowserSegments(segments) {
    const listContainer = document.getElementById('browser-segment-list');
    const player = document.getElementById('browser-preview-player');
    
    if (!listContainer) return;
    
    listContainer.innerHTML = '';
    
    if (segments.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.style.padding = '30px 0';
        empty.style.textAlign = 'center';
        empty.style.color = '#9a9ab0';
        empty.innerHTML = '<p>该视频暂无 Gemini 场景分析数据</p>';
        listContainer.appendChild(empty);
        return;
    }
    
    segments.forEach(seg => {
        const item = document.createElement('div');
        item.className = 'browser-segment-item';
        item.style.cssText = "cursor: pointer; padding: 10px; border-radius: 6px; background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border-color); font-size: 11px; display: flex; flex-direction: column; gap: 4px; color: var(--text-secondary); transition: all 0.2s;";
        
        // Hover effect via JS
        item.addEventListener('mouseenter', () => {
            item.style.background = 'rgba(255, 255, 255, 0.05)';
            item.style.borderColor = 'rgba(0, 242, 254, 0.3)';
        });
        item.addEventListener('mouseleave', () => {
            item.style.background = 'rgba(255, 255, 255, 0.02)';
            item.style.borderColor = 'var(--border-color)';
        });
        
        const motionEmoji = seg.motion_intensity === 'high' ? '🔥 高' : seg.motion_intensity === 'medium' ? '⚡ 中' : '❄️ 低';
        
        item.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.04); padding-bottom: 4px; margin-bottom: 2px;">
                <span style="font-family: monospace; font-size: 10px; color: var(--color-primary); font-weight: bold;">[${seg.start_time.toFixed(1)}s - ${seg.end_time.toFixed(1)}s]</span>
                <span style="font-size: 9px; padding: 1px 4px; background: rgba(255,255,255,0.06); border-radius: 3px; color: #ccc;">运动: ${motionEmoji}</span>
            </div>
            <div><strong>🎬 画面描述:</strong> <span style="color: #eee;">${seg.summary}</span></div>
            ${seg.visual_style ? `<div><strong>🎨 视觉风格:</strong> <span style="color: #ccc;">${seg.visual_style}</span></div>` : ''}
            ${seg.emotion_flow ? `<div><strong>❤️ 情感氛围:</strong> <span style="color: #ccc;">${seg.emotion_flow}</span></div>` : ''}
            ${seg.tags && seg.tags.length > 0 ? `
            <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px;">
                ${seg.tags.map(t => `<span style="background: rgba(0, 242, 254, 0.05); border: 1px solid rgba(0, 242, 254, 0.15); border-radius: 3px; padding: 1px 4px; font-size: 8px; color: var(--color-primary);">${t}</span>`).join('')}
            </div>
            ` : ''}
        `;
        
        item.addEventListener('click', () => {
            if (player) {
                player.currentTime = seg.start_time;
                player.play().catch(() => {});
                browserLog(`Seeking preview player to segment start: ${seg.start_time.toFixed(1)}s`);
            }
        });
        
        listContainer.appendChild(item);
    });
}
