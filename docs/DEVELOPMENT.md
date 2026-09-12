# PaperReader 开发者文档：Windows / macOS 本地构建与 Release 发布

本文档面向需要在 **Windows 或 macOS 本地从源代码运行、构建 PaperReader 原生应用**，以及维护 GitHub Release 的开发者。Windows 部分的命令行均以 **Git Bash**（Git for Windows 自带）为准。

PaperReader 当前桌面端不是 Electron/Tauri，而是以下组合：

- 前端：React + TypeScript + Vite
- 后端：FastAPI + Uvicorn
- 原生窗口：pywebview（macOS 使用 WKWebView，Windows 使用 WebView2）
- macOS 打包：py2app
- Windows 打包：PyInstaller
- 分发格式：macOS 为 `.app` + `.dmg`；Windows 为可移植版 ZIP
- CI / Release：GitHub Actions

当前 macOS 包只面向 **Apple Silicon (`arm64`)**，最低系统版本为 **macOS 13**。当前 Windows 包只面向 **x64**，最低系统为 **Windows 10 64 位**（需 WebView2 Runtime）。

---

## 1. 环境要求

建议使用：

- Apple Silicon Mac（`arm64`）
- macOS 13+
- Git
- Python **3.11**
- Node.js **20**
- npm
- Xcode Command Line Tools
- 可选：MacTeX / TeX Live（只有生成译文 PDF 时需要）

> `desktop/build_macos.sh` 和 `desktop/setup_macos.py` 当前都按 Python 3.11 / arm64 构建，因此不要直接使用 Python 3.12 或 x86_64 Python 来制作正式 macOS 包。

检查环境：

```bash
uname -m
python3.11 --version
node --version
npm --version
git --version
```

预期至少满足：

```text
arm64
Python 3.11.x
v20.x.x
```

如果尚未安装 Xcode Command Line Tools：

```bash
xcode-select --install
```

如果需要 LaTeX PDF 生成能力，可检查：

```bash
which latexmk
ls -l /Library/TeX/texbin/latexmk
```

PaperReader 桌面启动器会自动检测：

```text
/Library/TeX/texbin/latexmk
```

### Windows（Git Bash）构建环境

- Windows 10/11 64 位（x64）
- Git for Windows（提供 Git Bash）
- Python **3.11**（x64 版本，安装时勾选 "Add python.exe to PATH"）
- Node.js **20**
- npm
- Microsoft WebView2 Runtime（大多数 Windows 10/11 已内置）
- 可选：TeX Live（只有生成译文 PDF 时需要）

> `desktop/build_portable.ps1` 使用 PyInstaller 按 Python 3.11 / x64 构建，与 CI 的 Windows job 一致。Windows 本地构建的完整步骤见下文「在 Windows 上本地构建可移植版（Git Bash）」一节。

---

## 2. 获取源代码

```bash
git clone https://github.com/Mars-Dingdang/PaperReader.git
cd PaperReader
```

如果仓库已经存在：

```bash
git checkout main
git pull --ff-only origin main
```

---

## 3. 创建 Python 环境

### 方案 A：使用独立 conda 环境

```bash
conda create -n paperreader-dev python=3.11 -y
conda activate paperreader-dev
```

如果你已经按照仓库开发约定使用 `d2l` 环境，也可以：

```bash
conda activate d2l
python --version
```

但必须确认输出为 Python 3.11.x。

### 方案 B：使用 venv

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

Windows Git Bash 下没有 `python3.11` 命令，且 venv 的激活脚本位于 `Scripts` 目录（不是 macOS/Linux 的 `bin`）：

```bash
python -m venv .venv
source .venv/Scripts/activate
```

然后安装 Python 构建依赖：

```bash
python -m pip install --upgrade pip
python -m pip install -r desktop/requirements-build.txt
```

`desktop/requirements-build.txt` 会同时安装：

- 后端运行依赖
- `pywebview`
- macOS 下的 `py2app`
- Windows 下的 `pyinstaller`，以及固定的 `pythonnet 3.0.5` / `clr-loader 0.2.7.post0`（pythonnet 3.1.0 的 `Python.Runtime.dll` 无法在 PyInstaller 冻结环境中由 .NET Framework 宿主初始化，窗口打不开，`PaperReader-error.log` 中会出现 `Failed to resolve Python.Runtime.Loader.Initialize`）
- Windows 下的 `setuptools` 固定 `65.5.0`（80.x 的 vendored `jaraco.context` 在 Python 3.11 冻结打包时缺少 `backports.tarfile`，EXE 一启动就崩溃）

---

## 4. 安装前端依赖

仓库包含 `frontend/package-lock.json`，正常开发和 CI 构建优先使用：

```bash
npm --prefix frontend ci
```

如果你修改了 `frontend/package.json` 并需要重新生成 lock file，则使用：

