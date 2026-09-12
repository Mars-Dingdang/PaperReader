# PaperReader v2.1.8

[English](../../README.md) | 简体中文

[下载 Windows / macOS v2.1.8](https://github.com/Mars-Dingdang/PaperReader/releases/tag/v2.1.8) · [升级指南](../UPGRADING.md) · [发布说明](releases/v2.1.8.md)

> 📖 **下载前请先阅读[用户说明书](../user_instruction.md)**，其中包含安装（含 Windows 安装包"解除锁定"步骤，可避免绝大多数启动失败）、首次运行的服务商配置、论文提交、历史记录、产物文件与 AI 对话等说明。

v2.1.8 将 LaTeX 链路与 PDF 链路对齐：多文件 TeX 项目先扁平化再翻译，翻译过程逐片段上报进度，失败后从片段断点恢复而不是从头重来。详见[发布说明](releases/v2.1.8.md)。前端/API 版本号：`2.1.8`。

![](../../images/demo1.png)

PaperReader 是一款全栈双语论文阅读应用。上传 PDF 或 LaTeX 源码后，PaperReader 通过 MinerU 云端 API 解析 PDF，使用大模型翻译并保留公式、图片与表格结构，重新编译生成译文 PDF，并支持原文/译文对照阅读与论文问答。

## 桌面版快速开始

- **Windows**：从 Release 页下载 ZIP，完整解压后运行 `PaperReader.exe`。若无法打开，请先对 ZIP "解除锁定"，见[用户说明书](../user_instruction.md)。
- **macOS（Apple Silicon）**：打开 DMG，将 PaperReader 拷贝到"应用程序"。
- 两个平台的安装包首次启动都会打开配置向导，填写你自己的大模型与 [MinerU](https://mineru.net/apiManage/docs) 凭据，其余依赖已全部内置。
- 生成译文 PDF 需要宿主机额外安装 [TeX Live](https://www.tug.org/texlive/) 与 `latexmk`。
- 平台说明：[Windows](../../desktop/README_zh.md) · [macOS](../../desktop/README_macos_zh.md)

## 功能特性

- 用户名/密码账号体系，支持"记住我"登录与个人中心（头像、密码、按用户隔离的 LLM / MinerU / 解析器 / 视觉模型设置）；密钥加密存储，永不回传前端
- 按用户持久化的本地 SQLite 历史记录；重启后可重新打开已处理的文件
- 支持 `.pdf`、单个 `.tex`、逐个上传 TeX 工程文件，或完整的 `.zip` / `.tar` / `.tar.gz` / `.tgz` LaTeX 工程包；arXiv 论文优先使用 LaTeX 源码，结构保留优于 PDF 提取
- PDF 解析走 MinerU 云端 API，无需本地 OCR 或 GPU
- LLM 并发翻译，带逐 chunk 校验检查点与自动重试；失败文档从最近检查点续跑，无需从头再来
- 四层 LaTeX 失败防护：散文本清洗 → strict/降级两级编译 → 有界模型修复 → 浏览器内手动 TeX 编辑器
- 可选的视觉模型逐页对抗校验（自动/手动复核，默认关闭）
- 原文/译文 PDF 对照阅读：生成大纲、文本选择复制、触控板缩放，以及带阶段分解、预计耗时与失败诊断的进度条
- 产物面板：参考文献预览、拖入 PDF 窗格，以及模板提问（Highlight / Baseline / Limitations）
- 基于任意 OpenAI 兼容 API 的论文对话；两侧气泡均支持 Markdown、GitHub 表格与 KaTeX 公式
- 明/暗主题按账号持久化
- 原生桌面应用（Windows 使用 WebView2，macOS 使用 WKWebView），本地会话持久化

## 文档

| 文档 | 内容 |
| --- | --- |
| [用户说明书](../user_instruction.md) | 安装、配置与使用，下载前必读 |
| [开发者文档](../DEVELOPMENT.md) | 源码构建、打包与发布流程、项目结构、环境变量、API 参考 |
| [升级指南](../UPGRADING.md) | 版本间数据迁移 |
| [发布说明](releases/)（[English](../releases/)） | 各版本变更 |
