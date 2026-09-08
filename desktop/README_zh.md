PaperReader v2.1 Windows 可移植版
============================

使用方法
--------

1. 解压整个 ZIP，不能只把 PaperReader.exe 单独复制出来。
2. 双击 PaperReader.exe。首次启动会先打开配置向导，请填写大模型 API Key、Base URL、模型，以及可选的 MinerU 设置。
3. 注册或登录后，密钥会转存到当前账号的本机加密数据库；之后可在「个人中心 → AI 服务」修改。
4. 用户上传的论文、翻译结果和聊天记录保存在 %LOCALAPPDATA%\PaperReader\data。

运行要求
--------

- Windows 10/11 64 位，并需要 Microsoft WebView2 Runtime（大多数当前 Windows 安装已包含）。
- 接收者不需要安装 Python 或 Node.js。
- 要生成保持 LaTeX 排版的中文 PDF，电脑仍需安装 TeX Live，并确保 latexmk/xelatex 可从 PATH 访问。
- 不要分享 %LOCALAPPDATA%\PaperReader 下的隐藏配置或 data 用户数据。

分享方法
--------

直接分享 PaperReader-v2.1.0-Windows-x64.zip。每位使用者应在首次启动向导中填写自己的 API 密钥。

开发者重新打包
--------------

在仓库根目录运行 `powershell -ExecutionPolicy Bypass -File .\desktop\build_portable.ps1`。
脚本默认从 PATH 查找 npm 和 Python；也可通过 `-NpmPath`、`-PythonPath` 指定路径。

版本与升级
----------

发布标签为 v2.1，程序/前端版本为 2.1.0。下载包同时提供 SHA-256 校验文件。
EXE 未做 Authenticode 签名。v2.0 的 config.env 和 data 会在首次启动时复制到新的本机目录，原文件保留作为恢复副本。源码版的详细升级说明见 docs/UPGRADING.md。

重新构建前安装 Node.js 20 和 Python 3.11，然后运行：
python -m pip install -r desktop/requirements-build.txt
powershell -ExecutionPolicy Bypass -File .\desktop\build_portable.ps1

解压包中的 create_shortcut.ps1 可用于创建直接指向 PaperReader.exe 的桌面快捷方式。
