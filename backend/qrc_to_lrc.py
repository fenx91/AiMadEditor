"""
QRC → LRC 转换器
QQ 音乐 .qrc 格式：XOR 解密（32字节固定密钥循环）→ zlib 解压 → XML 解析 → LRC
"""
import sys
import zlib
import re
import xml.etree.ElementTree as ET

# QQ 音乐 QRC 固定密钥（32字节，循环使用）
QRC_KEY = bytes([
    0x77, 0x48, 0x32, 0x73, 0xDE, 0x49, 0x71, 0x2E,
    0x56, 0xF5, 0xB4, 0x3B, 0x67, 0x6E, 0x6F, 0x60,
    0xDE, 0x6E, 0xBE, 0x4A, 0x20, 0x8B, 0xAB, 0x47,
    0x64, 0x16, 0x98, 0x03, 0x3D, 0x28, 0xCD, 0xBA,
])


def xor_decrypt(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def ms_to_lrc_time(ms: int) -> str:
    """毫秒 → [mm:ss.xx]"""
    total_sec = ms // 1000
    centisec  = (ms % 1000) // 10
    minutes   = total_sec // 60
    seconds   = total_sec % 60
    return f"[{minutes:02d}:{seconds:02d}.{centisec:02d}]"


def qrc_to_lrc(qrc_path: str) -> str:
    with open(qrc_path, "rb") as f:
        raw = f.read()

    # 1. XOR 解密
    decrypted = xor_decrypt(raw, QRC_KEY)

    # 2. zlib 解压（尝试有/无 header 两种情况）
    xml_text = None
    for offset in (0, 4, 8):
        try:
            xml_text = zlib.decompress(decrypted[offset:]).decode("utf-8", errors="replace")
            break
        except Exception:
            continue

    if xml_text is None:
        raise ValueError("解密/解压失败，可能不是标准 QRC 格式")

    print("=== 解密后 XML 片段 ===")
    print(xml_text[:500])
    print("...")

    # 3. 解析 XML，提取 LyricContent
    root = ET.fromstring(xml_text)
    lyric_content = None
    for elem in root.iter():
        content = elem.get("LyricContent") or elem.get("lyriccontent")
        if content:
            lyric_content = content
            break

    if lyric_content is None:
        # 备用：直接用正则找 LyricContent=
        m = re.search(r'LyricContent="([^"]+)"', xml_text, re.IGNORECASE)
        if m:
            lyric_content = m.group(1)

    if lyric_content is None:
        raise ValueError("XML 中未找到 LyricContent 字段")

    # 4. 解析 QRC 歌词格式：[start_ms,duration_ms]文字
    # 每行格式示例：[1600,1730]I know that you've been hurt
    lrc_lines = []
    for line in lyric_content.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"\[(\d+),\d+\](.*)", line)
        if m:
            start_ms = int(m.group(1))
            text     = m.group(2).strip()
            lrc_lines.append((start_ms, text))

    if not lrc_lines:
        raise ValueError("未能解析到任何歌词行")

    # 5. 输出 LRC
    lrc_lines.sort(key=lambda x: x[0])
    lrc_out = []
    for ms, text in lrc_lines:
        lrc_out.append(f"{ms_to_lrc_time(ms)}{text}")

    return "\n".join(lrc_out)


if __name__ == "__main__":
    import os
    qrc_file = sys.argv[1] if len(sys.argv) > 1 else (
        "/home/fenxy/editor/tests/data/music/"
        "Adam Lambert - Whataya Want from Me - 227 - For Your Entertainment (Deluxe Version)_qm.qrc"
    )
    lrc_file = os.path.splitext(qrc_file)[0] + ".lrc"

    try:
        lrc_content = qrc_to_lrc(qrc_file)
        with open(lrc_file, "w", encoding="utf-8") as f:
            f.write(lrc_content)
        print(f"\n✅ 转换成功 → {lrc_file}")
        print("\n=== 前 10 行 ===")
        for line in lrc_content.splitlines()[:10]:
            print(line)
    except Exception as e:
        print(f"❌ 转换失败: {e}")