```bash
npm --prefix frontend install
```

然后把 `frontend/package-lock.json` 一并提交。

---

# 5. 从源代码直接打开原生 macOS 应用

这是调试 **完整桌面形态** 最直接的方法。

首先构建前端：

```bash
npm --prefix frontend run build
```

该命令会生成：

```text
frontend/dist/
```

然后直接运行桌面启动器：

```bash
python desktop/launcher.py
```

启动器会：

1. 准备 PaperReader 的本地配置和数据目录；
2. 在 `127.0.0.1:8000` 启动内嵌 FastAPI/Uvicorn 服务；
3. 使用 pywebview 创建原生 macOS 窗口；
4. 通过 WKWebView 显示 `frontend/dist` 中的前端；
5. 关闭窗口后停止内嵌后端。

应用数据默认位于：

```text
~/Library/Application Support/PaperReader/
```

其中包括配置、数据库、WebView 状态以及运行时数据。

如果启动异常，检查：

```text
~/Library/Application Support/PaperReader/PaperReader-error.log
```

### 端口 8000 被占用

检查：

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

确认是旧 PaperReader/uvicorn 进程后，再结束对应 PID：

```bash
kill <PID>
```

然后重新运行：

```bash
python desktop/launcher.py
```

> 原生 source-run 模式读取的是已经构建好的 `frontend/dist`。修改前端后，需要重新执行 `npm --prefix frontend run build` 才会进入原生窗口。

---

# 6. Web 开发模式（前端热更新）

如果主要修改 React UI，推荐使用 Vite 开发服务器，而不是每次重新打包原生窗口。

首次准备：

```bash
cp .env.example .env
npm --prefix frontend ci
python -m pip install -r requirements.txt
```

根据需要填写 `.env` 中的开发配置。

> Windows Git Bash 通常没有 `make`，直接使用下方各自的等价命令即可；`cp .env.example .env` 在 Git Bash 中同样可用。

终端 1：启动 FastAPI：

```bash
make backend
```

等价命令：

```bash
cd backend
uvicorn app.main:app --reload
```

终端 2：启动 Vite：

```bash
make frontend
```

等价命令：

```bash
cd frontend
npm run dev
```

浏览器打开：

```text
http://localhost:5173
```

这种模式适合快速修改 UI；准备正式 `.app` 前仍应做一次原生桌面运行或打包测试。

---

# 7. 在 macOS 本地构建 `.app` 和 `.dmg`

先确认当前环境：

```bash
uname -m
python --version
node --version
```

然后安装构建依赖：

```bash
python -m pip install -r desktop/requirements-build.txt
```

执行完整构建：

```bash
chmod +x desktop/build_macos.sh
./desktop/build_macos.sh
```

脚本会依次执行：

1. `npm ci`
2. `npm run build`
3. 生成 `.icns`
4. 使用 `py2app` 构建原生 `.app`
5. 补入运行时 Python 包/动态库
6. 对 `.app` 执行 ad-hoc `codesign`
7. 使用 `hdiutil` 制作压缩 DMG
8. 生成 SHA-256 文件

应用版本来自：

```text
frontend/package.json -> version
```

例如版本为 `2.1.2` 时，主要输出为：

```text
dist/PaperReader.app
release/PaperReader-v2.1.2-macOS-arm64.dmg
release/PaperReader-v2.1.2-macOS-arm64.dmg.sha256
```

直接打开构建出的 APP：

```bash
open dist/PaperReader.app
```

打开 DMG：

```bash
open release/PaperReader-v2.1.2-macOS-arm64.dmg
```

---

# 8. 在 Windows 上本地构建可移植版（Git Bash）

Windows 版 PaperReader 不是安装器，而是 PyInstaller 打包的 **可移植版**：解压 ZIP 后直接运行 `PaperReader.exe`，最终用户不需要安装 Python 或 Node.js。

以下命令全部在 **Git Bash**（Git for Windows 自带）中执行。

## 8.1 从源码直接打开原生 Windows 应用

调试完整桌面形态时，先构建前端，再运行与 macOS 相同的桌面启动器：

```bash
npm --prefix frontend run build
python desktop/launcher.py
```

启动器会：

1. 准备 PaperReader 的本地配置和数据目录；
2. 在 `127.0.0.1:8000` 启动内嵌 FastAPI/Uvicorn 服务；
3. 使用 pywebview 创建原生 Windows 窗口（WebView2 / EdgeChromium）；
4. 显示 `frontend/dist` 中的前端；
5. 关闭窗口后停止内嵌后端。

应用数据默认位于：

```text
%LOCALAPPDATA%\PaperReader\
```

Git Bash 中即 `~/AppData/Local/PaperReader/`，其中包括配置、数据库、WebView 状态以及运行时数据。启动异常时检查：

