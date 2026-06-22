# HYPERFRAMES - AI MV/MAD 智能脚本规划与渲染工作室

HYPERFRAMES 是一款面向 MAD/AMV 视频创作者的智能剪辑与渲染工作站。它集成了音频节奏分析、AI 创意分镜策划、多模态语义搜索（画面特征+语音台词）、以及基于 Web 技术的 Headless 视频高精度渲染，帮助创作者快速将一首歌曲转化为极具情感故事张力的音乐视频。

---

## 1. 核心特性 (Key Features)

### 🎵 音乐节奏与歌词分析 (Rhythm & Lyric Analysis)
* **节奏特征提取**：利用 `librosa` 提取音频波形，精准分析歌曲的 BPM、鼓点位置（Beats）以及音量起始点（Onsets），为视频切片提供卡点依据。
* **音频与歌词精确剪切**：支持创作者手动输入时间段裁剪歌曲，系统将自动调用 FFmpeg 物理切割音频文件，并对 LRC/TXT 歌词时间轴执行高精度毫秒级对齐与偏置。

### ✍️ 创意脚本分镜策划 (Creative Script Planner)
* **高层级大纲策划**：在卡点匹配前，调用 Gemini 3.5 Flash 大模型。大模型将通读歌词并结合用户给出的“心情/创作视角提示”（如：宇航员在荒凉星球寻找生机），为每句歌词自动衍生出契合整体情感线、具象化的“画面视觉提示词”和“镜头运动感偏好”（Low/Medium/High）。
* **用户迭代精修**：支持创作者在前端直接修改大纲文案与运动节奏，并支持对单行分镜输入修改意见（如“让色调变暗”）进行大模型局部重新生成。

### 💬 图像与语音台词双轨检索 (Multimodal Blended Search)
* **视频画面索引 (Visual Indexing)**：FFmpeg 每 0.5s 提取一帧图像，通过 OpenAI CLIP 模型（`clip-vit-base-patch32`）转化为 512 维特征向量存入 SQLite；并计算相邻帧差得出运动感分数。
* **语音台词索引 (Voice Indexing - ASR)**：FFmpeg 从视频中提取轻量 MP3 临时音轨，利用 Gemini 3.5 Flash 转写出高精度的对白文本和时间轴；再次通过 CLIP 文本模型将台词语义做向量化存储。
* **语义双轨打分融合 (Score Blended)**：
  - 用户发起检索时，相似度得分由**画面视觉相似度**与**台词语义相似度**混合而成（$Score = S_{visual} \cdot MotionFactor + w \cdot S_{transcript}$）。
  - 支持直接搜出带有匹配台词的镜头（如输入“你在看什么”匹配到主角说这句话的画面），并在候选卡片上悬挂 `💬 台词: "..."` 气泡展示。

### 🎬 双播放器顺滑预览与高精度渲染 (Seamless Preview & Headless Render)
* **双播放器 Ping-Pong 预加载**：前端包含两个视频播放器交替显隐。当播放器播放当前卡点时，后台播放器会自动静默加载并预 Seek 下一个卡点的视频，彻底解决视频源切换时的卡顿和转圈。
* **音量与静音控制**：预览与渲染阶段均执行 100% 视频静音控制，防止原视频杂音污染 MV 背景音乐；支持全局音量统一联动。
* **HyperFrames 智能渲染**：利用 headless 浏览器渲染，自动检测不兼容的原片格式（如 MKV, MOV 等）并映射至 H.264 MP4 代理；合并背景音轨，输出高品质 1080p MV 视频。

---

## 2. 系统架构与数据模型 (Architecture & Data Model)

系统使用 SQLite 数据库管理素材元数据。

```
+-------------------------------------------------------+
|                       VIDEOS                          |
+-------------------------------------------------------+
|  id (PK) | original_path | proxy_path | duration | fps|
+-------------------+-----------------------------------+
                    | 1
                    |
                    | 1:N
                    +--------------------+
                    |                    |
+-------------------+---+        +-------+--------------+
|       KEYFRAMES       |        |     TRANSCRIPTS      |
+-----------------------+        +----------------------+
|  id (PK)              |        |  id (PK)             |
|  video_id (FK)        |        |  video_id (FK)       |
|  timestamp (REAL)     |        |  start_time (REAL)   |
|  frame_path (TEXT)    |        |  end_time (REAL)     |
|  embedding (BLOB)     |        |  text (TEXT)         |
|  motion_score (REAL)  |        |  embedding (BLOB)    |
+-----------------------+        +----------------------+
```

