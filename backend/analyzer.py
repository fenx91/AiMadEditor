import re
import os
import librosa
import numpy as np
import subprocess
import shutil

# Parse LRC lyrics
def parse_lrc(lrc_content, total_duration):
    # Regex to match [mm:ss.xx] or [mm:ss:xx] or [mm:ss]
    time_regex = re.compile(r"\[(\d{2}):(\d{2})[.:](\d{2,3})?\]")
    lines = lrc_content.splitlines()
    
    segments = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Find all time tags in the line (a line might have multiple tags)
        tags = time_regex.findall(line)
        if not tags:
            continue
            
        # Remove all time tags to get the lyric text
        text = time_regex.sub("", line).strip()
        
        # If the text is meta tags like [ar:Artist], skip
        if text.startswith("[") and text.endswith("]"):
            continue
            
        for tag in tags:
            minutes = int(tag[0])
            seconds = int(tag[1])
            millis = tag[2]
            if millis:
                if len(millis) == 3:
                    millis_val = float(millis) / 1000.0
                else:
                    millis_val = float(millis) / 100.0
            else:
                millis_val = 0.0
                
            start_time = minutes * 60 + seconds + millis_val
            segments.append({
                "start": start_time,
                "text": text
            })
            
    # Sort segments by start time
    segments = sorted(segments, key=lambda x: x["start"])
    
    # Calculate end times
    for i in range(len(segments)):
        if i < len(segments) - 1:
            segments[i]["end"] = segments[i + 1]["start"]
        else:
            segments[i]["end"] = total_duration
            
    return segments

# Parse plain text lyrics (distribute evenly)
def parse_txt(txt_content, total_duration):
    lines = [line.strip() for line in txt_content.splitlines() if line.strip()]
    if not lines:
        return []
        
    num_lines = len(lines)
    duration_per_line = total_duration / num_lines
    
    segments = []
    for i, line in enumerate(lines):
        start = i * duration_per_line
        end = (i + 1) * duration_per_line
        segments.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "text": line
        })
        
    return segments

# Analyze audio rhythm and beat marks
def analyze_audio_rhythm(audio_path):
    try:
        # Load audio (mono, 22050Hz is standard for analysis)
        y, sr = librosa.load(audio_path, sr=22050)
        total_duration = librosa.get_duration(y=y, sr=sr)
        
        # 1. Beat tracking (BPM and Beat timestamps)
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        tempo = float(np.atleast_1d(tempo)[0])  # librosa 0.10+ returns ndarray; extract scalar
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
        
        # Ensure we have floats rounded to 3 decimals
        beat_times = [round(t, 3) for t in beat_times]
        
        # 2. Onset detection (finding strong accent points)
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        # Normalize onset envelope
        if np.max(onset_env) > 0:
            onset_env = onset_env / np.max(onset_env)
            
        onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
        onset_times = librosa.frames_to_time(onset_frames, sr=sr)
        
        # Match onsets with strengths
        onsets_info = []
        hop_length = 512
        for f, t in zip(onset_frames, onset_times):
            strength = float(onset_env[f])
            # Only keep reasonably strong onsets
            if strength > 0.1:
                onsets_info.append({
                    "time": round(float(t), 3),
                    "strength": round(strength, 3)
                })
                
        onsets_info = sorted(onsets_info, key=lambda x: x["time"])
        
        # 3. Generate downsampled waveform for frontend display
        # Downsample y to about 1000 points to display in web UI
        target_points = 1000
        hop = max(1, len(y) // target_points)
        waveform = []
        for i in range(0, len(y), hop):
            chunk = y[i:i+hop]
            if len(chunk) > 0:
                waveform.append(float(np.max(np.abs(chunk))))
            else:
                waveform.append(0.0)
                
        # Normalize waveform
        max_val = max(waveform) if waveform else 1.0
        if max_val > 0:
            waveform = [round(w / max_val, 3) for w in waveform]
            
        return {
            "bpm": round(tempo, 1),
            "duration": round(total_duration, 2),
            "beats": beat_times,
            "onsets": onsets_info,
            "waveform": waveform
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error analyzing audio {audio_path}: {e}")
        return {
            "bpm": 120.0,
            "duration": 0.0,
            "beats": [],
            "onsets": [],
            "waveform": []
        }

# Full music analysis (audio + lyrics)
def analyze_music(audio_path, lyric_path=None, lyric_text=None, preparsed_lyrics=None):
    # 1. Analyze audio
    audio_data = analyze_audio_rhythm(audio_path)
    duration = audio_data["duration"]
    
    # 2. Parse lyrics
    lyrics_segments = []
    if preparsed_lyrics is not None:
        lyrics_segments = preparsed_lyrics
    elif lyric_path and os.path.exists(lyric_path):
        content = None
        for encoding in ["utf-8", "gb18030", "gbk", "utf-16"]:
            try:
                with open(lyric_path, "r", encoding=encoding) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue
        
        if content is None:
            try:
                with open(lyric_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception as e:
                print(f"Error reading lyric file {lyric_path} with fallback: {e}")
        
        if content:
            try:
                if lyric_path.lower().endswith(".lrc"):
                    lyrics_segments = parse_lrc(content, duration)
                else:
                    lyrics_segments = parse_txt(content, duration)
            except Exception as e:
                print(f"Error parsing lyric file {lyric_path}: {e}")
            
    elif lyric_text:
        # Check if it looks like LRC
        if "[00:" in lyric_text or "[01:" in lyric_text:
            lyrics_segments = parse_lrc(lyric_text, duration)
        else:
            lyrics_segments = parse_txt(lyric_text, duration)
            
    # Combine lyrics with nearest beats for rhythmic slotting
    # For each lyric segment, we find the beats that fall within its [start, end] duration.
    # This helps the frontend visualize beats inside lyric segments.
    for seg in lyrics_segments:
        seg_beats = [b for b in audio_data["beats"] if seg["start"] <= b <= seg["end"]]
        seg["beats"] = seg_beats
        
    return {
        "bpm": audio_data["bpm"],
        "duration": duration,
        "beats": audio_data["beats"],
        "onsets": audio_data["onsets"],
        "waveform": audio_data["waveform"],
        "lyrics": lyrics_segments
    }

# Trim audio file using FFmpeg
def trim_audio_file(input_path, output_path, start_time, end_time):
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    ext = os.path.splitext(input_path)[1].lower()
    
    cmd = [
        ffmpeg, "-y",
        "-ss", str(start_time),
        "-to", str(end_time),
        "-i", input_path
    ]
    
    if ext == ".mp3":
        cmd += ["-c:a", "libmp3lame", "-q:a", "2"]
    elif ext in [".wav", ".flac"]:
        cmd += ["-c:a", "pcm_s16le" if ext == ".wav" else "flac"]
    else:
        cmd += ["-c:a", "aac"]
        
    cmd.append(output_path)
    
    print(f"Executing trim command: {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise Exception(f"FFmpeg trim failed: {res.stderr}")
    return output_path

# Offset lyric timestamps
def offset_lyrics(lyrics, start_time, end_time):
    trimmed_lyrics = []
    trim_duration = end_time - start_time
    
    for seg in lyrics:
        seg_start = seg["start"]
        seg_end = seg["end"]
        
        if seg_end <= start_time or seg_start >= end_time:
            continue
            
        new_start = max(0.0, seg_start - start_time)
        new_end = min(trim_duration, seg_end - start_time)
        
        if new_end > new_start:
            trimmed_lyrics.append({
                "start": round(new_start, 2),
                "end": round(new_end, 2),
                "text": seg["text"]
            })
            
    return trimmed_lyrics
