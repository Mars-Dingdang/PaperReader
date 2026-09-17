# PaperReader 使用说明

## 安装

### 直接使用软件
PaperReader 支持 Windows 和 MacOS 平台，可以直接下载安装包，见相应的 Release 页面（请下载最新版本的安装包）。安装包包含了所有依赖，无需额外安装。

需要注意的是，**Windows 版本的安装包如果直接解压后 PaperReader.exe 打开失败**，请重新解压前右键 .zip 文件、选择“属性”、**点击“解除锁定”**，然后再解压。**请在原始目录下打开 PaperReader.exe**，因为其运行依赖同一目录下的 _internal 文件夹。

### 从源代码构建
要从源代码构建 PaperReader，需要先克隆仓库，然后按照 docs/DEVELOPMENT.md 中的说明进行构建。

首先：安装必要的环境依赖
```bash
pip install -r desktop/requirements-build.txt
```

对于 Windows 用户，使用脚本
```bash
powershell -ExecutionPolicy Bypass -File ./desktop/build_portable.ps1
./dist/PaperReader/PaperReader.exe
```

对于 MacOS (Mac Silicon Only) 用户，使用脚本
```bash
chmod +x desktop/build_macos.sh
./desktop/build_macos.sh
open ./dist/PaperReader.app
```

## 使用说明
### 用户注册
新用户需要输入 API Key 和 url，以便使用自己的大模型密钥调用翻译、LaTeX 构建等服务。推荐使用价格相对较低的模型，如 DeepSeek-V4-Flash-0731。

PDF 解析默认使用 **MinerU 云解析**，需要单独配置 MinerU API Key，可到 [MinerU](https://mineru.net/) 官网获取免费的 API Key。

大模型与 MinerU 密钥独立加密保存。更新一个密钥时，另一个留空即可保持原值；只有勾选对应的删除选项才会清除。缺少 MinerU Key 时仍可保存大模型设置、处理 TeX 项目和问答，上传 PDF 前需要补齐 MinerU Key，或明确切换到本地解析。

### 提交论文
![](../images/0910-1.png)
PaperReader 是一款保留 LaTeX 公式、图片等结构的论文翻译器。其支持两种形式的提交：
1. **PDF 文件**：点击“新解析”直接上传 PDF 文件。PaperReader 的工作流为：PDF 文件 → MinerU 云解析 → 解析结果 → 翻译 → LaTeX 构建 → 输出 PDF。如果 LaTeX 构建失败，PaperReader 会将错误日志和 translated.tex 提交给 LLM，最多进行五轮自动修复尝试，每次应用补丁后重新编译。
2. **LaTeX 文件**：点击“Tex 项目”上传，可以上传整个压缩包（包含 .tex 文件、模板 .bib, .sty 等、以及所有图片），也可多文件逐个上传。PaperReader 会直接进行翻译和 LaTeX 构建。
>[!NOTE]
>由于 PDF 解析再重新构建 LaTeX 不可避免会出现一定结构偏差，上传论文的 Tex 源码会更为精准。**对于 arXiv 上的论文，我们推荐下载其 Tex source 压缩包进行上传**。

### LaTeX 自动修复

自动修复以编译通过和保留论文内容为目标。日志没有行号时仍会结合源码诊断；有行号时优先查看附近源码，并在后续尝试中扩大上下文。模型可以修复导言区、宏定义、宏包声明及完整的公式或表格环境。

每轮诊断和上一轮失败原因都会传给补丁生成步骤。响应格式或原文匹配有误时，会反馈原因并继续尝试。结构预检提供定位建议，最终由实际编译结果判断是否成功。较复杂的修复会增加模型调用次数和等待时间。

进度面板显示诊断、修复记录与最终失败原因。每次修改前会保存 `<文件名>.before-repair-<轮次>.tex`，位于该文档的产物目录；重复重试不会覆盖已有备份。五轮后仍失败时，可以从失败步骤重试，或在产物文件中编辑 `translated.tex` 后重新编译。

### 历史记录
左侧栏的“历史记录”中会显示用户提交的论文列表，点击即可查看解析结果和翻译结果。

列表顶部有“全文搜索文献库”搜索框：输入关键词会在所有已解析论文的原文与译文中查找，点击命中结果会直接打开对应论文并高亮所在位置。

可以点击☆收藏论文，收藏的论文会在“我的收藏”中显示。右键论文可“更改文档名”、“导出 BibTeX”（有 LaTeX 工程时导出工程自带的 .bib，否则根据论文元数据自动生成）或删除。

### 产物文件
左侧栏下滑可以看到“产物文件”，包含了原始文件，解析文件，翻译结果 LaTeX 和产物 PDF 等。其中的 translated.tex 点击“铅笔”按钮可以手动编辑后重新编译，也可以选择在本地 VSCode 中打开。

文件储存的位置为：
- Windows：
```text
 C:\Users\<name>\AppData\Local\PaperReader\data\outputs\<c312aa80-ff07-4122-ab89-17fbc22c0e5c>
```
- MacOS:
```text
/Users/<name>/Library/Application Support/PaperReader/data/outputs/<c312aa80-ff07-4122-ab89-17fbc22c0e5c>
```
其路径均可以从日志中找到。

### 阅读器功能
- **文档内搜索**：在 PDF 区域按 Ctrl（macOS 为 Cmd）+F 打开搜索栏，Enter / Shift+Enter 在命中之间跳转，Esc 关闭。
- **批注与笔记**：选中一段文字后右键（macOS 也可按住 Control 点击），打开菜单后文字保持选中，可选择四种颜色添加高亮，并可在输入框中附一句备注（按 Enter 保存）。批注会按账号保存，重新打开论文自动恢复；点击工具栏的“批注笔记”按钮可直接查看引用文字和备注，点击已有高亮或右键“查看批注”也可打开对应笔记。面板提供“定位原句”“删除批注”和“导出阅读笔记”，导出的 Markdown 包含原文、译文与备注。
- **阅读位置记忆**：关闭论文后重新打开，会自动回到上次读到的位置。
- **双栏联动滚动**：工具栏的“链接”图标默认开启，滚动一侧时另一侧同步滚动；再次点击可关闭。
- **图表导航**：工具栏的“图表”按钮打开当前 PDF 左侧的竖向半透明缩略图浮层，列表可独立滚动，点击卡片定位图注或表注。LaTeX 项目只列出主文件及其引用文件中实际使用的 Figure/Table，按源码顺序保留编号，包括同一个浮动环境中的多个表格。预览来自编译后的 PDF，支持矢量插图与 LaTeX 表格；原文、译文分别定位各自的页码。
- **对照高亮**：选中一段文字右键“跳转到对应内容并高亮”，对面译文（或原文）中与所选语句对应的部分会在文字层加载后高亮并居中显示。跨页段落优先匹配所选片段；没有可匹配文字时显示提示。

### AI 对话
点击左侧边栏顶部三个按钮中靠左的一个，是 AI 对话功能。用户可以在对话框中输入问题，PaperReader 会根据用户上传的论文内容进行回答。回答以流式方式逐字输出，其中的 [P1]、[P2] 等引用标记可以点击，会跳转到论文中被引用的位置。

也可以在 PDF 中直接选中一段看不懂的文字，右键选择“问 AI”，回答会自动结合这段文字所在的段落及其前后文。

上方的 AI Literature Chat 是一个独立的对话窗口，用户可以在其中将多篇上传的论文对比，进行问答。
