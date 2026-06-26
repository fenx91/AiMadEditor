import json
log_path = '/mnt/c/Users/xiaoen/.gemini/antigravity/brain/bcd20718-7c27-42a9-86f5-6399bebc730f/.system_generated/logs/transcript.jsonl'
with open(log_path, 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        if 'proxies_backup' in line or 'vocal' in line.lower() or 'sound' in line.lower():
            try:
                data = json.loads(line)
                content = data.get('content')
                if content and ('proxy' in content or 'render' in content or 'mkv' in content):
                    print(f"Line {i} (type={data.get('type')}, source={data.get('source')}):")
                    print(f"  Content: {content[:800]}\n")
            except Exception as e:
                pass
