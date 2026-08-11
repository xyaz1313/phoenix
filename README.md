# 不死鸟 Phoenix

<img src="docs/images/cover.png" alt="不死鸟 Phoenix" width="100%">

[![Version](https://img.shields.io/badge/version-7.6.2-2563EB.svg?style=flat-square)](phoenix_v7/plugin.yaml)
[![Tests](https://img.shields.io/badge/tests-338%2F338-A3FF12.svg?style=flat-square)](phoenix_v7/tests)
[![License](https://img.shields.io/badge/license-CC%20BY--NC%204.0-16A34A.svg?style=flat-square)](LICENSE)

> 装在 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 上的插件。路由分档、风险防线、自愈系统，全程官方插件钩子接入，不改 Hermes 一行核心代码。

**支持：Hermes Agent。** 全程通过官方插件系统加载，卸载即恢复原状。

[解决什么问题](#不死鸟解决什么问题) · [快速开始](#快速开始) · [能力一览](#能力一览) · [视觉总览](#视觉总览) · [安装](#安装) · [项目结构](#项目结构)

## 不死鸟解决什么问题

Hermes Agent 本身是一个通用 Agent 框架，很多"用起来更安心"的能力要么官方还没做，要么需要自己配置。不死鸟把这些补上：

| 真实处境 | 你会得到 |
| --- | --- |
| 不知道一句话该配给哪个模型，贵模型处理"在吗"很浪费 | 四档加权计分自动判定，问题难度和模型成本自动对齐 |
| AI 代理连续报错，越错越乱还在硬着头皮往下跑 | 三态熔断器，连续失败自动跳闸，冷却后自动试探恢复 |
| 同样的错误反复踩，AI 每次都从头试错 | 抗体库查表，错误模式记下来，同一个坑不踩两次 |
| 长任务没人盯着，AI 跳过规划直接动手，或者悄悄做了高危操作 | `/goal` 激活期间清单强制 + 高危操作换模型复核 |
| 高危档位的回复到底有没有编造内容，肉眼看不出来 | 免费预检 + 付费交叉核验，仅在深度/真神档触发 |
| 主力模型欠费了，AI 直接罢工 | 本地 26B 模型优先兜底（仅 macOS），云端免费档二级兜底 |
| 聊到手机号/身份证/密码这类敏感信息，不确定要不要发去云端 | 命中敏感词后事后提醒，引导手动切到本地模型处理（仅 macOS） |
| 装的这版插件到底跟你电脑上的 Hermes 版本合不合 | 运行时自动比对，明确告诉你"合不合" |

## 快速开始

安装完成后，直接正常使用 Hermes：所有路由、防线都是自动生效的，不需要学新命令。

看当前状态：

```bash
hermes phoenix-status
```

一条命令看路由模式、熔断器状态、长任务状态、Hermes 版本兼容性、今日花费、抗体库统计。

**自动路由换模型默认关闭**（只判断问题难度档位，不切换模型），只用单一模型的用户完全不用管这一项。如果你给不同档位配置了不同模型，可以自己开关：

```bash
hermes phoenix-router on   # 开启：按档位自动切换模型
hermes phoenix-router off  # 关闭：只判断档位，不切换模型（默认状态）
```

桌面端没有终端，用对话里的斜杠命令一样能切：`/phoenix-router on|off|status`。

怎么给档位配模型（单模型/多模型分Key/中转站三种情况分别怎么填）见 [三场景配置指南](phoenix_v7/docs/三场景配置指南.md)。

想专心用固定模型干活、不想被深度/真神档的确认提示打断，用专注模式（CLI/桌面端通用）：

```text
/phoenix-focus on   # 暂停确认提示（hardline永久高危命令不受影响）
/phoenix-focus off  # 恢复
```

同一次会话里连续弹了 3 次确认提示，第 3 次会自动带一句"要不要开专注模式"的建议，不会每次都提醒。

Hermes 升级后如果出问题，用 `/phoenix-upgrade-log` 看版本变化历史和自动归档的异常记录（升级瞬间会自动备份 `config.yaml`，路径也在这条命令的输出里）。

长任务场景直接用 Hermes 原生命令，不死鸟自动接管清单强制和高危复核：

```text
/goal 帮我重构一下这个模块的架构，确保测试全过
```

## 能力一览

| 模块 | 职责 | 一句话说明 |
| --- | --- | --- |
| Router 路由分档 | 判断用哪个档位、哪个模型 | 闪答/日常/深度/真神四档加权计分自动判定 |
| Guardrails 风险防线 | 防止失控烧钱或闯祸 | 三态熔断器 + 高危操作审批闸 + 候选链健康追踪 |
| Selfheal 自愈系统 | 错误处理经验积累 | 抗体库查表，3次未解决自动升级，坏建议自动停用 |
| Loop Guard 长任务守护 | `/goal` 激活期间的安全网 | 清单强制 + 高危操作换模型复核 |
| Verify 幻觉核验 | 高危回复真实性核查 | 免费预检 + 付费交叉核验，通道故障自动降级放行 |
| Fallback 欠费降级 | 主力模型不可用时兜底 | 配合 Hermes 原生 `fallback_model`，本地 26B 模型优先、云端兜底 |
| Privacy 隐私路由 | 敏感内容处理提醒 | 命中敏感词后事后提醒，引导手动切到本地模型，同会话不重复提醒 |
| Version Check 版本核实 | 插件与 Hermes 版本兼容性 | 运行时自动比对，四种结果明确提示 |
| Checkpoint Reminder 存档点提醒 | 高危操作前提醒开启回滚保护 | 检测到高危操作且 Hermes 自带 checkpoint 功能未开启时事后提醒，引导手动开启 |
| Adaptive Approval 审批策略自适应 | 按历史批准记录动态调整确认频率 | 同类操作连续批准 3 次后不再重复确认，拒绝一次立即清零，永久高危类别不受信任影响 |
| Subagent Context 子任务风险继承 | 补子任务冷启动空窗期 | 委派子任务瞬间继承父会话当时的风险档位，子任务自己重新判定后再覆盖 |
| Webhook 审计外发 | 把风险信号推给外部系统 | 熔断跳闸/高危命令/幻觉核验/隐私提醒签名后 POST 到自配置端点，默认关闭 |
| Focus Mode 专注模式 | 专心干活时暂停高危确认提示 | 斜杠命令`/phoenix-focus`开关，CLI/桌面端通用，连续3次提示后自动建议一次 |
| Upgrade Watch 升级安全网 | Hermes升级后排查更容易 | 检测版本变化自动备份config.yaml，30分钟窗口内异常自动归档到`/phoenix-upgrade-log` |
| Context Watch 上下文体量提醒 | 上下文变大时提前预警 | prompt_tokens过粗粒度警戒线时事后提醒，建议开新会话，同会话仅提醒一次 |

338 个自动化测试全程跟着功能走，在没有旧 `.hermes` 目录的干净环境下也能跑（`HERMES_AGENT_SRC` 显式指定 hermes-agent 源码位置即可，见 `phoenix_v7/tests/conftest.py`）。完整技术拆解见 [不死鸟 Phoenix 完整技术文档](phoenix_v7/docs/)。

## 视觉总览

<img src="docs/images/01-router.png" alt="Router 路由分档" width="100%">

<img src="docs/images/02-guardrails.png" alt="Guardrails 风险防线" width="100%">

<img src="docs/images/04-selfheal.png" alt="Selfheal 自愈系统" width="100%">

<img src="docs/images/05-loopguard.png" alt="Loop Guard 长任务守护" width="100%">

<img src="docs/images/06-verify.png" alt="Verify 幻觉核验" width="100%">

<img src="docs/images/07-fallback.png" alt="Fallback 欠费降级" width="100%">

<img src="docs/images/09-checkpoint-reminder.png" alt="Checkpoint Reminder 存档点提醒" width="100%">

<img src="docs/images/10-adaptive-approval.png" alt="Adaptive Approval 审批策略自适应" width="100%">

<img src="docs/images/11-privacy.png" alt="Privacy 隐私路由" width="100%">

<img src="docs/images/12-local-model-setup.png" alt="本地模型配置指南" width="100%">

<img src="docs/images/08-comparison.png" alt="全景对比：纯 Hermes vs 不死鸟" width="100%">

## 安装

### 下载

⚠️ 请从 **[Releases](../../releases/latest)** 页面下载安装包（几百 KB，纯代码）。**不要**点仓库首页的绿色 "Code → Download ZIP" 按钮——那下载的是整个仓库源码（含展示图片等资源，十几 MB），不是安装包，装不了。

解压到任意位置后继续下面的步骤。

### macOS / Linux

```bash
cd 解压后的文件夹
bash install.sh
```

### Windows（PowerShell）

```powershell
cd 解压后的文件夹
.\install.ps1
```

默认执行**只复制文件、校验，不会自动改 Hermes 的插件启用状态**——干净安装完之后需要自己运行 `hermes plugins enable phoenix_v7` 并跑一遍 `hermes phoenix-status` 确认。已安装旧版本会自动备份，不会覆盖丢失。插件复制到的位置是 Hermes 的 Home 目录（macOS/Linux 默认 `~/.hermes/plugins/phoenix_v7/`，Windows 默认 `%LOCALAPPDATA%\hermes\plugins\phoenix_v7\`，设了 `HERMES_HOME` 环境变量的话以那个为准，可以用 `hermes config path` 查看当前实际路径）。

如果你是从旧版本（比如 `phoenix_full`）**切换**过来，用：

```powershell
.\install.ps1 -Migrate
```

这条路径会自动：备份旧插件代码、历史数据、Hermes 配置文件 → 生成 SHA-256 清单校验复制结果 → 禁用旧版本 → 启用 phoenix_v7 → 跑 `phoenix-status` 和最小烟测，确认全程只有一个 Phoenix 版本处于启用状态。**任何一步失败都会自动回滚**到迁移前的状态（旧插件、旧数据、旧启用状态全部恢复），不会留下"新旧混装"或"两边都不能用"的中间态。

> macOS/Linux 的 `install.sh` 目前还是老的"默认安装即自动启用"逻辑，`-Migrate` 这一套事务化切换 + 失败回滚暂时只有 Windows 版做了，后续会补齐。

### 卸载

```powershell
.\install.ps1 -Uninstall            # 删除插件代码 + 历史数据（抗体库、成本记录等）
.\install.ps1 -Uninstall -KeepState # 只删插件代码，保留历史数据
```

macOS/Linux 手动删除插件目录即可（路径同上）；只想清代码、保留数据的话，别删同一个 Home 目录下的 `phoenix_v7_state/` 目录。两种方式都不影响 Hermes 本体，也不会残留任何对 Hermes 核心文件的修改。

## 项目结构

```text
phoenix/
├── phoenix_v7/          # 插件本体，会被复制到 Hermes Home 下的 plugins/ 目录
│   ├── router/           # 路由分档引擎
│   ├── guardrails/        # 熔断器/审批闸/成本记账/审计外发/升级安全网/上下文提醒
│   ├── selfheal/          # 抗体库
│   ├── loop/              # 长任务守护信号
│   ├── verify/            # 幻觉核验
│   ├── privacy/            # 隐私敏感词检测与本地模型切换提醒
│   ├── tests/              # 338 个自动化测试
│   ├── docs/                # 使用指南
│   └── plugin.yaml          # 插件声明 + Hermes 版本兼容性字段
├── install.sh            # macOS / Linux 安装脚本
├── install.ps1            # Windows 安装脚本
└── LICENSE
```

## 为什么值得信任

- 338 条自动化测试全程跟着功能走，每次改动都要求全绿才能合并；在没有旧 `.hermes` 目录的干净环境下同样能跑
- 至少三次真实生产事故驱动了关键安全设计（详见完整技术文档）
- 两次重大重构都是先发现"自己重复造了 Hermes 已有的轮子"，再主动改用官方原生机制，不硬撑自建版本
- 发布前主动加了版本兼容性自检机制，不指望用户自己去猜"这个版本能不能用"

## 作者与支持

作者：**小爷** · 懂商业的 AI 野生 UP 主 / Hermes Agent·不死鸟 AI 架构原创作者

<img src="docs/wechat-qrcode.jpg" alt="微信二维码" width="240">

扫码添加微信，交流 Hermes 与不死鸟的使用问题或合作交流。

## 许可证

本项目采用 [CC BY-NC 4.0](LICENSE) 许可证。

- 个人使用、学习、研究与非商业项目可以直接使用。
- 公开发布衍生作品时，请注明来源。
- 商业用途需要单独授权，请联系作者。
