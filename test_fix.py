"""尝试更多解密方案"""
import zlib, struct

path = ("/home/fenxy/editor/tests/data/music/"
        "Adam Lambert - Whataya Want from Me - 227 - For Your Entertainment (Deluxe Version)_qm.qrc")
with open(path, "rb") as f:
    raw = f.read()

print(f"前64字节:\n{raw[:64].hex()}\n")

# 方案A: 酷狗 KRC 格式 - 固定头 + XOR key "5F 4D 40 72 61 5C 6F 72"
krc_magic = b'\x98krc\r\n'
krc_key = bytes([0x40, 0x47, 0x61, 0x77, 0x5E, 0x32, 0x74, 0x47,
                 0x51, 0x33, 0x31, 0x74, 0x40, 0x61, 0x35, 0x77])
print(f"KRC 魔数匹配: {raw[:4] == b'\\x98krc'}")

# 方案B: 使用完整256字节密钥表（QQ音乐旧版本）
# key 由字符串 "@#$()*+-./:;<=>?@ABCDE" 派生
def make_key_256():
    s = b"@#$()*+-./:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    key = bytearray(256)
    for i in range(256):
        key[i] = s[i % len(s)]
    return bytes(key)

key256 = make_key_256()
dec = bytes(b ^ key256[i % 256] for i, b in enumerate(raw))
for off in range(0, 16):
    try:
        r = zlib.decompress(dec[off:])
        print(f"✅ 方案B offset={off}: {len(r)} bytes")
        print(r[:200].decode("utf-8", errors="replace"))
    except:
        pass

# 方案C: 反转字节序列后 zlib
for off in range(0, 8):
    try:
        r = zlib.decompress(raw[off:][::-1])
        print(f"✅ 反转 offset={off}: {len(r)} bytes")
    except:
        pass

# 方案D: 检查是否是 zip 格式
print(f"\nzip 签名检测: {raw[:4].hex()} (zip 应为 504b0304)")

# 方案E: 打印4字节小端整数头
vals = struct.unpack_from('<4I', raw[:16])
print(f"前16字节作为小端int32: {[hex(v) for v in vals]}")

# 方案F: 检查已知 QRC 新版密钥（来自开源项目 QQMusicApi）
key_new = bytes([
    0xB3, 0x6C, 0x89, 0xE5, 0xBF, 0xF3, 0xDD, 0xE2,
    0x34, 0x12, 0xD6, 0xBD, 0xA3, 0x29, 0xBD, 0x6E,
    0x4A, 0xC8, 0x17, 0x0E, 0xD5, 0x5D, 0x8F, 0x30,
    0xF2, 0x1E, 0xDE, 0x93, 0xB1, 0x54, 0x6E, 0x83,
])
dec2 = bytes(b ^ key_new[i % len(key_new)] for i, b in enumerate(raw))
for off in (0, 4, 8):
    try:
        r = zlib.decompress(dec2[off:])
        print(f"✅ 新密钥 offset={off}: {len(r)} bytes")
        print(r[:300].decode("utf-8", errors="replace"))
        break
    except:
        pass
