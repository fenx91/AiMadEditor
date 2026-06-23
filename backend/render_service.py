"""HyperFrames rendering and Premiere XML export services."""

import json
import os
import shutil
import subprocess
import urllib.parse

from fastapi import HTTPException, Response
from fastapi.responses import JSONResponse

from schemas import RenderRequest, TimelineSlot


def get_high_res_render_proxy(original_path):
    base_name = os.path.splitext(os.path.basename(original_path))[0]
    proxy_dir = "data/proxies"
    os.makedirs(proxy_dir, exist_ok=True)
    render_proxy_path = os.path.join(proxy_dir, f"{base_name}_render.mp4")
    
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

def render_video(req: RenderRequest):
    try:
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
                            speaker=slot.speaker
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
                
                # 3. Crop audio using FFmpeg
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

        # Save render decision list data to hyperframes template directory
        # Translate local audio path to absolute/web path
        abs_audio = os.path.abspath(req.audio_path)
        
        # Prepare slots for HyperFrames rendering
        # Clean up old temp videos that exceed the current request's slot count
        num_slots = len(req.slots)
        for f in os.listdir("hyperframes_template"):
            if f.startswith("temp_video_") and f.endswith(".mp4"):
                try:
                    idx = int(f.replace("temp_video_", "").replace(".mp4", ""))
                    if idx >= num_slots:
                        os.remove(os.path.join("hyperframes_template", f))
                except (ValueError, OSError):
                    pass
                    
        # Prepare slots using relative paths relative to hyperframes_template/
        # Prepare slots and hard links inside hyperframes_template/
        slots_data = []
        for slot_idx, slot in enumerate(req.slots):
            abs_video_path = os.path.abspath(slot.video_path)
            resolved_path = abs_video_path
            
            # If format is not directly supported in Chrome, map to high-res rendering proxy
            if abs_video_path.lower().endswith(('.mkv', '.avi', '.mov', '.flv')):
                resolved_path = os.path.abspath(get_high_res_render_proxy(abs_video_path))
                print(f"Mapped unsupported video format {abs_video_path} to high-res proxy {resolved_path}")
            
            import hashlib
            slot_duration = slot.end_time - slot.start_time
            
            # Construct a unique cache key based on video path, clip start, and duration
            cache_key_str = f"{resolved_path}_{slot.clip_start}_{slot_duration}"
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
                    "-c:a", "aac", "-b:a", "192k",
                    temp_path
                ]
                
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
                "speaker": slot.speaker
            })
            
        render_data = {
            "slots": slots_data,
            "audioPath": abs_audio,
            "lyrics": req.lyrics if req.lyrics else [],
            "musicVolume": req.music_volume if req.music_volume is not None else 1.0,
            "dialogueVolume": req.dialogue_volume if req.dialogue_volume is not None else 1.0,
            "duration": req.slots[-1].end_time if req.slots else 0.0
        }
        
        # Write render data JSON inside hyperframes template directory
        with open("hyperframes_template/render_data.json", "w", encoding="utf-8") as f:
            json.dump(render_data, f, indent=2)
            
        # Copy audio file to template directory for browser testing/playing
        audio_ext = os.path.splitext(req.audio_path)[1]
        dest_audio = "hyperframes_template/audio" + audio_ext
        shutil.copy2(req.audio_path, dest_audio)
        
        # Dynamically update the index.html with the correct audio file name, video elements, and duration
        try:
            import re
            audio_filename = "audio" + audio_ext
            duration_val = req.slots[-1].end_time if req.slots else 0.0
            
            # Generate static video elements HTML
            video_tags = []
            dialogue_vol = req.dialogue_volume if req.dialogue_volume is not None else 1.0
            for i, slot in enumerate(slots_data):
                slot_duration = slot["endTime"] - slot["startTime"]
                # Omit 'muted' and set volume if this slot keeps audio so HyperFrames extracts its audio track
                audio_attr = f'volume="{dialogue_vol}"' if slot.get("keepAudio") else 'muted'
                video_tags.append(
                    f'<video class="video-layer" id="video_{i}" src="{slot["videoPath"]}" data-start="{slot["startTime"]}" data-duration="{slot_duration}" preload="auto" {audio_attr}></video>'
                )
            video_elements_html = "\n    ".join(video_tags)
            
            with open("hyperframes_template/index.template.html", "r", encoding="utf-8") as f:
                html_content = f.read()
                
            # Replace audio src and data-volume attributes
            music_vol = req.music_volume if req.music_volume is not None else 1.0
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
            
            with open("hyperframes_template/index.html", "w", encoding="utf-8") as f:
                f.write(html_content)
        except Exception as e:
            print(f"Error updating template attributes dynamically: {e}")
        
        # Call HyperFrames rendering command
        # First we verify if HyperFrames is installed and render
        # Let's write output to output/mv_output.mp4
        output_mp4 = os.path.abspath("output/mv_output.mp4")
        
        # CLI command execution: npx hyperframes render ...
        # For security and compatibility, we will prepare the command but not run it blindly.
        # HyperFrames render tool command structure:
        # npx hyperframes render <template_index_html_path> -o <output_mp4> --data <render_data_json_path>
        template_path = os.path.abspath("hyperframes_template")
        data_path = os.path.abspath("hyperframes_template/render_data.json")
        
        cmd = [
            "npx", "hyperframes", "render", template_path,
            "-o", output_mp4,
            "--data", data_path,
            "--resolution", "landscape",
            "--low-memory-mode",
            "--no-browser-gpu",
            "--workers", "1"
        ]
        
        print(f"Executing render command: {' '.join(cmd)}")
        # Prep local node/bin to env PATH
        env = os.environ.copy()
        local_node_bin = os.path.abspath("node/bin")
        env["PATH"] = local_node_bin + os.pathsep + env.get("PATH", "")
        # Enable HyperFrames frame extraction cache
        env["HYPERFRAMES_EXTRACT_CACHE_DIR"] = os.path.expanduser("~/.cache/hyperframes/extracted_frames")
        
        # Run render command
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            bufsize=1
        )
        
        stdout_lines = []
        if process.stdout:
            for line in process.stdout:
                print(line, end="", flush=True)
                stdout_lines.append(line)
        
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
            <file id="file-{file_index}">
              <name>{xml.sax.saxutils.escape(clip_name)}</name>
              <pathurl>{xml.sax.saxutils.escape(v_url)}</pathurl>
              <rate>
                <timebase>24</timebase>
                <ntsc>TRUE</ntsc>
              </rate>
              <duration>{source_dur_frames}</duration>
            </file>
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
        <numChannels>4</numChannels>
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
      </audio>
    </media>
  </sequence>
</xmeml>
"""
        return Response(content=xml_content, media_type="application/xml")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

