# AI 智能 MV 脚本与 HyperFrames 渲染系统设计方案

本项目旨在开发一个面向视频剪辑师的 **AI 辅助 MV 剪辑与渲染工作流系统**。该系统将对本地素材进行多维语义索引，自动分析音乐节奏与歌词意境，通过 Web UI 提供人机交互匹配，并最终使用 **HyperFrames** 进行非线性视频自动渲染。

---

## 用户审查要求

> [!IMPORTANT]
> **本地模型运行的硬件要求：**
> 步骤 1 中，为了保护您的素材隐私和免去云端费用，系统默认采用本地开源模型（CLIP 和 Whisper）。
> 运行此系统需要您的电脑具备：
> - 良好的 CPU（推荐 8 核以上）
> - 最好有 NVIDIA 独立显卡（如 RTX 3060 及以上，支持 CUDA 加速），否则在 CPU 上提取特征速度会较慢。

> [!WARNING]
> **HyperFrames 渲染环境依赖：**
> 为了能够顺利渲染视频，系统后台需要预装以下本地环境：
> - **Node.js (v22+)**：用于运行 `npx hyperframes` 命令。
> - **FFmpeg**：用于将无头浏览器捕获的图片拼装成 MP4。

---

## 方案决策与确认

> [!NOTE]
> **1. 本地视频预览格式处理：已确认**
> 系统在索引视频时，将自动通过 FFmpeg 提取低码率的 360p MP4 代理文件，专门用于 Web UI 预览。最终 HyperFrames 渲染出片时会使用原始的高清视频。
> 
> **2. 歌词格式输入：已确认**
> 系统主要支持 `.lrc` 歌词文件，从而精确解析带时间戳的歌词。若无 `.lrc`，则支持上传纯文本歌词并按时间均分或配合简单的 ASR（优先使用本地 `.lrc` 解析）。

---

## 拟议变更

我们将在工作区 [editor](file:///wsl$/Ubuntu/home/fenxy/editor) 中创建以下全新组件。

### 1. 后端服务 (Python / FastAPI)
负责视频特征提取、音乐卡点分析、智能推荐和 HyperFrames 工程组装。

#### [NEW] [app.py](file:///wsl$/Ubuntu/home/fenxy/editor/backend/app.py)
* 整个系统的服务入口，暴露接口给 Web UI。
* 接口包括：`/api/index_videos`（视频索引）、`/api/analyze_music`（音乐节奏歌词分析）、`/api/match`（智能配对推荐）、`/api/render`（调用 HyperFrames 渲染）。

#### [NEW] [indexer.py](file:///wsl$/Ubuntu/home/fenxy/editor/backend/indexer.py)
* **视频扫描与特征提取器：**
  - 使用 `FFmpeg` 对视频进行场景切片检测（Scene Detection）并提取关键帧。
  - 使用本地 HuggingFace **`openai/clip-vit-base-patch32`** 模型为关键帧生成视觉语义向量。
  - 生成 360p 低清预览代理视频。
  - 将视频信息与向量存入本地的轻量级数据库（`SQLite` + 本地向量相似度计算）。

#### [NEW] [analyzer.py](file:///wsl$/Ubuntu/home/fenxy/editor/backend/analyzer.py)
* **音乐与歌词解析器：**
  - 使用 **`librosa`** 分析歌曲的 BPM 与瞬态鼓点（Onsets），确定卡点时间轴。
  - 解析歌词（LRC 文件），将歌词文本输入到本地 LLM 或通过语义模型（Sentence-Transformers）转换为文本向量。

#### [NEW] [matcher.py](file:///wsl$/Ubuntu/home/fenxy/editor/backend/matcher.py)
* **匹配推荐引擎：**
  - 计算歌词向量与视频帧向量的余弦相似度（Cosine Similarity）。
  - 根据音乐的节奏快慢（卡点密度）和视频的运动强度（Motion Intensity）进行交叉过滤。
  - 为每个时间插槽返回 Top 5 候选片段。

---

### 2. 交互前端 Web UI (HTML / CSS / JS)
提供一个极富现代感的、暗色调科技风（Neon Dark Mode）的交互面板，供剪辑师挑选卡点镜头。

#### [NEW] [index.html](file:///wsl$/Ubuntu/home/fenxy/editor/frontend/index.html)
* 主界面结构。包含：
  - 顶部：音乐上传与歌词加载区。
  - 中部：可视化音频波形图（Waveform）与卡点时间线。
  - 左侧：逐行歌词与对应匹配槽列表。
  - 右侧：推荐素材候选池（以网格卡片展示预览图，标明匹配度得分）。

#### [NEW] [style.css](file:///wsl$/Ubuntu/home/fenxy/editor/frontend/style.css)
* 极具美感的 Vanilla CSS 样式表。采用深色磨砂玻璃（Glassmorphism）质感，霓虹蓝（Cyan）与紫罗兰（Violet）微光点缀。

#### [NEW] [app.js](file:///wsl$/Ubuntu/home/fenxy/editor/frontend/app.js)
* 前端核心交互逻辑。负责拖拽替换素材、播放试听、标记锁定片段、发起一键渲染请求。

---

### 3. HyperFrames 模板与渲染器

#### [NEW] [index.html](file:///wsl$/Ubuntu/home/fenxy/editor/hyperframes_template/index.html)
* 用于最终渲染的 HyperFrames HTML 模板。
* 内部包含预置的 GSAP 动画代码，可以接收后端输出的 JSON 数据，动态生成排布好 `<video>` 的 DOM 结构。

---

## 验证计划

### 自动化验证与依赖检查
- 运行 `python backend/app.py` 验证 API 启动状态。
- 使用 Mock 数据测试 `/api/match` 接口的推荐准确度。

### 手动验证流
1. **测试视频索引：** 拖入一个包含 5 个短视频的文件夹，验证是否在本地成功提取特征并生成 360p 预览文件。
2. **测试音乐分析：** 上传一首 MP3，验证波形图是否准确标出鼓点（BPM）。
3. **测试推荐交互：** 在 Web UI 中挑选素材并锁定，验证时间轴是否同步更新。
4. **测试 HyperFrames 最终出片：** 点击“渲染”，验证后台是否正确调用 `npx hyperframes render`，最终输出 `output.mp4` 且音画同步、卡点精准。
