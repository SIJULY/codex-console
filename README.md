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

## 🚀 快速安装与运行

根据你的使用环境，我们提供了两种启动方式。如果你想在云服务器上 24 小时挂机注册，强烈推荐使用第二种**后台常驻部署**。

### 方案一：极简一键运行 (适合本地电脑 / 已有 Python 3.10+ 环境)

对于 macOS 或带有较新 Python 环境的 Linux 桌面用户，直接在终端执行以下命令即可拉取并启动：

```bash
git clone https://github.com/SIJULY/codex-console.git && cd codex-console && pip install -r requirements.txt && python webui.py --port 8090 --access-password admin888
```
启动成功后，浏览器访问 http:///127.0.0.1:8090，密码 admin888 即可使用。

### 方案二：云服务器全自动后台部署 (⭐ 强烈推荐)

如果你使用的是云服务器（如甲骨文 ARM 实例、Ubuntu 20.04 等），系统默认环境可能较老，且 SSH 断开会导致任务停止。请使用以下步骤进行 纯净环境构建 + Systemd 守护进程部署

* 一. 准备纯净的 Python 3.10 虚拟环境 (以 Miniconda 为例)
```bash
# 下载并安装 Miniconda (根据你的 CPU 架构替换链接，此处为 ARM64 示例)
mkdir -p ~/miniconda3
wget [https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh](https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh) -O ~/miniconda3/miniconda.sh
bash ~/miniconda3/miniconda.sh -b -u -p ~/miniconda3
source ~/miniconda3/bin/activate

# 创建并激活名为 codex 的专属环境
conda create -n codex python=3.10 -y
conda activate codex
```

* 二. 拉取代码并安装依赖
```bash
# 推荐将项目放在 /opt 目录下统一管理
git clone https://github.com/SIJULY/codex-console.git /opt/codex-console
cd /opt/codex-console
pip install -r requirements.txt
```bash

* 三. 注册系统级后台服务 (Systemd)

执行以下命令，让控制台开机自启、崩溃自动重启，彻底脱离 SSH 窗口独立运行：
```bash
cat << 'EOF' > /etc/systemd/system/codex.service
[Unit]
Description=Codex Console Web UI
After=network.target

[Service]
User=root
WorkingDirectory=/opt/codex-console
# 请确保以下 Python 路径与你实际的虚拟环境路径一致
ExecStart=/root/miniconda3/envs/codex/bin/python webui.py --port 8090 --access-password admin888
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 启动并设置开机自启
systemctl daemon-reload
systemctl enable codex
systemctl start codex
```bash
🎉 部署完成！浏览器访问 http://ip:8090，密码 admin888 即可使用。

## 免责声明
本项目仅供学习、研究和技术交流使用，请遵守相关平台和服务条款，不要用于违规、滥用或非法用途。
因使用本项目产生的任何风险和后果，由使用者自行承担。
