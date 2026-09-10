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

同时，PDF 解析需要 MinerU API Key，建议不要选择本地解析，**请选择 MinerU 云解析**，并到 [MinerU](https://mineru.net/) 官网获取免费的 API Key。

所有密钥被加密储存至本地，他人无法获取。

### 提交论文
![](../images/0910-1.png)
PaperReader 是一款保留 LaTeX 公式、图片等结构的论文翻译器。其支持两种形式的提交：
1. **PDF 文件**：点击“新解析”直接上传 PDF 文件。PaperReader 的工作流为：PDF 文件 → MinerU 云解析 → 解析结果 → 翻译 → LaTeX 构建 → 输出 PDF。如果 LaTeX 构建失败，PaperReader 会将错误日志和 translated.tex 一同再次提交给 LLM 进行修复，直到构建成功。
2. **LaTeX 文件**：点击“Tex 项目”上传，可以上传整个压缩包（包含 .tex 文件、模板 .bib, .sty 等、以及所有图片），也可多文件逐个上传。PaperReader 会直接进行翻译和 LaTeX 构建。
>[!NOTE]
>由于 PDF 解析再重新构建 LaTeX 不可避免会出现一定结构偏差，上传论文的 Tex 源码会更为精准。**对于 arXiv 上的论文，我们推荐下载其 Tex source 压缩包进行上传**。

### 历史记录
左侧栏的“历史记录”中会显示用户提交的论文列表，点击即可查看解析结果和翻译结果。

可以点击☆收藏论文，收藏的论文会在“我的收藏”中显示。

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

### AI 对话
点击左侧边栏顶部三个按钮中靠左的一个，是 AI 对话功能。用户可以在对话框中输入问题，PaperReader 会根据用户上传的论文内容进行回答。

上方的 AI Literature Chat 是一个独立的对话窗口，用户可以在其中将多篇上传的论文对比，进行问答。