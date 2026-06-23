import { formatTime } from './playback.js';

export function renderBrowserTranscripts(transcripts, log = console.log) {
    log(`renderBrowserTranscripts: Starting render for ${transcripts.length} entries.`);
    const listContainer = document.getElementById('browser-transcript-list');
    const countBadge = document.getElementById('browser-transcript-count');
    const player = document.getElementById('browser-preview-player');
    
    if (!listContainer) {
        log("renderBrowserTranscripts ERROR: #browser-transcript-list not found.");
        return;
    }
    
    // Programmatically ensure dimensions and flex behavior to override cache or parent flex collapse
    listContainer.style.height = '320px';
    listContainer.style.flexShrink = '0';
    
    listContainer.innerHTML = '';
    if (countBadge) countBadge.textContent = `${transcripts.length} 句`;
    
    if (transcripts.length === 0) {
        log("renderBrowserTranscripts: 0 transcripts to display.");
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
            log(`Transcript item click: seeking player to start_time: ${transcript.start_time}s`);
            if (player) {
                player.currentTime = transcript.start_time;
                player.play().catch(e => console.log("Play failed on seek:", e));
            }
            highlightPlayingTranscript(item);
        });
        
        listContainer.appendChild(item);
    });
    const compStyle = window.getComputedStyle(listContainer);
    log(`renderBrowserTranscripts: Completed rendering ${transcripts.length} nodes.`);
    log(`[DIAGNOSTIC] listContainer: clientHeight=${listContainer.clientHeight}px, offsetHeight=${listContainer.offsetHeight}px, scrollHeight=${listContainer.scrollHeight}px`);
    log(`[DIAGNOSTIC] listContainer Styles: display=${compStyle.display}, height=${compStyle.height}, max-height=${compStyle.maxHeight}, flexShrink=${compStyle.flexShrink}`);
    
    // Trace parent hierarchy
    let parent = listContainer.parentElement;
    let depth = 1;
    while (parent && parent.tagName !== 'BODY') {
        const pStyle = window.getComputedStyle(parent);
        log(`[DIAGNOSTIC] Parent L${depth} (<${parent.tagName}> id="${parent.id || ''}" class="${parent.className || ''}"): display=${pStyle.display}, height=${pStyle.height}, maxHeight=${pStyle.maxHeight}, flex=${pStyle.flex || (pStyle.flexGrow + ' ' + pStyle.flexShrink + ' ' + pStyle.flexBasis)}`);
        parent = parent.parentElement;
        depth++;
    }
}

export function highlightPlayingTranscript(activeItem) {
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

export function renderBrowserSegments(segments, log = console.log) {
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
                log(`Seeking preview player to segment start: ${seg.start_time.toFixed(1)}s`);
            }
        });
        
        listContainer.appendChild(item);
    });
}