* **`videos`**：存储视频的基础属性与转码代理文件路径。
* **`keyframes`**：存储每 0.5s 图像帧的路径、512维 CLIP 图像嵌入向量，以及相邻帧平均绝对像素差（`motion_score`）。
* **`transcripts`**：存储 ASR 语音识别台词的时间轴、文字，以及利用 CLIP text encoder 生成的台词语义向量（用于台词语义匹配）。

---

## 3. 核心 API 路由 (Backend API Endpoints)

| 方法 | 路由 | 参数 | 描述 |
| :--- | :--- | :--- | :--- |
| **POST** | `/api/index_videos` | `directory` | 扫描目录并将所有视频生成代理、关键帧和向量索引 |
| **GET** | `/api/videos` | - | 获取视频索引库内已注册的所有视频元数据 |
| **POST** | `/api/upload_music` | `audio`, `lyric`, `lyric_text` | 上传并分析歌曲结构、节奏点和初始歌词切片 |
| **POST** | `/api/trim_music` | `audio_path`, `lyric_path`, `start_time`, `end_time` | 物理裁剪音频片段并同步平移重计算歌词轴 |
| **POST** | `/api/generate_script_plan` | `lyrics`, `user_vision` | 调用 Gemini 生成基于歌词和心情偏好的分镜分镜大纲 |
| **POST** | `/api/regenerate_script_line` | `lyric_text`, `current_prompt`, `user_feedback`, `user_vision` | 对大纲中的单行镜头进行局部改写 |
| **POST** | `/api/match` | `lyric_text`, `motion_preference`, `limit` | 检索符合提示词/台词的最优视频画面候选集（Top 5） |
| **POST** | `/api/render` | `slots`, `audio_path` | 将时间轴卡点数据保存并调用 HyperFrames 渲染高清 MP4 |

---

## 4. 环境准备与项目运行 (Setup & Guide)

### 4.1 前置依赖
* **Python 3.12+**
* **Node.js (LTS)**
* **FFmpeg / FFprobe**：用于视频代理压制、关键帧提取、音频截取和音轨提取。
  ```bash
  sudo apt update && sudo apt install -y ffmpeg
  ```

### 4.2 本地运行
1. **安装 Python 虚拟环境及依赖**：
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r backend/requirements.txt   # （或直接 pip install fastapi uvicorn pillow torch torchvision transformers python-dotenv python-multipart librosa soundfile）
   ```
2. **配置秘钥 (`.env`)**：
   在项目根目录下创建 `.env` 文件（已自动配置 `.gitignore` 保护该私有文件）：
   ```env
   GOOGLE_API_KEY=您的_GEMINI_API_KEY
   ```
3. **启动后端服务 (FastAPI)**：
   运行项目根目录下的启动命令：
   ```bash
   # 普通启动
   ./venv/bin/python backend/app.py
   
   # 开发热重载启动
   RELOAD=1 ./venv/bin/python backend/app.py
   ```
4. **前端浏览器访问**：
   后端服务启动后，在本地浏览器中直接访问 `http://localhost:8000` 即可开启可视化剪辑工作区。

---

## 5. 自动化测试套件 (Test Suite)

项目提供了两层自动化测试以保障代码健壮性：

### 5.1 单元与 Mock 模块测试 (Pytest)
在根目录下运行测试套件：
```bash
./run_tests.sh
```
测试范围包含：
* `test_analyzer.py`：测试音频 BPM 节奏特征提取。
* `test_trimmer.py`：测试 LRC 歌词精确偏置与音频剪切。
* `test_script_plan.py`：测试创意脚本大纲的生成与行改写流程。
* `test_voice_index.py`：测试语音台词索引落库与检索打分融合逻辑。

### 5.2 真实集成测试 (CLI Scripts)
可以直接使用 python 在终端运行涉及真实多模态/大模型推理的集成测试：
* **真实 CLIP 与视频索引测试**：
  ```bash
  python tests/test_index_and_embed.py
  ```
* **真实 Gemini 语音转写与台词检索测试**：
  ```bash
  python tests/test_real_voice_index.py
  ```
