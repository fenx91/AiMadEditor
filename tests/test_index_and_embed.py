"""
集成测试：真实 CLIP 模型 + 对 /home/fenxy/editor/in 里的视频做索引和 embedding 验证。
在项目根目录运行：  python tests/test_index_and_embed.py

注意：此文件不通过 pytest 运行（模块级代码加了 if __name__ == '__main__' 保护），
     直接 python 执行时才会运行真实 CLIP 推理。
"""
import os
import sys
import glob
import numpy as np

# 把项目根和 backend 加入路径
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))


def hr(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


if __name__ == '__main__':
    from backend.indexer import FeatureExtractor, init_db, index_video_file

    VIDEO_DIR = "/home/fenxy/editor/in"
    TEST_DB   = "data/test_index.db"

    # ── Step 1: 加载 CLIP 模型 ──────────────────────────────────────
    hr("Step 1: 加载 CLIP FeatureExtractor")
    extractor = FeatureExtractor()
    print(f"✅ 模型加载成功，设备: {extractor.device}")

    # ── Step 2: 文本 Embedding ──────────────────────────────────────
    hr("Step 2: 文本 Embedding 测试")
    texts = ["两人在阳光下散步", "夜晚的城市霓虹灯", "激烈的战斗场面"]
    for t in texts:
        emb = extractor.get_text_embedding(t)
        norm = float(np.linalg.norm(emb))
        print(f"  文本: 「{t}」")
        print(f"    shape={emb.shape}  norm={norm:.6f}  (应≈1.0)")
        assert abs(norm - 1.0) < 1e-4, f"Embedding 未归一化！norm={norm}"
    print("✅ 文本 Embedding 测试通过")

    # ── Step 3: 图像 Embedding（取已有帧，或临时提取一帧）─────────────
    hr("Step 3: 图像 Embedding 测试")
    import subprocess, shutil
    FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
    tmp_frame = "/tmp/test_frame.jpg"

    videos = sorted(glob.glob(os.path.join(VIDEO_DIR, "*.mkv")) +
                    glob.glob(os.path.join(VIDEO_DIR, "*.mp4")))
    assert videos, f"❌ {VIDEO_DIR} 中没有视频文件"

    video = videos[0]
    print(f"  使用视频: {os.path.basename(video)}")
    subprocess.run([FFMPEG, "-y", "-i", video, "-vf", "fps=2",
                    "-frames:v", "1", "-q:v", "2", tmp_frame],
                   capture_output=True)
    assert os.path.exists(tmp_frame), "❌ 无法提取测试帧"

    emb = extractor.get_image_embedding(tmp_frame)
    norm = float(np.linalg.norm(emb))
    print(f"  图像帧 shape={emb.shape}  norm={norm:.6f}  (应≈1.0)")
    assert abs(norm - 1.0) < 1e-4, f"图像 Embedding 未归一化！norm={norm}"
    print("✅ 图像 Embedding 测试通过")

    # ── Step 4: 文本和图像向量余弦相似度 ────────────────────────────
    hr("Step 4: 相似度合理性验证")
    text_emb = extractor.get_text_embedding("anime scene")
    sim = float(np.dot(text_emb, emb))  # 两个都已归一化，dot = cosine sim
    print(f"  'anime scene' 与帧的余弦相似度: {sim:.4f}")
    assert -1.0 <= sim <= 1.0, "❌ 相似度超出 [-1, 1] 范围"
    print(f"✅ 相似度在合理范围内")

    # ── Step 5: 真实视频 index（仅索引前 1 条）──────────────────────
    hr("Step 5: 完整 index_video_file 测试")
    init_db(TEST_DB)
    print(f"  索引文件: {os.path.basename(video)}")
    print(f"  数据库: {TEST_DB}")
    vid_id = index_video_file(video, extractor, db_path=TEST_DB)

    assert vid_id is not None, "❌ index_video_file 返回 None，索引失败"

    import sqlite3
    conn = sqlite3.connect(TEST_DB)
    kf_count = conn.execute("SELECT COUNT(*) FROM keyframes WHERE video_id=?", (vid_id,)).fetchone()[0]
    conn.close()

    print(f"  video_id={vid_id}  关键帧数量={kf_count}")
    assert kf_count > 0, f"❌ 关键帧数量为 0！"
    print(f"✅ 索引成功，{kf_count} 帧已存入数据库")

    # ── Step 6: 缓存命中的 Skip 测试 ────────────────────────────────
    hr("Step 6: 缓存命中的 Skip 测试")
    import time
    start_time = time.time()
    # Re-indexing the same file should hit the cache and be near-instantaneous
    second_vid_id = index_video_file(video, extractor, db_path=TEST_DB)
    elapsed = time.time() - start_time
    assert second_vid_id == vid_id
    print(f"  第二次索引耗时: {elapsed:.4f} 秒")
    assert elapsed < 0.5, f"❌ 缓存未生效！耗时 {elapsed:.4f}s"
    print("✅ 缓存命中测试通过 (Skip 成功)")

    # ── 清理 ────────────────────────────────────────────────────────
    hr("全部测试通过 ✅")
    print(f"  测试数据库保留于: {TEST_DB}（可手动删除）")
