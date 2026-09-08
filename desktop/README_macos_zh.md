# PaperReader v2.1 macOS（Apple Silicon）

## 安装与首次启动

1. 下载 `PaperReader-v2.1.0-macOS-arm64.dmg` 及对应 `.sha256`，校验后打开 DMG。
2. 将 PaperReader 拖入“应用程序”。本版本使用临时签名但未经过 Apple 公证；如果首次打开被拦截，请在 Finder 中按住 Control 点击应用并选择“打开”。
3. 首次启动会在登录前显示配置向导。填写大模型 API Key、Base URL、模型，以及可选的 MinerU 参数。
4. 注册或登录后，密钥会转存到当前本地账号的加密数据库。可随时在「个人中心 → AI 服务」修改。

应用数据、隐藏配置和日志位于 `~/Library/Application Support/PaperReader`。不要分享该目录或包含私人论文的数据。

## 运行要求

- Apple Silicon Mac（arm64），macOS 13 或更高版本。
- APP 已包含 Python 后端、WKWebView 窗口和前端资源，不需要另装 Python 或 Node.js。
- 生成中文译文 PDF 仍需安装 MacTeX/TeX Live；应用会自动检测 `/Library/TeX/texbin/latexmk`。
- LLM、MinerU 和在线文献功能需要网络及用户自己的服务密钥。

## 开发者构建

在 Apple Silicon Mac、Python 3.11 与 Node.js 20 环境执行：

```sh
python -m pip install -r desktop/requirements-build.txt
./desktop/build_macos.sh
```

脚本会构建前端、生成 `.app`、执行 ad-hoc 签名并输出 DMG 与 SHA-256 文件。
