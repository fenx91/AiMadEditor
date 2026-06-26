"""HyperFrames rendering and Premiere XML export services."""

import json
import os
import shutil
import subprocess
import urllib.parse

from fastapi import HTTPException, Response
from fastapi.responses import JSONResponse

from schemas import RenderRequest, TimelineSlot


def is_rife_running():
    try:
        import subprocess
        # Check if any process has 'run_rife' in command line
        res = subprocess.run(["pgrep", "-f", "run_rife"], stdout=subprocess.PIPE)
        return res.returncode == 0
    except Exception:
        return False


def is_file_open_by_any_process(filepath):
    try:
        import subprocess
        res = subprocess.run(["fuser", filepath], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return res.returncode == 0
    except Exception:
        return False


def get_high_res_render_proxy(original_path):
    base_name = os.path.splitext(os.path.basename(original_path))[0]
    proxy_dir = "data/proxies"
    os.makedirs(proxy_dir, exist_ok=True)
    render_proxy_path = os.path.join(proxy_dir, f"{base_name}_render.mp4")
    
    # If the .mp4 file is currently open/written to by RIFE, error out to let the user know
    if is_rife_running() and is_file_open_by_any_process(render_proxy_path):
        raise ValueError(
            f"视频代理文件 '{base_name}_render.mp4' 正在被 RIFE 插帧程序写入中，请等待该集插帧完成后再进行渲染。"
        )
            
    if os.path.exists(render_proxy_path):
        return render_proxy_path
        
    print(f"Generating high-res rendering proxy for {original_path}...")
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    
    # Try GPU NVENC with keyframe interval of 30 (GOP=30) for fast seeking
    cmd_gpu = [
        ffmpeg, "-y",
        "-hwaccel", "cuda",
        "-i", original_path,
        "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20",
        "-pix_fmt", "yuv420p",
        "-g", "30", "-keyint_min", "30",
        "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k", render_proxy_path
    ]
    
    cmd_cpu = [
        ffmpeg, "-y",
        "-i", original_path,
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-g", "30", "-keyint_min", "30",
        "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "192k", render_proxy_path
    ]
    
    # Run GPU command
    result = subprocess.run(cmd_gpu, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print("  NVENC GPU transcode failed or not available. Falling back to CPU...")
        subprocess.run(cmd_cpu, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print("  High-res rendering proxy generated successfully with GPU NVENC.")
        
    return render_proxy_path


def merge_contiguous_slots(slots):
    if not slots:
        return []
    
    merged = []
    current = slots[0]
    
    for s in slots[1:]:
        is_same_video = (current.video_path == s.video_path)
        is_contiguous_timeline = (abs(current.end_time - s.start_time) < 0.01)
        
        # Check if clip is contiguous
        expected_clip_start = current.clip_start + current.clip_duration
        is_contiguous_clip = (abs(expected_clip_start - s.clip_start) < 0.05)
        
        is_same_audio = (current.keep_audio == s.keep_audio)
        is_same_orig_audio = (getattr(current, 'use_original_audio', False) == getattr(s, 'use_original_audio', False))
        
        trans = getattr(s, 'transition', 'none')
        if trans is None:
            trans = 'none'
        has_no_transition = (trans.lower() == 'none')
        
        is_same_transcript = (getattr(current, 'transcript', '') == getattr(s, 'transcript', ''))
        is_same_speaker = (getattr(current, 'speaker', '') == getattr(s, 'speaker', ''))
        is_same_dialogue_ind = (getattr(current, 'dialogue_independent', False) == getattr(s, 'dialogue_independent', False))
        is_same_d_video_path = (getattr(current, 'dialogue_video_path', None) == getattr(s, 'dialogue_video_path', None))
        
        if (is_same_video and is_contiguous_timeline and is_contiguous_clip and 
            is_same_audio and is_same_orig_audio and has_no_transition and 
            is_same_transcript and is_same_speaker and
            is_same_dialogue_ind and is_same_d_video_path):
            
            # Extend current slot
            current.end_time = s.end_time
            current.clip_duration = current.clip_duration + s.clip_duration
        else:
            merged.append(current)
            current = s
            
    merged.append(current)
    return merged


def get_video_duration(video_path):
    # Try querying SQLite database data/metadata.db first
    try:
        import sqlite3
        db_path = "data/metadata.db"
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            abs_path = os.path.abspath(video_path)
            cursor.execute("SELECT duration FROM videos WHERE original_path = ? OR proxy_path = ?", (video_path, video_path))
            row = cursor.fetchone()
            if not row:
                cursor.execute("SELECT duration FROM videos WHERE original_path = ? OR proxy_path = ?", (abs_path, abs_path))
                row = cursor.fetchone()
            conn.close()
            if row and row[0] > 0:
                return float(row[0])
    except Exception as e:
        print(f"Error querying database for video duration of {video_path}: {e}")

    # Fallback to ffprobe
    try:
        import shutil
        import json
        import subprocess
        ffprobe = shutil.which("ffprobe") or "ffprobe"
        cmd = [
            ffprobe, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "format=duration",
            "-of", "json", video_path
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        data = json.loads(out)
        duration = float(data.get("format", {}).get("duration", 0.0))
        if duration > 0:
            return duration
    except Exception as e:
        # Also try resolved proxy path in data/proxies
        try:
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            proxy_path = os.path.abspath(f"data/proxies/{base_name}_render.mp4")
            if os.path.exists(proxy_path):
                cmd[6] = proxy_path
                out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
                data = json.loads(out)
                duration = float(data.get("format", {}).get("duration", 0.0))
                if duration > 0:
                    return duration
        except:
            pass
        print(f"Error running ffprobe for video duration of {video_path}: {e}")
        
    return None


def resolve_inherited_slots(slots, lyrics):
    if not lyrics:
        return slots
        
    slots = sorted(slots, key=lambda s: s.start_time)
    resolved_slots = []
    
    for lyric in lyrics:
        lyric_start = lyric.get("start", 0.0)
        lyric_end = lyric.get("end", 0.0)
        
        matching_slots = [s for s in slots if lyric_start - 0.01 <= s.start_time < lyric_end - 0.01]
        
        if matching_slots:
            resolved_slots.extend(matching_slots)
        else:
            prev_slots = [s for s in slots if s.start_time < lyric_start - 0.01]
            base_slot = None
            if prev_slots:
                base_slot = prev_slots[-1]
            if not base_slot and slots:
                base_slot = slots[0]
                
            if base_slot:
                clip_start = base_slot.clip_start + (lyric_start - base_slot.start_time)
                
                # Fetch video duration to clamp clip_start
                video_dur = get_video_duration(base_slot.video_path)
                if video_dur is not None and video_dur > 0:
                    if clip_start > video_dur - 0.1:
                        clip_start = max(0.0, video_dur - 0.1)
                
                # Make sure clip_start is non-negative and clip_duration is valid
                clip_start = max(0.0, clip_start)
                clip_duration = max(0.0, lyric_end - lyric_start)
                
                inherited_slot = TimelineSlot(
                    start_time=lyric_start,
                    end_time=lyric_end,
                    video_path=base_slot.video_path,
                    clip_start=clip_start,
                    clip_duration=clip_duration,
                    keep_audio=base_slot.keep_audio,
                    transcript=base_slot.transcript,
                    speaker=base_slot.speaker,
                    speaker_manual=base_slot.speaker_manual,
                    dialogue_independent=base_slot.dialogue_independent,
                    dialogue_start_time=base_slot.dialogue_start_time,
                    dialogue_end_time=base_slot.dialogue_end_time,
                    dialogue_clip_start=base_slot.dialogue_clip_start,
                    dialogue_video_path=base_slot.dialogue_video_path,
                    use_original_audio=base_slot.use_original_audio,
                    transition=None
                )
                resolved_slots.append(inherited_slot)
                
    return resolved_slots


def render_video(req: RenderRequest, callback=None):
    if callback: callback(2, "正在解析卡点对齐与素材映射...")
    try:
        # Resolve inherited (fallback) slots if there are gaps
        if req.lyrics and req.slots:
            req.slots = resolve_inherited_slots(req.slots, req.lyrics)
            
        # Clamp all slots and dialogue clips to their video duration to prevent black screen
        for slot in req.slots:
            if slot.video_path:
                dur = get_video_duration(slot.video_path)
                if dur and dur > 0:
                    if slot.clip_start > dur - 0.1:
                        old_start = slot.clip_start
                        slot.clip_start = max(0.0, dur - 0.1)
                        print(f"Clamped slot clip_start for {slot.video_path} from {old_start:.2f}s to {slot.clip_start:.2f}s (dur={dur:.2f}s)")
                        
        if req.dialogue_clips:
            for d_clip in req.dialogue_clips:
                if d_clip.video_path:
                    dur = get_video_duration(d_clip.video_path)
                    if dur and dur > 0:
                        if d_clip.clip_start > dur - 0.1:
                            old_start = d_clip.clip_start
                            d_clip.clip_start = max(0.0, dur - 0.1)
                            print(f"Clamped dialogue clip_start for {d_clip.video_path} from {old_start:.2f}s to {d_clip.clip_start:.2f}s (dur={dur:.2f}s)")

        # Range Render Pre-processing
        range_start = req.range_start
        range_end = req.range_end
        original_duration = req.slots[-1].end_time if req.slots else 0.0
        
        if range_start is not None or range_end is not None:
            r_start = range_start if range_start is not None else 0.0
            r_end = range_end if (range_end is not None and range_end > 0) else original_duration
            
            if r_start < 0: r_start = 0.0
            if r_end > original_duration: r_end = original_duration
            
            if r_end > r_start:
                range_duration = r_end - r_start
                
                # 1. Filter and shift slots
                new_slots = []
                for slot in req.slots:
                    if slot.end_time > r_start and slot.start_time < r_end:
                        new_start = max(0.0, slot.start_time - r_start)
                        new_end = min(range_duration, slot.end_time - r_start)
                        
                        shift_offset = 0.0
                        if slot.start_time < r_start:
                            shift_offset = r_start - slot.start_time
                            
                        new_clip_start = slot.clip_start + shift_offset
                        new_clip_duration = new_end - new_start
                        
                        new_slots.append(TimelineSlot(
                            start_time=new_start,
                            end_time=new_end,
                            video_path=slot.video_path,
                            clip_start=new_clip_start,
                            clip_duration=new_clip_duration,
                            keep_audio=slot.keep_audio,
                            transcript=slot.transcript,
                            speaker=slot.speaker,
                            speaker_manual=slot.speaker_manual,
                            dialogue_independent=slot.dialogue_independent,
                            dialogue_start_time=slot.dialogue_start_time,
                            dialogue_end_time=slot.dialogue_end_time,
                            dialogue_clip_start=slot.dialogue_clip_start,
                            dialogue_video_path=slot.dialogue_video_path,
                            use_original_audio=slot.use_original_audio,
                            transition=slot.transition
                        ))
                req.slots = new_slots
                
                # 2. Filter and shift lyrics
                if req.lyrics:
                    new_lyrics = []
                    for lyric in req.lyrics:
                        l_start = lyric.get("start", 0.0)
                        l_end = lyric.get("end", 0.0)
                        if l_end > r_start and l_start < r_end:
                            new_l_start = max(0.0, l_start - r_start)
                            new_l_end = min(range_duration, l_end - r_start)
                            new_lyric = lyric.copy()
                            new_lyric["start"] = new_l_start
                            new_lyric["end"] = new_l_end
                            new_lyrics.append(new_lyric)
                    req.lyrics = new_lyrics
                
                # 3. Filter and shift independent dialogue clips
                if req.dialogue_clips:
                    new_dialogue_clips = []
                    for d_clip in req.dialogue_clips:
                        if d_clip.end_time > r_start and d_clip.start_time < r_end:
                            new_start = max(0.0, d_clip.start_time - r_start)
                            new_end = min(range_duration, d_clip.end_time - r_start)
                            
                            shift_offset = 0.0
                            if d_clip.start_time < r_start:
                                shift_offset = r_start - d_clip.start_time
                                
                            new_clip_start = d_clip.clip_start + shift_offset
                            new_clip_duration = new_end - new_start
                            
                            d_clip.start_time = new_start
                            d_clip.end_time = new_end
                            d_clip.clip_start = new_clip_start
                            d_clip.clip_duration = new_clip_duration
                            new_dialogue_clips.append(d_clip)
                    req.dialogue_clips = new_dialogue_clips
                
                # 4. Crop audio using FFmpeg
                import hashlib
                audio_cache_key = f"{req.audio_path}_{r_start}_{range_duration}"
                audio_hash = hashlib.md5(audio_cache_key.encode("utf-8")).hexdigest()
                os.makedirs("data/trimmed_cache", exist_ok=True)
                cropped_audio_path = os.path.abspath(f"data/trimmed_cache/audio_{audio_hash}{os.path.splitext(req.audio_path)[1]}")
                
                if not os.path.exists(cropped_audio_path):
                    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
                    crop_cmd = [
                        ffmpeg, "-y",
                        "-ss", str(r_start),
                        "-t", str(range_duration),
                        "-i", req.audio_path,
                        "-c:a", "copy",
                        cropped_audio_path
                    ]
                    print(f"Cropping BGM audio: {' '.join(crop_cmd)}")
                    subprocess.run(crop_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                req.audio_path = cropped_audio_path

        # Merge contiguous slots that refer to the same video file and play continuously
        req.slots = merge_contiguous_slots(req.slots)

        # Save render decision list data to hyperframes template directory
        # Translate local audio path to absolute/web path
        abs_audio = os.path.abspath(req.audio_path)
        
        # Prepare slots for HyperFrames rendering
        # Clean up old temp videos and dialogue videos
        num_slots = len(req.slots)
        num_dialogues = len(req.dialogue_clips) if req.dialogue_clips else 0
        for f in os.listdir("hyperframes_template"):
            if f.startswith("temp_video_") and f.endswith(".mp4"):
                try:
                    idx = int(f.replace("temp_video_", "").replace(".mp4", ""))
                    if idx >= num_slots:
                        os.remove(os.path.join("hyperframes_template", f))
                except (ValueError, OSError):
                    pass
            elif f.startswith("temp_dialogue_") and f.endswith(".mp4"):
                try:
                    idx = int(f.replace("temp_dialogue_", "").replace(".mp4", ""))
                    if idx >= num_dialogues:
                        os.remove(os.path.join("hyperframes_template", f))
                except (ValueError, OSError):
                    pass
                    
        # Prepare slots using relative paths relative to hyperframes_template/
        # Prepare slots and hard links inside hyperframes_template/
        slots_data = []
        num_slots = len(req.slots)
        for slot_idx, slot in enumerate(req.slots):
            if callback:
                callback(int(5 + (slot_idx / num_slots) * 15), f"正在裁剪与对准视频卡点 {slot_idx + 1}/{num_slots}...")
            abs_video_path = os.path.abspath(slot.video_path)
            resolved_path = abs_video_path
            
            # If format is not directly supported in Chrome, map to high-res rendering proxy
            if abs_video_path.lower().endswith(('.mkv', '.avi', '.mov', '.flv')):
                use_orig = getattr(slot, 'use_original_audio', False)
                base_name = os.path.splitext(os.path.basename(abs_video_path))[0]
                backup_path = os.path.abspath(f"data/proxies_backup_20260623-013023/{base_name}_render.mp4")
                if use_orig:
                    if os.path.exists(backup_path):
                        resolved_path = backup_path
                        print(f"Mapped to backup original proxy with full background sound: {resolved_path}")
                    else:
                        resolved_path = abs_video_path
                        print(f"Backup original proxy missing. Falling back to original video file for full background sound: {resolved_path}")
                else:
                    resolved_path = os.path.abspath(get_high_res_render_proxy(abs_video_path))
                    print(f"Mapped unsupported video format {abs_video_path} to high-res proxy {resolved_path}")
            
            import hashlib
            slot_duration = slot.end_time - slot.start_time
            
            slot_vol = req.dialogue_volume if (slot.keep_audio and req.dialogue_volume is not None) else 1.0
            # Construct a unique cache key based on video path, clip start, duration, and volume (if keeping audio)
            cache_key_str = f"{resolved_path}_{slot.clip_start}_{slot_duration}_{slot_vol}"
            cache_hash = hashlib.md5(cache_key_str.encode("utf-8")).hexdigest()
            cache_dir = os.path.abspath("data/trimmed_cache")
            os.makedirs(cache_dir, exist_ok=True)
            cache_path = os.path.join(cache_dir, f"{cache_hash}.mp4")
            
            # Create a unique trimmed video in hyperframes_template for each slot
            temp_name = f"temp_video_{slot_idx}.mp4"
            temp_path = os.path.join("hyperframes_template", temp_name)
            
            use_cached = False
            if os.path.exists(cache_path):
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    os.link(cache_path, temp_path)
                    use_cached = True
                    print(f"Reused cached trim for slot {slot_idx}: {cache_path}")
                except Exception:
                    try:
                        shutil.copy2(cache_path, temp_path)
                        use_cached = True
                        print(f"Copied cached trim for slot {slot_idx}: {cache_path}")
                    except Exception as ce:
                        print(f"Failed to reuse cache for slot {slot_idx}: {ce}")
            
            ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
            clip_start_val = 0.0
            clip_dur_val = slot_duration
            
            if not use_cached:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
                
                # Trim the video segment directly without any padding or delay
                trim_cmd = [
                    ffmpeg, "-y",
                    "-ss", str(slot.clip_start),
                    "-t", str(slot_duration),
                    "-i", resolved_path,
                    "-c:v", "libx264", "-crf", "18", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                ]
                if slot.keep_audio and slot_vol != 1.0:
                    trim_cmd.extend(["-af", f"volume={slot_vol},alimiter=limit=0.99", "-c:a", "aac", "-b:a", "192k"])
                else:
                    trim_cmd.extend(["-c:a", "aac", "-b:a", "192k"])
                trim_cmd.append(temp_path)
                
                print(f"Trimming slot {slot_idx}: {resolved_path} from {slot.clip_start}s to {slot.clip_start + slot_duration}s...")
                trim_res = subprocess.run(trim_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                if trim_res.returncode == 0:
                    try:
                        shutil.copy2(temp_path, cache_path)
                    except Exception as ce:
                        print(f"Failed to save to cache: {ce}")
                else:
                    print(f"  Trim failed: {trim_res.stderr.decode()[:200]}. Falling back to link/copy...")
                    try:
                        os.link(resolved_path, temp_path)
                    except Exception:
                        shutil.copy2(resolved_path, temp_path)
                    clip_start_val = slot.clip_start
                    clip_dur_val = slot.clip_duration
                
            slots_data.append({
                "startTime": slot.start_time,
                "endTime": slot.end_time,
                "videoPath": temp_name,
                "clipStart": clip_start_val,
                "clipDuration": clip_dur_val,
                "keepAudio": slot.keep_audio,
                "transcript": slot.transcript,
                "speaker": slot.speaker,
                "transition": getattr(slot, "transition", None)
            })

        # Prepare independent dialogue clips for HyperFrames rendering
        dialogue_clips_data = []
        if req.dialogue_clips:
            num_dialogues = len(req.dialogue_clips)
            for d_idx, d_clip in enumerate(req.dialogue_clips):
                if callback:
                    callback(int(20 + (d_idx / num_dialogues) * 10), f"正在裁剪与对齐台词音频 {d_idx + 1}/{num_dialogues}...")
                abs_video_path = os.path.abspath(d_clip.video_path)
                resolved_path = abs_video_path
                
                # If format is not directly supported in Chrome, map to high-res rendering proxy
                if abs_video_path.lower().endswith(('.mkv', '.avi', '.mov', '.flv')):
                    use_orig = getattr(d_clip, 'use_original_audio', False)
                    base_name = os.path.splitext(os.path.basename(abs_video_path))[0]
                    backup_path = os.path.abspath(f"data/proxies_backup_20260623-013023/{base_name}_render.mp4")
                    if use_orig:
                        if os.path.exists(backup_path):
                            resolved_path = backup_path
                            print(f"Mapped independent dialogue to backup original proxy: {resolved_path}")
                        else:
                            resolved_path = abs_video_path
                            print(f"Backup original proxy missing. Falling back to original video file: {resolved_path}")
                    else:
                        resolved_path = os.path.abspath(get_high_res_render_proxy(abs_video_path))
                        print(f"Mapped unsupported video format {abs_video_path} to high-res proxy {resolved_path}")
                
                import hashlib
                d_duration = d_clip.end_time - d_clip.start_time
                
                dialogue_vol = req.dialogue_volume if req.dialogue_volume is not None else 1.0
                # Construct a unique cache key based on video path, clip start, duration, and dialogue volume
                cache_key_str = f"dialogue_{resolved_path}_{d_clip.clip_start}_{d_duration}_{dialogue_vol}"
                cache_hash = hashlib.md5(cache_key_str.encode("utf-8")).hexdigest()
                cache_dir = os.path.abspath("data/trimmed_cache")
                os.makedirs(cache_dir, exist_ok=True)
                cache_path = os.path.join(cache_dir, f"{cache_hash}.mp4")
                
                temp_name = f"temp_dialogue_{d_idx}.mp4"
                temp_path = os.path.join("hyperframes_template", temp_name)
                
                use_cached = False
                if os.path.exists(cache_path):
                    try:
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                        os.link(cache_path, temp_path)
                        use_cached = True
                        print(f"Reused cached trim for dialogue {d_idx}: {cache_path}")
                    except Exception:
                        try:
                            shutil.copy2(cache_path, temp_path)
                            use_cached = True
                            print(f"Copied cached trim for dialogue {d_idx}: {cache_path}")
                        except Exception as ce:
                            print(f"Failed to reuse cache for dialogue {d_idx}: {ce}")
                
                ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
                clip_start_val = 0.0
                clip_dur_val = d_duration
                
                if not use_cached:
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except OSError:
                            pass
                    
                    trim_cmd = [
                        ffmpeg, "-y",
                        "-ss", str(d_clip.clip_start),
                        "-t", str(d_duration),
                        "-i", resolved_path,
                        "-c:v", "libx264", "-crf", "18", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p",
                    ]
                    if dialogue_vol != 1.0:
                        trim_cmd.extend(["-af", f"volume={dialogue_vol},alimiter=limit=0.99", "-c:a", "aac", "-b:a", "192k"])
                    else:
                        trim_cmd.extend(["-c:a", "aac", "-b:a", "192k"])
                    trim_cmd.append(temp_path)
                    
                    print(f"Trimming dialogue {d_idx}: {resolved_path} from {d_clip.clip_start}s to {d_clip.clip_start + d_duration}s...")
                    trim_res = subprocess.run(trim_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                    if trim_res.returncode == 0:
                        try:
                            shutil.copy2(temp_path, cache_path)
                        except Exception as ce:
                            print(f"Failed to save to cache: {ce}")
                    else:
                        print(f"  Dialogue trim failed: {trim_res.stderr.decode()[:200]}. Falling back to link/copy...")
                        try:
                            os.link(resolved_path, temp_path)
                        except Exception:
                            shutil.copy2(resolved_path, temp_path)
                        clip_start_val = d_clip.clip_start
                        clip_dur_val = d_duration
                    
                dialogue_clips_data.append({
                    "startTime": d_clip.start_time,
                    "endTime": d_clip.end_time,
                    "videoPath": temp_name,
                    "clipStart": clip_start_val,
                    "clipDuration": clip_dur_val,
                    "transcript": d_clip.transcript,
                    "speaker": d_clip.speaker
                })
            
        # Determine normalized volumes for mixing (since HTML volume is clamped to 1.0)
        dialogue_volume_input = req.dialogue_volume if req.dialogue_volume is not None else 1.0
        music_volume_input = req.music_volume if req.music_volume is not None else 1.0
        
        music_volume_rendered = music_volume_input
        if dialogue_volume_input > 1.0:
            dialogue_volume_rendered = 1.0
        else:
            dialogue_volume_rendered = dialogue_volume_input

        render_data = {
            "slots": slots_data,
            "dialogueClips": dialogue_clips_data,
            "audioPath": abs_audio,
            "lyrics": req.lyrics if req.lyrics else [],
            "musicVolume": music_volume_rendered,
            "dialogueVolume": dialogue_volume_rendered,
            "duration": req.slots[-1].end_time if req.slots else 0.0
        }
        
        # Write render data JSON inside hyperframes template directory (with setup_name isolation)
        render_data_filename = "render_data.json"
        if req.setup_name:
            render_data_filename = f"render_data_{req.setup_name}.json"
        with open(os.path.join("hyperframes_template", render_data_filename), "w", encoding="utf-8") as f:
            json.dump(render_data, f, indent=2)
            
        # Copy audio file to template directory for browser testing/playing
        audio_ext = os.path.splitext(req.audio_path)[1]
        audio_filename = "audio" + audio_ext
        if req.setup_name:
            audio_filename = f"audio_{req.setup_name}{audio_ext}"
        dest_audio = os.path.join("hyperframes_template", audio_filename)
        shutil.copy2(req.audio_path, dest_audio)
        
        # Dynamically update the index.html with the correct audio file name, video elements, and duration
        try:
            import re
            duration_val = req.slots[-1].end_time if req.slots else 0.0
            
            # Generate static video elements HTML
            video_tags = []
            dialogue_vol = dialogue_volume_rendered
            for i, slot in enumerate(slots_data):
                slot_duration = slot["endTime"] - slot["startTime"]
                # Omit 'muted' and set volume if this slot keeps audio so HyperFrames extracts its audio track
                audio_attr = f'volume="{dialogue_vol}" data-volume="{dialogue_vol}"' if slot.get("keepAudio") else 'muted'
                video_tags.append(
                    f'<video class="video-layer" id="video_{i}" src="{slot["videoPath"]}" data-start="{slot["startTime"]}" data-duration="{slot_duration}" preload="auto" {audio_attr}></video>'
                )
            
            # Generate static independent dialogue audio elements HTML
            for j, d_clip in enumerate(dialogue_clips_data):
                d_dur = d_clip["endTime"] - d_clip["startTime"]
                # Use <audio> tag for independent dialogue. This guarantees HyperFrames extracts only its audio track
                # and doesn't visually display or extract video frames.
                video_tags.append(
                    f'<audio class="dialogue-layer" id="dialogue_video_{j}" src="{d_clip["videoPath"]}" data-start="{d_clip["startTime"]}" data-duration="{d_dur}" preload="auto" volume="{dialogue_vol}" data-volume="{dialogue_vol}" data-track-index="2"></audio>'
                )
                
            video_elements_html = "\n    ".join(video_tags)
            
            with open("hyperframes_template/index.template.html", "r", encoding="utf-8") as f:
                html_content = f.read()
                
            # Replace audio src and data-volume attributes
            music_vol = music_volume_rendered
            html_content = re.sub(
                r'<audio id="bg-audio" src="[^"]*"[^>]*>',
                f'<audio id="bg-audio" src="{audio_filename}" data-start="0" data-duration="{duration_val}" data-track-index="0" data-volume="{music_vol}"></audio>',
                html_content
            )
            # Replace data-duration on viewport tag
            html_content = re.sub(
                r'data-duration="[^"]*"',
                f'data-duration="{duration_val}"',
                html_content
            )
            # Replace video elements placeholder
            html_content = re.sub(
                r'<!-- VIDEO_ELEMENTS_PLACEHOLDER -->',
                video_elements_html,
                html_content
            )
            
            # Inject custom lyric style CSS if provided
            if getattr(req, "lyric_style_css", None):
                css_injection = f"\n<style>\n#lyrics-container {{\n    {req.lyric_style_css}\n}}\n</style>\n</head>"
                html_content = html_content.replace("</head>", css_injection)
            
            # Replace custom lyrics CSS if provided
            if req.lyric_style_css:
                layout_style = "position: absolute; bottom: 5%; left: 50%; transform: translateX(-50%); z-index: 999; pointer-events: none; max-width: 80%; line-height: 1.4; display: none;"
                custom_style = f'style="{layout_style} {req.lyric_style_css}"'
                html_content = re.sub(
                    r'<div id="lyrics-container" style="[^"]*">',
                    f'<div id="lyrics-container" {custom_style}>',
                    html_content
                )
                
            # If isolated setup_name is used, we need index.html to fetch the correct render_data file
            if req.setup_name:
                html_content = html_content.replace("render_data.json", render_data_filename)
                
            index_html_filename = "index.html"
            if req.setup_name:
                index_html_filename = f"index_{req.setup_name}.html"
            with open(os.path.join("hyperframes_template", index_html_filename), "w", encoding="utf-8") as f:
                f.write(html_content)
        except Exception as e:
            print(f"Error updating template attributes dynamically: {e}")
        
        # Call HyperFrames rendering command
        # First we verify if HyperFrames is installed and render
        # Let's write output to output/mv_output.mp4 (with setup_name isolation if specified)
        output_filename = "mv_output.mp4"
        if req.setup_name:
            output_filename = f"mv_output_{req.setup_name}.mp4"
        output_mp4 = os.path.abspath(os.path.join("output", output_filename))
        
        # CLI command execution: npx --yes hyperframes@<pinned-version> render ...
        # For security and compatibility, we will prepare the command but not run it blindly.
        # HyperFrames render tool command structure:
        # npx hyperframes render <template_index_html_path> -o <output_mp4> --data <render_data_json_path>
        template_path = os.path.abspath("hyperframes_template")
        data_path = os.path.abspath(os.path.join("hyperframes_template", render_data_filename))
        
        cmd = [
            "npx", "--yes", "hyperframes@0.6.119", "render", template_path,
            "-o", output_mp4,
            "--data", data_path,
            "-f", "60",
            "-q", "high",
            "--crf", "12",
            "--video-frame-format", "png",
            "--resolution", "landscape",
            "--workers", "1",
            "--low-memory-mode",
            "--no-browser-gpu",
            "--protocol-timeout", "1200000",
            "--browser-timeout", "300"
        ]
        if req.setup_name:
            # Tell HyperFrames to render our custom composition HTML instead of index.html
            cmd.extend(["-c", index_html_filename])
        
        print(f"Executing render command: {' '.join(cmd)}")
        if callback:
            callback(30, "正在启动 Headless Chrome 进行 HTML 动画捕捉与视频帧导出...")
        # Prep local node/bin to env PATH
        env = os.environ.copy()
        local_node_bin = os.path.abspath("node/bin")
        env["PATH"] = local_node_bin + os.pathsep + env.get("PATH", "")
        # Keep npm/npx non-interactive when FastAPI runs as a background server.
        env["CI"] = env.get("CI", "1")
        env["npm_config_yes"] = "true"
        env["npm_config_fund"] = "false"
        env["npm_config_audit"] = "false"
        # Enable HyperFrames frame extraction cache
        env["HYPERFRAMES_EXTRACT_CACHE_DIR"] = os.path.expanduser("~/.cache/hyperframes/extracted_frames")
        
        # Run render command
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            bufsize=1
        )
        
        stdout_lines = []
        if process.stdout:
            import re
            for line in process.stdout:
                print(line, end="", flush=True)
                stdout_lines.append(line)
                if callback:
                    # Remove ANSI color codes
                    clean_line = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', line)
                    # Search for percentage
                    percent_match = re.search(r'(\d+)%\s+(.*)', clean_line)
                    if percent_match:
                        percent_val = int(percent_match.group(1))
                        msg = percent_match.group(2).strip()
                        overall_percent = int(30 + (percent_val / 100.0) * 65)
                        callback(overall_percent, f"HyperFrames: {msg}")
                    else:
                        clean_stripped = clean_line.strip()
                        if clean_stripped:
                            callback(None, clean_stripped)
        
        process.wait()
        returncode = process.returncode
        stdout_content = "".join(stdout_lines)
        
        if returncode != 0:
            print(f"HyperFrames render error: {stdout_content}")
            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "detail": f"Render failed: {stdout_content}",
                    "cmd": " ".join(cmd)
                }
            )
            
        return {
            "status": "success",
            "output_path": output_mp4,
            "output_url": "/output/mv_output.mp4"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def get_path_url(abs_path):
    path = abs_path.replace('\\', '/')
    if len(path) > 1 and path[1] == ':':
        path = '/' + path
    return "file://localhost" + urllib.parse.quote(path)

def export_xml(req: RenderRequest):
    try:
        import xml.sax.saxutils
        
        # Calculate frames based on timebase 24, NTSC true (23.976fps)
        def to_frames(secs):
            return int(round(secs * 24.0))
            
        bgm_path = os.path.abspath(req.audio_path)
        bgm_name = os.path.basename(bgm_path)
        bgm_url = get_path_url(bgm_path)
        
        bgm_duration_secs = req.slots[-1].end_time if req.slots else 0.0
        bgm_duration_frames = to_frames(bgm_duration_secs)
        
        video_clips = []
        dialogue_clips_l = []
        dialogue_clips_r = []
        
        # Map video files to unique indices for FCP XML file references
        video_files = {}
        for slot in req.slots:
            abs_v_path = os.path.abspath(slot.video_path)
            if abs_v_path not in video_files:
                video_files[abs_v_path] = len(video_files) + 1
                
        if req.dialogue_clips:
            for d_clip in req.dialogue_clips:
                abs_v_path = os.path.abspath(d_clip.video_path)
                if abs_v_path not in video_files:
                    video_files[abs_v_path] = len(video_files) + 1
                    
        written_files = set()
        
        for i, slot in enumerate(req.slots):
            abs_v_path = os.path.abspath(slot.video_path)
            file_index = video_files[abs_v_path]
            clip_name = os.path.basename(abs_v_path)
            v_url = get_path_url(abs_v_path)
            
            start_f = to_frames(slot.start_time)
            end_f = to_frames(slot.end_time)
            in_f = to_frames(slot.clip_start)
            out_f = to_frames(slot.clip_start + (slot.end_time - slot.start_time))
            
            source_dur_secs = slot.clip_duration if slot.clip_duration else (slot.end_time - slot.start_time)
            source_dur_frames = to_frames(max(source_dur_secs, 1000.0))
            
            if file_index not in written_files:
                file_tag = f"""<file id="file-{file_index}">
              <name>{xml.sax.saxutils.escape(clip_name)}</name>
              <pathurl>{xml.sax.saxutils.escape(v_url)}</pathurl>
              <rate>
                <timebase>24</timebase>
                <ntsc>TRUE</ntsc>
              </rate>
              <duration>{source_dur_frames}</duration>
            </file>"""
                written_files.add(file_index)
            else:
                file_tag = f"""<file id="file-{file_index}"/>"""
            
            # Video track clip item
            v_clip = f"""          <clipitem id="video-clip-{i}">
            <name>{xml.sax.saxutils.escape(clip_name)}</name>
            <duration>{source_dur_frames}</duration>
            <rate>
              <timebase>24</timebase>
              <ntsc>TRUE</ntsc>
            </rate>
            <in>{in_f}</in>
            <out>{out_f}</out>
            <start>{start_f}</start>
            <end>{end_f}</end>
            {file_tag}
          </clipitem>"""
            video_clips.append(v_clip)
            
            # Dialogue tracks clip items (if keep_audio is enabled)
            if slot.keep_audio:
                audio_clip_l = f"""          <clipitem id="audio-clip-{i}-l">
            <name>{xml.sax.saxutils.escape(clip_name)}</name>
            <duration>{source_dur_frames}</duration>
            <rate>
              <timebase>24</timebase>
              <ntsc>TRUE</ntsc>
            </rate>
            <in>{in_f}</in>
            <out>{out_f}</out>
            <start>{start_f}</start>
            <end>{end_f}</end>
            <file id="file-{file_index}"/>
          </clipitem>"""
                dialogue_clips_l.append(audio_clip_l)
                
                audio_clip_r = f"""          <clipitem id="audio-clip-{i}-r">
            <name>{xml.sax.saxutils.escape(clip_name)}</name>
            <duration>{source_dur_frames}</duration>
            <rate>
              <timebase>24</timebase>
              <ntsc>TRUE</ntsc>
            </rate>
            <in>{in_f}</in>
            <out>{out_f}</out>
            <start>{start_f}</start>
            <end>{end_f}</end>
            <file id="file-{file_index}"/>
          </clipitem>"""
                dialogue_clips_r.append(audio_clip_r)
                
        independent_clips_l = []
        independent_clips_r = []
        if req.dialogue_clips:
            for i, d_clip in enumerate(req.dialogue_clips):
                abs_v_path = os.path.abspath(d_clip.video_path)
                file_index = video_files[abs_v_path]
                clip_name = os.path.basename(abs_v_path)
                v_url = get_path_url(abs_v_path)
                
                start_f = to_frames(d_clip.start_time)
                end_f = to_frames(d_clip.end_time)
                in_f = to_frames(d_clip.clip_start)
                out_f = to_frames(d_clip.clip_start + (d_clip.end_time - d_clip.start_time))
                
                source_dur_secs = d_clip.clip_duration if d_clip.clip_duration else (d_clip.end_time - d_clip.start_time)
                source_dur_frames = to_frames(max(source_dur_secs, 1000.0))
                
                if file_index not in written_files:
                    file_tag = f"""<file id="file-{file_index}">
              <name>{xml.sax.saxutils.escape(clip_name)}</name>
              <pathurl>{xml.sax.saxutils.escape(v_url)}</pathurl>
              <rate>
                <timebase>24</timebase>
                <ntsc>TRUE</ntsc>
              </rate>
              <duration>{source_dur_frames}</duration>
            </file>"""
                    written_files.add(file_index)
                else:
                    file_tag = f"""<file id="file-{file_index}"/>"""
                
                audio_clip_l = f"""          <clipitem id="independent-clip-{i}-l">
            <name>{xml.sax.saxutils.escape(clip_name)} (独立台词)</name>
            <duration>{source_dur_frames}</duration>
            <rate>
              <timebase>24</timebase>
              <ntsc>TRUE</ntsc>
            </rate>
            <in>{in_f}</in>
            <out>{out_f}</out>
            <start>{start_f}</start>
            <end>{end_f}</end>
            {file_tag}
          </clipitem>"""
                independent_clips_l.append(audio_clip_l)
                
                audio_clip_r = f"""          <clipitem id="independent-clip-{i}-r">
            <name>{xml.sax.saxutils.escape(clip_name)} (独立台词)</name>
            <duration>{source_dur_frames}</duration>
            <rate>
              <timebase>24</timebase>
              <ntsc>TRUE</ntsc>
            </rate>
            <in>{in_f}</in>
            <out>{out_f}</out>
            <start>{start_f}</start>
            <end>{end_f}</end>
            <file id="file-{file_index}"/>
          </clipitem>"""
                independent_clips_r.append(audio_clip_r)
                
        bgm_clip_l = f"""          <clipitem id="bgm-clip-l">
            <name>{xml.sax.saxutils.escape(bgm_name)}</name>
            <duration>{bgm_duration_frames}</duration>
            <rate>
              <timebase>24</timebase>
              <ntsc>TRUE</ntsc>
            </rate>
            <in>0</in>
            <out>{bgm_duration_frames}</out>
            <start>0</start>
            <end>{bgm_duration_frames}</end>
            <file id="bgm-file">
              <name>{xml.sax.saxutils.escape(bgm_name)}</name>
              <pathurl>{xml.sax.saxutils.escape(bgm_url)}</pathurl>
              <rate>
                <timebase>24</timebase>
                <ntsc>TRUE</ntsc>
              </rate>
              <duration>{bgm_duration_frames}</duration>
            </file>
          </clipitem>"""
          
        bgm_clip_r = f"""          <clipitem id="bgm-clip-r">
            <name>{xml.sax.saxutils.escape(bgm_name)}</name>
            <duration>{bgm_duration_frames}</duration>
            <rate>
              <timebase>24</timebase>
              <ntsc>TRUE</ntsc>
            </rate>
            <in>0</in>
            <out>{bgm_duration_frames}</out>
            <start>0</start>
            <end>{bgm_duration_frames}</end>
            <file id="bgm-file"/>
          </clipitem>"""
          
        video_clips_xml = "\n".join(video_clips)
        dialogue_clips_l_xml = "\n".join(dialogue_clips_l)
        dialogue_clips_r_xml = "\n".join(dialogue_clips_r)
        
        num_channels = 4
        extra_tracks = ""
        if independent_clips_l:
            num_channels = 6
            independent_clips_l_xml = "\n".join(independent_clips_l)
            independent_clips_r_xml = "\n".join(independent_clips_r)
            extra_tracks = f"""        <track>
{independent_clips_l_xml}
        </track>
        <track>
{independent_clips_r_xml}
        </track>"""
        
        xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml SYSTEM "fcpxml.dtd">
<xmeml version="5">
  <sequence id="sequence-1">
    <name>AI MV Premiere Project</name>
    <duration>{bgm_duration_frames}</duration>
    <rate>
      <timebase>24</timebase>
      <ntsc>TRUE</ntsc>
    </rate>
    <media>
      <video>
        <format>
          <samplecharacteristics>
            <width>1920</width>
            <height>1080</height>
            <pixelaspectratio>square</pixelaspectratio>
            <rate>
              <timebase>24</timebase>
              <ntsc>TRUE</ntsc>
            </rate>
          </samplecharacteristics>
        </format>
        <track>
{video_clips_xml}
        </track>
      </video>
      <audio>
        <numChannels>{num_channels}</numChannels>
        <track>
{bgm_clip_l}
        </track>
        <track>
{bgm_clip_r}
        </track>
        <track>
{dialogue_clips_l_xml}
        </track>
        <track>
{dialogue_clips_r_xml}
        </track>
{extra_tracks}
      </audio>
    </media>
  </sequence>
</xmeml>
"""
        return Response(content=xml_content, media_type="application/xml")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