```text
%LOCALAPPDATA%\PaperReader\PaperReader-error.log
```

### 端口 8000 被占用

```bash
netstat -ano | grep :8000 | grep LISTENING
```

输出最后一列是 PID。确认是旧 PaperReader/uvicorn 进程后结束它（Git Bash 中 `taskkill` 的参数斜杠要写成 `//`，避免被 MSYS 转换成路径）：

```bash
taskkill //PID <PID> //F
```

然后重新运行 `python desktop/launcher.py`。

> 原生 source-run 模式读取的是已经构建好的 `frontend/dist`。修改前端后，需要重新执行 `npm --prefix frontend run build` 才会进入原生窗口。

## 8.2 构建可移植版 ZIP

安装构建依赖（`desktop/requirements-build.txt` 通过 `sys_platform` 在 Windows 下安装 PyInstaller）：

```bash
python -m pip install -r desktop/requirements-build.txt
```

构建脚本是 PowerShell 脚本，从 Git Bash 直接调用 `powershell.exe` 执行：

```bash
powershell -ExecutionPolicy Bypass -File ./desktop/build_portable.ps1
```

如果 `python` 或 `npm` 不在 PATH，可显式指定路径：

```bash
powershell -ExecutionPolicy Bypass -File ./desktop/build_portable.ps1 \
  -PythonPath "C:/Python311/python.exe" \
  -NpmPath "C:/Program Files/nodejs/npm.cmd"
```

脚本会依次执行：

1. `npm ci`
2. `npm run build`
3. 使用 PyInstaller（`desktop/PaperReader.spec`）打包 `PaperReader.exe`
4. 把 `desktop/README_zh.md` 复制为包内 `使用说明.txt`，并放入 `create_shortcut.ps1`
5. 压缩为 ZIP 并生成 SHA-256 文件

应用版本同样来自 `frontend/package.json -> version`。例如版本为 `2.1.2` 时，主要输出为：

```text
dist/PaperReader/PaperReader.exe
release/PaperReader-v2.1.2-Windows-x64.zip
release/PaperReader-v2.1.2-Windows-x64.zip.sha256
```

直接运行打包出的 EXE：

```bash
./dist/PaperReader/PaperReader.exe
```

> 脚本内部会自行执行 `npm ci` 和 `npm run build`，因此打包前不需要单独构建前端。

## 8.3 构建后校验

与 CI 的 Windows job 一致的 smoke test：

```bash
python scripts/smoke_release.py --web
python scripts/smoke_release.py --archive release/PaperReader-v2.1.2-Windows-x64.zip
```

校验 ZIP 的 SHA-256（Git Bash 自带 `sha256sum`）：

```bash
sha256sum release/PaperReader-v*-Windows-x64.zip
cat release/PaperReader-v*-Windows-x64.zip.sha256
```

比较两处输出的 SHA-256 digest 是否一致。

后端测试与 Python 语法检查与 macOS 相同：

```bash
python -m pytest backend/tests -q
python -m compileall -q backend/app desktop/launcher.py
```

---

## 9. macOS 构建后校验

### 9.1 检查签名

```bash
codesign --verify --deep --strict --verbose=2 dist/PaperReader.app
```

当前脚本使用的是 **ad-hoc signing**：

```bash
codesign --force --deep --sign - dist/PaperReader.app
```

这不是 Developer ID 签名，也没有经过 Apple Notarization。

因此通过 GitHub Release 分发后，用户第一次启动时可能需要：

1. Finder 中找到 PaperReader；
2. Control-click / 右键；
3. 选择“打开”。

### 9.2 运行仓库自带 smoke test

GitHub Actions 对正式 macOS 构建执行的是：

```bash
python scripts/smoke_release.py --app dist/PaperReader.app
```

本地准备 Release 前也推荐执行相同检查：

```bash
python scripts/smoke_release.py --app dist/PaperReader.app
```

### 9.3 后端测试

```bash
python -m pytest backend/tests -q
```

### 9.4 Python 语法检查

```bash
python -m compileall -q backend/app desktop/launcher.py
```

### 9.5 前端生产构建

```bash
npm --prefix frontend run build
```

---

## 10. 校验 DMG SHA-256

构建后可执行：

```bash
DMG=$(ls release/PaperReader-v*-macOS-arm64.dmg | head -n 1)
shasum -a 256 "$DMG"
cat "$DMG.sha256"
```

比较两处输出的 SHA-256 digest 是否一致。

> 当前 `build_macos.sh` 在 checksum 文件中写入的是构建机上的 DMG 路径，因此把 `.dmg` 与 `.sha256` 下载到另一台机器后，直接运行 `shasum -c` 可能因为路径不同而失败。此时比较 digest 本身即可。

---

# 11. GitHub Actions 当前 Release 流程

仓库已经配置：

