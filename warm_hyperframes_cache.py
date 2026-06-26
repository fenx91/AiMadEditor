import json
import os
import subprocess

# Setup paths
workspace_dir = "/home/fenxy/editor"
template_dir = os.path.join(workspace_dir, "hyperframes_template")
render_data_path = os.path.join(template_dir, "render_data.json")
backup_path = os.path.join(template_dir, "render_data.json.bak")

# Load original render data
with open(render_data_path, "r", encoding="utf-8") as f:
    original_data = json.load(f)

original_slots = original_data["slots"]
total_slots = len(original_slots)
print(f"Total slots: {total_slots}")

# Backup original file
with open(backup_path, "w", encoding="utf-8") as f:
    json.dump(original_data, f, indent=2)

try:
    # We will do chunks of 15 slots
    chunk_sizes = [15, 30, 45, 60, total_slots]
    for size in chunk_sizes:
        current_size = min(size, total_slots)
        print(f"\n==================================================")
        print(f"Warming cache with first {current_size} slots...")
        print(f"==================================================")
        
        # Slice slots
        original_data["slots"] = original_slots[:current_size]
        
        # Write modified render data
        with open(render_data_path, "w", encoding="utf-8") as f:
            json.dump(original_data, f, indent=2)
            
        # Run hyperframes render command directly inside WSL
        cmd = [
            "sh", "-c",
            "export PATH=/home/fenxy/editor/node/bin:$PATH; "
            "export HYPERFRAMES_EXTRACT_CACHE_DIR=/home/fenxy/.cache/hyperframes/extracted_frames; "
            "npx hyperframes render /home/fenxy/editor/hyperframes_template "
            "-o /home/fenxy/editor/output/mv_output_temp.mp4 "
            "--data /home/fenxy/editor/hyperframes_template/render_data.json "
            "--resolution landscape --low-memory-mode"
        ]
        
        print(f"Running command: {' '.join(cmd)}")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=workspace_dir)
        print(res.stdout)
        
        if res.returncode != 0:
            print(f"Render failed for chunk {current_size}, but cache might have been partially populated.")

finally:
    # Restore original render data
    print("\nRestoring original render_data.json...")
    with open(backup_path, "r", encoding="utf-8") as f:
        restored_data = json.load(f)
    with open(render_data_path, "w", encoding="utf-8") as f:
        json.dump(restored_data, f, indent=2)
    
    if os.path.exists(backup_path):
        os.remove(backup_path)

print("Warming completed!")
