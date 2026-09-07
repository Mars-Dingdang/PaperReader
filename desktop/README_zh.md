PaperReader v2.0 Windows 可移植版
============================

使用方法
--------

1. 解压整个 ZIP，不能只把 PaperReader.exe 单独复制出来。
2. 用记事本打开 config.env，填写你自己的 OPENAI_API_KEY、OPENAI_BASE_URL、OPENAI_MODEL。
3. 如使用 MinerU 云端版式解析，还需填写 MINERU_API_KEY，并把 PDF_PARSER 改为 mineru。
4. 双击 PaperReader.exe。程序会以独立的 Edge 应用窗口启动。
5. 用户上传的论文、翻译结果和聊天记录保存在解压目录下的 data 文件夹。

运行要求
--------

- Windows 10/11 64 位，建议安装 Microsoft Edge。
- 接收者不需要安装 Python 或 Node.js。
- 要生成保持 LaTeX 排版的中文 PDF，电脑仍需安装 TeX Live，并确保 latexmk/xelatex 可从 PATH 访问。
- 不要把含有真实 API 密钥或私人论文的 config.env/data 文件夹再次分享给别人。

分享方法
--------

直接分享 PaperReader-v2.0.0-Windows-x64.zip。每位使用者应填写自己的 API 密钥。

开发者重新打包
--------------

在仓库根目录运行 `powershell -ExecutionPolicy Bypass -File .\desktop\build_portable.ps1`。
脚本默认从 PATH 查找 npm 和 Python；也可通过 `-NpmPath`、`-PythonPath` 指定路径。

版本与升级
----------

发布标签为 v2.0，程序/前端版本为 2.0.0。下载包同时提供 SHA-256 校验文件。
EXE 未做代码签名。首次启动后需注册本地账户，再填写自己的 API 设置。
升级时先关闭程序并备份 config.env 和整个 data 文件夹；保留原安装位置和 AUTH_SECRET_KEY，
不要用新包中的配置示例覆盖已有配置。源码版的详细升级及 v1.0 文件导入说明见 docs/UPGRADING.md。

重新构建前安装 Node.js 20 和 Python 3.11，然后运行：
python -m pip install -r desktop/requirements-build.txt
powershell -ExecutionPolicy Bypass -File .\desktop\build_portable.ps1

解压包中的 create_shortcut.ps1 可用于创建直接指向 PaperReader.exe 的桌面快捷方式。