```text
.github/workflows/release.yml
```

普通 `main` push / PR 会执行测试和打包检查；当 push 的 tag 匹配：

```text
v2.*
```

时，会执行完整 Release 流程。

主要阶段：

1. Linux / Windows / macOS 后端兼容性测试；
2. Windows x64 portable 构建 + smoke test；
3. macOS arm64 APP/DMG 构建 + smoke test；
4. 下载两个平台的 workflow artifacts；
5. 自动创建新的 GitHub Release，或在同名 Release 已存在时更新说明并替换旧资产；
6. 将 Windows ZIP、macOS DMG 和 checksum 文件作为 Release assets 上传。

正式 Release 由该 GitHub Actions 流程自动发布。

---

# 12. 发布一个新的 Release

## 12.1 版本号 / Tag 约定

workflow 要求 Git tag 与 `frontend/package.json` 的完整 SemVer 严格一致：

```bash
VERSION=$(python -c "import json; print(json.load(open('frontend/package.json'))['version'])")
test "$RELEASE_TAG" = "v$VERSION"
```

也就是说：

```text
frontend/package.json: 2.1.2
Git tag:               v2.1.2
Release notes:         docs/releases/v2.1.2.md
```

旧的 `v2.1` 短标签保持不动；所有新版本（包括 patch release）都使用完整三段版本号。

---

## 12.2 示例：发布 v2.1.2

假设准备发布：

```text
应用版本：2.1.2
Git tag：v2.1.2
```

### Step 1：更新前端版本号

推荐让 npm 同时维护 `package.json` 和 `package-lock.json`：

```bash
cd frontend
npm version 2.1.2 --no-git-tag-version
cd ..
```

确认：

```bash
node -p "require('./frontend/package.json').version"
```

应该输出：

```text
2.1.2
```

### Step 2：创建 Release Notes

创建：

```text
docs/releases/v2.1.2.md
```

文件名必须与 Git tag 一致，因为 workflow 会直接读取：

```text
docs/releases/$RELEASE_TAG.md
```

可以参考已有：

```text
docs/releases/v2.1.2.md
```

### Step 3：本地验证

至少执行：

```bash
python -m pytest backend/tests -q
python -m compileall -q backend/app desktop/launcher.py
npm --prefix frontend run build
```

如果本机是 Apple Silicon Mac，建议额外执行：

```bash
./desktop/build_macos.sh
python scripts/smoke_release.py --app dist/PaperReader.app
```

如果本机是 Windows，建议额外执行（Git Bash）：

```bash
powershell -ExecutionPolicy Bypass -File ./desktop/build_portable.ps1
python scripts/smoke_release.py --web
python scripts/smoke_release.py --archive release/PaperReader-v*-Windows-x64.zip
```

### Step 4：提交 Release 准备变更

```bash
git status
git add frontend/package.json frontend/package-lock.json docs/releases/v2.1.2.md
git commit -m "prepare v2.1.2 release"
git push origin main
```

推荐先等待 `main` 对应的 GitHub Actions 全部通过。

### Step 5：创建并 push tag

```bash
git checkout main
git pull --ff-only origin main
git tag -a v2.1.2 -m "PaperReader v2.1.2"
git push origin v2.1.2
```

**push tag 是正式 Release 的触发动作。**

GitHub Actions 随后会自动构建并发布 Release。

---

# 13. 使用 GitHub CLI 查看发布状态

如果安装了 `gh`：

```bash
gh auth status
```

查看 workflow：

```bash
gh run list --workflow release.yml --limit 10
```

查看某次运行：

```bash
gh run view <RUN_ID>
```

实时查看：

```bash
gh run watch <RUN_ID>
```

发布成功后：

```bash
gh release view v2.1.2
```

查看 Release assets：

```bash
gh release view v2.1.2 --json assets
```

---

# 14. 手动发布 Release（仅故障恢复时使用）

正常情况应让 `.github/workflows/release.yml` 自动发布，因为它会保证 Windows/macOS 都经过对应 smoke test。

如果 CI 已经成功构建了全部 artifacts，但最后的 `publish` job 单独失败，可以下载/收集完整 Release 文件后手动执行类似：

```bash
gh release create v2.1.2 \
  release/* \
  --verify-tag \
  --title "PaperReader v2.1.2" \
  --notes-file docs/releases/v2.1.2.md \
  --latest
```

不要在只有 macOS DMG、没有 Windows ZIP 的情况下随意执行这条命令，否则会产生不完整的正式 Release。

---

# 15. Release 失败时如何处理

## 测试或打包 job 失败

优先修复代码/构建问题并重新 push commit。

如果只是偶发 CI 问题，也可以在 GitHub Actions 页面重新运行失败 jobs。

不要反复删除并移动已经公开发布的 tag，除非明确知道这样做对已有用户和下载链接的影响。

