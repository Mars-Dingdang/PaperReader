PaperReader Windows 可移植版
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

直接分享 PaperReader-Windows-x64.zip。每位使用者应填写自己的 API 密钥。

开发者重新打包
--------------

在仓库根目录运行 `powershell -ExecutionPolicy Bypass -File .\desktop\build_portable.ps1`。
脚本默认从 PATH 查找 npm 和 Python；也可通过 `-NpmPath`、`-PythonPath` 指定路径。
