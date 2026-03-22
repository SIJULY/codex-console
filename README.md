# codex-console

基于 [cnlimiter/codex-manager](https://github.com/cnlimiter/codex-manager) 持续修复和维护的增强版本。

这个版本的目标很直接: 把近期 OpenAI 注册链路里那些“昨天还能跑，今天突然翻车”的坑补上，让注册、登录、拿 token、打包运行都更稳一点。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

## 致谢

首先感谢上游项目作者 [cnlimiter](https://github.com/cnlimiter) 提供的优秀基础工程。

本仓库是在原项目思路和结构之上进行兼容性修复、流程调整和体验优化，适合作为一个“当前可用的修复维护版”继续使用。

## 这个分支修了什么

为适配当前注册链路，这个分支重点补了下面几个问题:

1. **新增 Sentinel POW 求解逻辑**
   OpenAI 现在会强制校验 Sentinel POW，原先直接传空值已经不行了，这里补上了实际求解流程。
2. **注册和登录拆成两段**
   现在注册完成后通常不会直接返回可用 token，而是跳转到绑定手机或后续页面。本分支改成“先注册成功，再单独走一次登录流程拿 token”，避免卡死在旧逻辑里。
3. **去掉重复发送验证码**
   登录流程里服务端本身会自动发送验证码邮件，旧逻辑再手动发一次，容易让新旧验证码打架。现在改成直接等待系统自动发来的那封验证码邮件。
4. **修复重新登录流程的页面判断问题**
   针对重新登录时页面流转变化，调整了登录入口和密码提交逻辑，减少卡在错误页面的情况。
5. **优化终端和 Web UI 提示文案**
   保留可读性的前提下，把一些提示改得更友好一点，出错时至少不至于像在挨骂。

## 核心能力

* Web UI 管理注册任务和账号数据
* 支持批量注册、日志实时查看、基础任务管理
* 支持多种邮箱服务接码（新增智能盲盒轮询机制，强力防风控）
* 支持 SQLite 和远程 PostgreSQL
* 支持打包为 Windows/Linux/macOS 可执行文件
* 更适配当前 OpenAI 注册与登录链路

## 环境要求

* Python 3.10+
* `uv`（推荐）或 `pip`
* Git

---

## 🚀 一键安装与运行 (新手推荐)

对于 Linux / macOS 用户，可以直接在终端复制并运行以下**一行命令**。它会自动拉取代码、安装依赖并直接启动网页控制台：


```bash
git clone [https://github.com/SIJULY/codex-console.git](https://github.com/SIJULY/codex-console.git) && cd codex-console && pip install -r requirements.txt && python webui.py
```
启动成功后，直接在浏览器访问 http://127.0.0.1:8000 即可开始使用！

## 免责声明
本项目仅供学习、研究和技术交流使用，请遵守相关平台和服务条款，不要用于违规、滥用或非法用途。
因使用本项目产生的任何风险和后果，由使用者自行承担。
