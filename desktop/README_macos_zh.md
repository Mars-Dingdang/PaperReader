# PaperReader v2.1.8 macOS（Apple Silicon）

## 安装与首次启动

1. 下载 `PaperReader-v2.1.8-macOS-arm64.dmg` 及对应 `.sha256`，校验后打开 DMG。
2. 将 PaperReader 拖入“应用程序”。本版本使用临时签名但未经过 Apple 公证；如果首次打开被拦截，请在 Finder 中按住 Control 点击应用并选择“打开”。
3. 首次启动会在登录前显示配置向导。填写大模型 API Key、Base URL、模型，以及可选的 MinerU 参数。
4. 注册或登录后，密钥会转存到当前本地账号的加密数据库。可随时在「个人中心 → AI 服务」修改。

应用数据、隐藏配置和日志位于 `~/Library/Application Support/PaperReader`。不要分享该目录或包含私人论文的数据。

## v2.1.8 LaTeX 兼容性与可恢复翻译

翻译或 LaTeX 编译失败时，可在进度面板点击“从此处重试”。已完成的结构化解析与译块由 checkpoint 复用；自动 LaTeX 修复最多两轮，并仅允许修改编译器定位的行窗。

- LaTeX 工程会优先遵循 arXiv `00README.json` → `process.compiler`，并支持 `% !TeX program = ...`。支持 pdflatex、xelatex、lualatex 和 latex；没有受支持声明时继续默认使用 XeLaTeX。

- PDF 中的 HTTP(S) 外链由系统默认浏览器打开，PaperReader 保持当前论文和阅读位置；PDF 内部章节/页码链接仍在阅读器中跳转。
- 可以拖选、复制 PDF 文字并继续使用双语对应定位；触控板双指捏合缩放更灵敏，目录会优先使用书签并在缺少书签时从文本生成。
- 支持直接导入 `.zip`、`.tar`、`.tar.gz`、`.tgz` LaTeX 工程包。解压后请检查文件并确认主 `.tex`，应用不会自动开始翻译。
- arXiv 或论文提供 LaTeX 源码时，建议优先上传 LaTeX，以获得更好的结构与翻译质量。
- 新账号默认关闭视觉检查，可在侧栏或个人中心主动开启；升级不会覆盖现有账号的选择。

## 运行要求

- Apple Silicon Mac（arm64），macOS 13 或更高版本。
- APP 已包含 Python 后端、WKWebView 窗口和前端资源，不需要另装 Python 或 Node.js。
- 生成中文译文 PDF 仍需安装 MacTeX/TeX Live；应用会自动检测 `/Library/TeX/texbin/latexmk`，并将同目录加入编译子进程的 PATH，使 `latexmk` 能正常调用 XeLaTeX 等引擎。
- LLM、MinerU 和在线文献功能需要网络及用户自己的服务密钥。

## 开发者构建

在 Apple Silicon Mac、Python 3.11 与 Node.js 20 环境执行：

```sh
python -m pip install -r desktop/requirements-build.txt
./desktop/build_macos.sh
```

脚本会构建前端、生成 `.app`、执行 ad-hoc 签名并输出 DMG 与 SHA-256 文件。