## tag 已 push，但 Release 尚未创建

修复 workflow 或代码后，可以重新运行该 tag 对应 workflow run。

## Release 已创建

正常情况下不要复用同一个版本号做不同内容的正式发布。应创建新版本。

如果维护者明确决定修复并重新发布同一个版本，先通过 PR 将修复合并到 `main`，确认 `main` CI 通过，再将现有标签重指向新的合并提交并强制推送该标签。标签 workflow 会重新构建 Windows 与 macOS 包；发布步骤检测到同名 Release 后，会用 `gh release upload --clobber` 替换全部资产，并从 `docs/releases/<tag>.md` 更新 Release 标题和说明。不要手工混用新旧构建资产。

---

# 16. 常见问题

## `npm ci` 失败

如果出现 lock file 与 `package.json` 不一致：

```bash
npm --prefix frontend install
```

确认变更后提交：

```bash
git add frontend/package.json frontend/package-lock.json
```

## py2app 构建失败

先确认：

```bash
python --version
python -c "import platform; print(platform.machine())"
python -c "import py2app; print(py2app.__version__)"
```

应重点确认 Python 3.11 和 arm64。

构建日志位于：

```text
build/macos-py2app.log
```

查看尾部：

```bash
tail -120 build/macos-py2app.log
```

## APP 打开后立刻退出

检查：

```text
~/Library/Application Support/PaperReader/PaperReader-error.log
```

以及端口：

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

## Windows 打包版无法启动或窗口空白

确认已安装 Microsoft WebView2 Runtime（大多数 Windows 10/11 已内置）。启动失败详情见：

```text
%LOCALAPPDATA%\PaperReader\PaperReader-error.log
```

以及端口占用（Git Bash）：

```bash
netstat -ano | grep :8000 | grep LISTENING
taskkill //PID <PID> //F
```

## 可以打开 APP，但不能生成译文 PDF

检查 `latexmk`：

```bash
/Library/TeX/texbin/latexmk -v
```

没有安装时需要安装 MacTeX / TeX Live。

## 用户下载 DMG 后提示无法验证开发者

当前 macOS Release 是 ad-hoc signed、未 notarize。这是现有发布方式的已知限制。

首次启动通常可以：Finder → Control-click PaperReader → Open。

若未来希望正常双击、减少 Gatekeeper 警告，需要增加：

- Apple Developer ID Application 签名
- Hardened Runtime
- Apple notarization (`notarytool`)
- stapling

这些步骤目前没有集成进仓库 Release workflow。

---

# 17. 清理本地构建产物

如果需要重新做一次干净构建：

```bash
rm -rf build dist frontend/dist
```

如果 `release/` 中没有需要保留的本地包，也可以额外删除：

```bash
rm -rf release
```

重新构建：

```bash
./desktop/build_macos.sh
```

Windows Git Bash 中同样使用上述 `rm -rf` 命令清理，然后重新执行：

```bash
powershell -ExecutionPolicy Bypass -File ./desktop/build_portable.ps1
```

---

# 18. 最短命令速查

## 本地直接从源码打开原生 APP（macOS）

```bash
git clone https://github.com/Mars-Dingdang/PaperReader.git
cd PaperReader

conda create -n paperreader-dev python=3.11 -y
conda activate paperreader-dev

python -m pip install -r desktop/requirements-build.txt
npm --prefix frontend ci
npm --prefix frontend run build
python desktop/launcher.py
```

## 构建 macOS APP + DMG

```bash
conda activate paperreader-dev
./desktop/build_macos.sh
open dist/PaperReader.app
```

## 本地直接从源码打开原生 APP（Windows Git Bash）

```bash
git clone https://github.com/Mars-Dingdang/PaperReader.git
cd PaperReader

python -m venv .venv
source .venv/Scripts/activate

python -m pip install -r desktop/requirements-build.txt
npm --prefix frontend ci
npm --prefix frontend run build
python desktop/launcher.py
```

## 构建 Windows 可移植版 ZIP（Git Bash）

```bash
source .venv/Scripts/activate
python -m pip install -r desktop/requirements-build.txt
powershell -ExecutionPolicy Bypass -File ./desktop/build_portable.ps1
./dist/PaperReader/PaperReader.exe
```

## 发布下一个 SemVer Release（以 v2.1.2 为例）

```bash
cd frontend
npm version 2.1.2 --no-git-tag-version
cd ..

# 编写 docs/releases/v2.1.2.md

python -m pytest backend/tests -q
npm --prefix frontend run build
./desktop/build_macos.sh
python scripts/smoke_release.py --app dist/PaperReader.app

git add frontend/package.json frontend/package-lock.json docs/releases/v2.1.2.md
git commit -m "prepare v2.1.2 release"
git push origin main

git tag -a v2.1.2 -m "PaperReader v2.1.2"
git push origin v2.1.2
```

