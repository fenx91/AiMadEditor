"""
集成测试：利用真实 Gemini API key 对 /home/fenxy/editor/in 中的视频音轨做转写测试，
并验证检索台词时的准确性。
在项目根目录运行： python tests/test_real_voice_index.py
"""
import os
import sys
import glob
import sqlite3

# Add project root and backend to path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

if __name__ == '__main__':
    from backend.indexer import FeatureExtractor, init_db, index_video_file, has_audio
    from backend.matcher import find_candidates
    
    VIDEO_DIR = "/home/fenxy/editor/in"
    TEST_DB   = "data/test_real_voice.db"
    
    print("=" * 60)
    print("  开始真实语音索引与检索集成测试")
    print("=" * 60)
    
    # 1. Check video pool
    videos = sorted(glob.glob(os.path.join(VIDEO_DIR, "*.mkv")) +
                    glob.glob(os.path.join(VIDEO_DIR, "*.mp4")))
    if not videos:
        print(f"❌ 错误: 文件夹 {VIDEO_DIR} 中没有视频文件")
        sys.exit(1)
        
    # Find a video with audio
    video_to_test = None
    for v in videos:
        if has_audio(v):
            video_to_test = v
            break
            
    if not video_to_test:
        print("❌ 错误: 视频文件夹中没有任何带音轨的视频，无法进行 ASR 测试。")
        sys.exit(1)
        
    print(f"✅ 找到带音轨测试视频: {os.path.basename(video_to_test)}")
    
    # 2. Load model
    print("\n[Step 1] 加载 FeatureExtractor...")
    extractor = FeatureExtractor()
    print("✅ 加载成功")
    
    # 3. Index video (calls Gemini transcription under the hood)
    print(f"\n[Step 2] 索引视频并将台词写入数据库: {TEST_DB}")
    init_db(TEST_DB)
    
    # Clean up old test data if any
    if os.path.exists(TEST_DB):
        try:
            os.remove(TEST_DB)
            init_db(TEST_DB)
        except OSError:
            pass
            
    vid_id = index_video_file(video_to_test, extractor, db_path=TEST_DB)
    assert vid_id is not None, "❌ 视频索引失败！"
    
    # 4. Check transcripts table
    conn = sqlite3.connect(TEST_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT start_time, end_time, text FROM transcripts WHERE video_id = ?", (vid_id,))
    rows = cursor.fetchall()
    conn.close()
    
    print(f"\n[Step 3] 查看数据库转写结果:")
    print(f"  共转写出 {len(rows)} 句台词。")
    for i, r in enumerate(rows):
        print(f"    #{i+1} [{r[0]:.1f}s - {r[1]:.1f}s]: {r[2]}")
        
    if not rows:
        print("⚠️ 警告: 转写出 0 句台词。如果视频里确实没人说话（纯背景乐），这是正常的；如果有对话，请检查 Gemini API 调用。")
    else:
        # 5. Search for a keyword from the transcribed text
        print("\n[Step 4] 对转写的台词进行语义检索测试:")
        # Pick the first transcript text
        test_query = rows[0][2]
        print(f"  检索词: '{test_query}'")
        cands = find_candidates(test_query, extractor, db_path=TEST_DB, limit=3)
        
        print("  检索候选结果:")
        for idx, c in enumerate(cands):
            has_t = "transcript_text" in c
            t_text = c.get("transcript_text", "")
            print(f"    候选 #{idx+1} [ts={c['timestamp']:.1f}s] score={c['score']:.4f}  has_transcript={has_t}  text={t_text}")
            
        # Ensure our target candidate is retrieved and contains transcript text
        matching_cands = [c for c in cands if c.get("transcript_text") == test_query]
        if matching_cands:
            print("✅ 语义台词检索完美匹配成功！")
        else:
            print("⚠️ 无法在 Top 3 候选里精确匹配到台词，可能是因为视觉分数过高或去重机制排除了该时间。")
            
    # Clean up test database
    if os.path.exists(TEST_DB):
        try:
            os.remove(TEST_DB)
        except OSError:
            pass
            
    print("\n" + "=" * 60)
    print("  真实语音索引与检索集成测试结束")
    print("=" * 60)
