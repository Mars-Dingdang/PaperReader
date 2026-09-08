# PaperReader 开发者文档：macOS 本地构建与 Release 发布

本文档面向需要在 **macOS 本地从源代码运行、构建 PaperReader 原生应用**，以及维护 GitHub Release 的开发者。

PaperReader 当前桌面端不是 Electron/Tauri，而是以下组合：

- 前端：React + TypeScript + Vite
- 后端：FastAPI + Uvicorn
- 原生窗口：pywebview（macOS 使用 WKWebView）
- macOS 打包：py2app
- 分发格式：`.app` + `.dmg`
- CI / Release：GitHub Actions

当前 macOS 包只面向 **Apple Silicon (`arm64`)**，最低系统版本为 **macOS 13**。

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

然后安装 Python 构建依赖：

```bash
python -m pip install --upgrade pip
python -m pip install -r desktop/requirements-build.txt
```

`desktop/requirements-build.txt` 会同时安装：

- 后端运行依赖
- `pywebview`
- macOS 下的 `py2app`

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

## 8. 构建后校验

### 8.1 检查签名

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

### 8.2 运行仓库自带 smoke test

GitHub Actions 对正式 macOS 构建执行的是：

```bash
python scripts/smoke_release.py --app dist/PaperReader.app
```

本地准备 Release 前也推荐执行相同检查：

```bash
python scripts/smoke_release.py --app dist/PaperReader.app
```

### 8.3 后端测试

```bash
python -m pytest backend/tests -q
```

### 8.4 Python 语法检查

```bash
python -m compileall -q backend/app desktop/launcher.py
```

### 8.5 前端生产构建

```bash
npm --prefix frontend run build
```

---

## 9. 校验 DMG SHA-256

构建后可执行：

```bash
DMG=$(ls release/PaperReader-v*-macOS-arm64.dmg | head -n 1)
shasum -a 256 "$DMG"
cat "$DMG.sha256"
```

比较两处输出的 SHA-256 digest 是否一致。

> 当前 `build_macos.sh` 在 checksum 文件中写入的是构建机上的 DMG 路径，因此把 `.dmg` 与 `.sha256` 下载到另一台机器后，直接运行 `shasum -c` 可能因为路径不同而失败。此时比较 digest 本身即可。

---

# 10. GitHub Actions 当前 Release 流程

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

# 11. 发布一个新的 Release

## 11.1 版本号 / Tag 约定

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

## 11.2 示例：发布 v2.1.2

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

# 12. 使用 GitHub CLI 查看发布状态

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

# 13. 手动发布 Release（仅故障恢复时使用）

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

# 14. Release 失败时如何处理

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

# 15. 常见问题

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

# 16. 清理本地构建产物

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

---

# 17. 最短命令速查

## 本地直接从源码打开原生 APP

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