之后由 GitHub Actions 自动生成 Windows x64 和 macOS arm64 构建并发布 GitHub Release。

---

# 19. 全栈 Web 开发参考

以下内容自 README 移入，面向直接运行后端 + 前端（或 Docker 部署）的开发与联调场景；桌面端构建与发布见上文第 1–18 节。

## 19.1 项目结构

```text
PaperReader/
├── backend/
│   └── app/
│       ├── api/            # routes_*.py：auth / setup / upload / document / chat / project / review / recompile / data
│       ├── core/           # config.py、database.py
│       ├── models/         # schemas.py、store.py
│       ├── services/       # document_pipeline、translate_service、alignment_service、llm_client、
│       │                   # mineru_service、mineru_layout、latex_service、latex_sanitizer、latex_recovery、
│       │                   # project_archive、vision_check_service、auth_service、chat_store、
│       │                   # legacy_import、literature_service、stage_tracker
│       ├── workers/        # tasks.py（Celery）
│       └── main.py
├── desktop/                # 桌面端启动器与打包脚本（见第 1–18 节）
├── frontend/
│   ├── src/
│   │   ├── components/     # ReaderPage 使用的 UI 组件
│   │   ├── lib/            # api.ts、pdfDocumentOptions.ts
│   │   ├── pages/          # ReaderPage.tsx
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   └── styles.css
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts
├── data/                   # 运行时数据（uploads / outputs / paperreader.db），不要提交
├── docs/                   # 用户说明书、开发者文档、release notes
├── infra/                  # Dockerfile.backend
├── scripts/                # setup_*.sh / .ps1、smoke_release.py、benchmark_llm_rate.py
├── .env.example
├── docker-compose.yml
├── Makefile
└── requirements.txt
```

## 19.2 Python 依赖

来自 `requirements.txt`：

- fastapi==0.115.0
- uvicorn[standard]==0.30.6
- python-multipart==0.0.9
- pydantic==2.9.2
- pydantic-settings==2.5.2
- openai==1.51.2
- requests==2.32.3
- celery==5.4.0
- redis==5.0.8
- httpx==0.27.2
- pytest==8.3.3
- pypdf==4.3.1
- pypdfium2==4.30.0
- Pillow==10.4.0

## 19.3 环境变量

复制环境文件并填写 OpenAI 兼容端点与密钥：

```bash
cp .env.example .env
```

### 必需变量

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `MINERU_API_KEY`（在 https://mineru.net/apiManage/docs 申请）
- `AUTH_SECRET_KEY` — 账号模式下的本地会话签名/加密密钥

### 可选 / 调优变量

- `SQLITE_DB_NAME`（默认 `paperreader.db`）— `DATA_DIR` 下的本地持久化数据库文件。
- `SESSION_DAYS`（默认 `1`）— 普通登录会话有效期。
- `REMEMBER_ME_DAYS`（默认 `30`）— "记住我"会话有效期。
- `TRANSLATE_CONCURRENCY`（默认 `4`）— 并行翻译的 chunk 数。
- `TRANSLATE_MAX_RETRIES`（默认 `5`）— 单次 LLM 调用的重试预算；使用带抖动的指数退避，并遵守 `Retry-After`。
- `LLM_RATE_LIMIT_RPS`（默认 `4`）— 所有 worker 线程共享的 LLM 全局限速（每秒请求数，令牌桶）。设为 `0` 关闭。建议低于服务商/密钥公布的 RPM 以避免 429。注意：该限速按单个 uvicorn 进程生效；若扩展为 N 个 worker，实际限速为 `N × LLM_RATE_LIMIT_RPS`。
- `TRANSLATE_BATCH_MAX_CHARS`（默认 `6000`）— 每个 IR 批量请求拼接字符数上限。调大可摊薄往返延迟，但单次请求体更大。
- `TRANSLATE_SEGMENT_MAX_CHARS`（默认 `2000`）— 单个散文本段落的硬上限。超长 MinerU 段落会被拆分再重组，避免模型输出上限截断后半段。
- `VISION_MODEL`（默认 `GLM-4.5V`）— Phase D 视觉校验使用的多模态模型，必须与 `OPENAI_BASE_URL` 同一 OpenAI 兼容端点且支持视觉（如 `GLM-4.5V`、`GLM-4.6V`、`Qwen3-VL-30B-A3B-Instruct`、`Qwen3-VL-235B-A22B-Instruct`）。
- `VISION_CHECK_ENABLED`（默认 `false`）、`VISION_CHECK_MODE`（`auto` | `manual`）、`VISION_CHECK_MAX_PAGES`（默认 `8`）— Phase D 的部署默认值。新账号默认关闭校验，可在侧边栏或个人中心开启自动/手动校验。
- `LATEXMK_PATH` — 当 `latexmk` 不在 `PATH` 上时，指向其绝对路径。

