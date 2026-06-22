"""
集成测试：调用真实 Gemini API Key 测试创意分镜大纲生成与单行改写逻辑。
在项目根目录运行： python tests/test_real_script_plan.py
"""
import os
import sys

# Add project root and backend to path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

if __name__ == '__main__':
    from fastapi.testclient import TestClient
    from backend.app import app, get_gemini_api_key
    
    print("=" * 60)
    print("  开始真实 Gemini 大纲策划与改写集成测试")
    print("=" * 60)
    
    # 1. Check API Key
    api_key = get_gemini_api_key()
    if not api_key:
        print("❌ 错误: 未能在环境变量或 .env 中找到 GOOGLE_API_KEY！请在根目录下配置 .env 文件。")
        sys.exit(1)
    print(f"✅ 找到 Gemini API Key: {api_key[:8]}...{api_key[-4:]}")
    
    # 2. Use TestClient to send a real request to generate_script_plan
    client = TestClient(app)
    
    lyrics_payload = {
        "lyrics": [
            {"text": "Whataya want from me", "start": 0.0, "end": 4.5},
            {"text": "There might have been a time", "start": 4.5, "end": 8.0}
        ],
        "user_vision": "一个孤独的宇航员在荒凉的红色星球上漫步，寻找生命迹象，情感绝望"
    }
    
    print("\n[Step 1] 调用真实 Gemini-2.5-Flash 进行分镜脚本大纲生成...")
    response = client.post("/api/generate_script_plan", json=lyrics_payload)
    
    if response.status_code != 200:
        print(f"❌ 失败: 状态码 {response.status_code}, 错误信息: {response.text}")
        sys.exit(1)
        
    data = response.json()
    print("✅ 大纲生成成功！Gemini 返回数据如下:")
    for item in data:
        print(f"  分镜 #{item['index'] + 1} 歌词: \"{item['lyric']}\"")
        print(f"    视觉描述 (Visual Prompt): {item['visual_prompt']}")
        print(f"    运动度 (Motion): {item['motion_preference']}")
        print(f"    情感基调 (Tone): {item['emotional_tone']}")
        
    # 3. Test regenerate_script_line
    line_payload = {
        "lyric_text": "Whataya want from me",
        "current_prompt": data[0]["visual_prompt"],
        "user_feedback": "让他走在大雨滂沱的赛博朋克废墟街头中",
        "user_vision": "一个孤独的宇航员在荒凉的红色星球上漫步，寻找生命迹象，情感绝望"
    }
    
    print("\n[Step 2] 调用真实 Gemini 进行单行分镜大纲局部改写...")
    regen_response = client.post("/api/regenerate_script_line", json=line_payload)
    
    if regen_response.status_code != 200:
        print(f"❌ 失败: 状态码 {regen_response.status_code}, 错误信息: {regen_response.text}")
        sys.exit(1)
        
    regen_data = regen_response.json()
    print("✅ 单行改写成功！Gemini 返回数据如下:")
    print(f"    修改后提示词: {regen_data['visual_prompt']}")
    print(f"    修改后运动度: {regen_data['motion_preference']}")
    print(f"    修改后情感基调: {regen_data['emotional_tone']}")
    
    print("\n" + "=" * 60)
    print("  真实 Gemini 大纲策划与改写集成测试成功通过！")
    print("=" * 60)
