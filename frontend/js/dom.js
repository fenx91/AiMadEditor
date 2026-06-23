/** Locate the editor DOM once during application bootstrap. */
export function getEditorElements() {
    return {
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
    dialogueWaveformCanvas: document.getElementById('dialogue-waveform-canvas'),
    timelineRuler: document.getElementById('timeline-ruler'),
    playhead: document.getElementById('playhead'),
    
    lyricTrackItems: document.getElementById('lyric-track-items'),
    videoTrackItems: document.getElementById('video-track-items'),
    dialogueTrackItems: document.getElementById('dialogue-track-items'),
    
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
    exportXmlBtn: document.getElementById('export-xml-btn'),
    exportJsonBtn: document.getElementById('export-json-btn'),
    rangeRenderEnable: document.getElementById('range-render-enable'),
    rangeRenderStart: document.getElementById('range-render-start'),
    rangeRenderEnd: document.getElementById('range-render-end'),
    saveSetupBtn: document.getElementById('save-setup-btn'),
    loadSetupBtn: document.getElementById('load-setup-btn'),
    
    modalOverlay: document.getElementById('modal-overlay'),
    modalTitle: document.getElementById('modal-title'),
    modalProgressBar: document.getElementById('modal-progress-bar'),
    modalStatusMsg: document.getElementById('modal-status-msg'),
    modalLogConsole: document.getElementById('modal-log-console'),
    modalFooter: document.getElementById('modal-footer'),
    modalCloseBtn: document.getElementById('modal-close-btn'),
    musicVolumeSlider: document.getElementById('music-volume-slider'),
    dialogueVolumeSlider: document.getElementById('dialogue-volume-slider'),
    volumeMuteBtn: document.getElementById('volume-mute-btn'),
    clearSlotBtn: document.getElementById('clear-slot-btn'),
    autoMatchAllBtn: document.getElementById('auto-match-all-btn'),
    
    // New Trimmer Controls
    trimmerInput: document.getElementById('trimmer-input'),
    trimmerPlayBtn: document.getElementById('trimmer-play-btn'),
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
    tabJsonBtn: document.getElementById('tab-json-btn'),
    panelPlannerContent: document.getElementById('panel-planner-content'),
    panelMatcherContent: document.getElementById('panel-matcher-content'),
    panelJsonContent: document.getElementById('panel-json-content'),
    jsonEditorTextarea: document.getElementById('json-editor-textarea'),
    applyJsonEditBtn: document.getElementById('apply-json-edit-btn'),
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
}