### MinerU PDF 解析

PDF 解析走 MinerU 精准解析 API（无需本地 OCR / GPU / 大模型下载）。除 API Key 外均可选：

- `MINERU_API_KEY` — MinerU 账号的 Bearer token。
- `MINERU_BASE_URL` — 默认 `https://mineru.net/api/v4`。
- `MINERU_MODEL_VERSION` — `vlm`（推荐）、`pipeline` 或 `MinerU-HTML`。
- `MINERU_LANGUAGE` — 英文论文 `en`，中文 `ch` 等。
- `MINERU_ENABLE_FORMULA`、`MINERU_ENABLE_TABLE`、`MINERU_IS_OCR` — 功能开关。
- `MINERU_POLL_INTERVAL`（秒）、`MINERU_TIMEOUT`（秒）— 轮询控制。

MinerU 侧限制：文件 ≤ 200 MB，≤ 200 页，每账号每天 1000 高优先级页。需允许访问 `mineru.net` 及其返回的 OSS/CDN 域名。

## 19.4 本地运行

Web 开发模式（前端热更新，`make backend` / `make frontend`）已在上文第 6 节说明，此处只补充其余命令。

启动可选的 Celery worker（用于后续异步任务扩展，请在独立终端运行）：

```bash
make worker
# 等价：cd backend && celery -A app.workers.tasks worker -l info
```

前端构建与预览：

```bash
npm --prefix frontend run build      # 产出 frontend/dist
npm --prefix frontend run preview    # 本地预览生产构建
```

常用校验：

```bash
pytest                               # 运行后端测试
python -m compileall backend/app     # 快速语法检查
```

> 上传与解析在请求链路中是同步执行的；处理较大 PDF 时前端会持续轮询 `GET /api/document/{id}` 直至 `status` 变为 `done` 或 `failed`。

## 19.5 账号系统

- 上传、项目、历史、对话、视觉校验与重新编译等 API 均需登录。
- 登录使用用户名 + 密码，凭据为 HttpOnly 会话 Cookie。
- "记住我"仅延长 Cookie 有效期，不会明文存储密码。
- 用户数据持久化在本地 SQLite：`users`、`sessions`、`user_settings`、`documents`、`projects`。
- 按用户隔离的设置包括：主题、视觉校验偏好、收藏、个人 LLM `API Key` / `Base URL` / `Model`、个人 parser / MinerU 密钥与选项、视觉模型。

### 个人中心

登录后点击侧边栏账号区域进入个人中心，可以：

- 上传/更换头像
- 修改用户名
- 修改密码
- 配置个人 LLM 设置
- 管理持久化的阅读偏好

对话默认使用当前用户保存的 LLM 设置；为空时回退到后端 `.env` 默认值。

## 19.6 Docker 部署

```bash
docker compose up --build
```

服务地址：

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`
- Redis: `localhost:6379`

## 19.7 API 端点

- `GET /health`
- **认证 / 设置（routes_auth.py）**
  - `POST /api/auth/register`
  - `POST /api/auth/login`
  - `POST /api/auth/logout`
  - `GET /api/auth/me`
  - `PATCH /api/auth/profile`
  - `POST /api/auth/change-password`
  - `POST /api/auth/avatar`
  - `PUT /api/settings/me`
  - `PUT /api/settings/me/providers`
- **首次运行向导（routes_setup.py）**
  - `GET /api/setup/status`
  - `PUT /api/setup`
- **上传**
  - `POST /api/upload`（multipart 文件：`.pdf` 或 `.tex`；表单字段 `vision_check_enabled`、`vision_check_mode`）
- **文档**
  - `GET /api/documents` — 列出当前登录用户的文档摘要
  - `GET /api/document/{document_id}`
  - `PATCH /api/document/{document_id}`
  - `DELETE /api/document/{document_id}` — 软删除当前用户的一条历史记录
  - `POST /api/document/{document_id}/retry` — 重新排队失败文档，从最近校验点续跑
  - `POST /api/document/{document_id}/locate-counterpart` — 双语对应定位，返回 `highlight_text` 用于片段级高亮
  - `GET|POST /api/document/{document_id}/annotations`、`DELETE /api/document/{document_id}/annotations/{id}` — 持久化批注
  - `GET /api/document/{document_id}/notes.md` — 导出双语 Markdown 阅读笔记
  - `PATCH /api/document/{document_id}/progress` — 保存阅读位置（`last_read_page` / `last_read_ratio`）
  - `GET /api/document/{document_id}/structure` — 后端解析的章节目录与图表列表
  - `GET /api/document/{document_id}/bibtex` — BibTeX 导出（TeX 工程优先返回工程内 `.bib`）
  - `GET /api/search?q=` — 跨文档全文搜索
- **项目（TeX 工程）**
  - `POST /api/project` — 创建 TeX 项目
  - `GET /api/project/{project_id}` — 查看文件与主文件候选
  - `POST /api/project/{project_id}/files` — 多次上传项目文件
  - `POST /api/project/{project_id}/archive` — 安全导入 `.zip`、`.tar`、`.tar.gz` 或 `.tgz` LaTeX 工程包
  - `POST /api/project/{project_id}/delete-files`
  - `POST /api/project/{project_id}/build` — 选定主 `.tex` 后启动编译流水线
  - `DELETE /api/project/{project_id}`
- **视觉校验（Phase D）**
  - `GET /api/document/{document_id}/review`
  - `POST /api/document/{document_id}/review` — 接受 / 拒绝视觉模型提出的修订
- **手动 TeX 重新编译**
  - `GET /api/document/{document_id}/tex` — 读取当前 `translated.tex`
  - `POST /api/document/{document_id}/tex` — 保存修改后重新编译（源文件先经 `latex_sanitizer` 清洗，并启用 strict→`-f` 降级编译）
  - `POST /api/document/{document_id}/tex/reveal` — 在系统文件管理器中显示产物
- **对话**
  - `POST /api/chat` — 阻塞式回答（保留兼容）；请求体可带 `quote` 注入选中文本的双语上下文
  - `POST /api/chat/stream` — SSE 流式回答（`meta` / `delta` / `done` / `error` 事件）
  - `POST /api/chat/sessions`
  - `GET /api/chat/sessions`
  - `GET /api/chat/sessions/{session_id}`
- **产物访问**
  - `GET|HEAD /data/{file_path}` — 产物文件下载，按账号校验归属

### `GET /api/document/{document_id}` 响应要点

- `source_filename`
- `updated_at`、`last_opened_at`
- `artifacts`（上传与生成的文件）
- `references`（提取的参考文献条目，用于预览）
- `progress`、`current_stage`、`current_stage_label`、`eta_seconds`、`stages`（Phase A）
- `pending_reviews` — `manual` 模式下等待人工决策的视觉模型修订提案（Phase D）
- `last_compile_warning` — strict 编译失败但宽松 `-f` 编译仍产出 PDF 时设置；UI 会提示用户打开手动 TeX 编辑器清理
- 以及既有的 `status`、`original_pdf_url`、`translated_pdf_url`、`logs`

### 对话请求体

```json
{
  "document_id": "uuid",
  "message": "What is the main contribution?",
  "override_api_key": "",
  "override_base_url": "",
  "override_model": ""
}
```

`override_*` 字段可选。当前 UI 中，对话通常直接使用登录用户保存的个人设置。

### LaTeX 归档安全

项目压缩包按文件名与内容双重识别后本地解压。导入最多允许 2,000 个成员、单文件 20 MB、整包 200 MB。绝对路径、`..` 穿越路径、链接、设备条目、加密 ZIP 成员、重复/冲突路径、损坏压缩包以及不含 `.tex` 的压缩包都会被原子性拒绝。导入后 UI 展示按置信度排序的主文件候选，等待用户确认后才会开始解析或翻译。

## 19.8 平台说明

### macOS (Apple Silicon)

- PDF 解析经 MinerU 云端完成，无需本地 Torch/MPS 配置。
- PDF 内的 HTTP(S) 链接在系统浏览器打开；PaperReader 窗口保留当前论文与阅读位置。
- WKWebView 阅读器支持 PDF 文本选择/复制、生成的大纲与更快的触控板捏合缩放。
- LaTeX 编译失败时，安装 TeX Live + `latexmk` 及中文字体。

### Linux (CUDA)

- PDF 解析无需 GPU（MinerU 云端）。
- LLM 翻译仍使用 `.env` 中配置的 OpenAI 兼容端点。

### Windows

- 使用 `scripts/setup_windows.ps1`。
- 安装 TeX Live + `latexmk`，并确保可执行文件在 `PATH` 中。

## 19.9 当前实现边界

- 上传处理仍在请求链路中同步执行（尚未引入后台任务交接）；文档内的翻译 chunk 通过线程池并发。
- 文档/项目/账号状态持久化在 SQLite，但应用目前面向本地/小规模部署设计，而非加固的互联网级多租户服务。
- 参考文献提取是启发式的（基于章节/行模式），不是完整的引文解析器。
- 前端支持登录/注册、个人中心、面板开关、拖拽产物预览、视觉校验人工复核以及浏览器内 `translated.tex` 编辑器。
- LaTeX 编译先跑 strict 一遍，再跑宽松的 `-f` 一遍，使流水线极少以硬失败告终；警告通过 `last_compile_warning` 上报，手动编辑器支持就地修补源码并重新编译。
