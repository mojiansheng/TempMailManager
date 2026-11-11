# TempMail Manager 临时邮箱管理

本地自托管的 [onetimeemail.com](https://onetimeemail.com) 临时邮箱管理工具：一键创建可选有效期（10 分钟 ~ 30 天）的临时邮箱、多级分组管理、每日自动续期、收信与邮件内容查看、批量导入/导出，全部数据保存在本地 SQLite，不经过任何第三方服务。

![主界面](screenshots/main.png)

## 功能特性

- 📬 **邮箱管理** — 新建时可选有效期（10 分钟 / 30 分钟 / 1 小时 / 3 小时 / 6 小时 / 24 小时 / 3 天 / 7 天 / 15 天 / 30 天，默认 30 天，选择会被记住），支持备注、手动续期（可选续到多久，默认保持当前有效期）、自动续期开关
- 🔔 **未读提醒** — 邮箱卡片显示未读数量，点开邮件即自动标记已读并实时更新角标
- 🌳 **多级分组** — 无限层级分组树，展开箭头清晰可点，未分组视图；**分组可拖动排序，也能直接拖进另一个分组下**
- 🖱️ **拖动排序** — 分组树拖到目标行中间即「放入其下」，拖到上下边缘即同级排序；邮箱卡片可在列表内拖动排序
- 🎯 **邮箱拖进分组** — 把邮箱卡片直接拖到左侧任意分组上即可移入，拖到「未分组」即移出；拖已勾选的卡片会整批移动
- ☑️ **批量管理** — 邮箱区右上角一键进入管理模式，勾选多个邮箱后统一「移入分组」，分组下拉带层级缩进
- 🔄 **自动续期** — 内置调度器按「每 N 小时」或「每天 HH:MM」巡检，续期时长可选具体档位或「保持各邮箱当前有效期」；首次启动不抢跑，等满间隔再开始
- 📥 **批量导入** — 支持粘贴文本 / 文本文件 / Excel（xlsx）三种方式批量导入已有账户
- 📤 **批量导出** — 一键导出全部邮箱（含 uuid / 助记词 / cookies）为 Excel
- 📧 **收信查看** — 沙箱化 iframe 渲染邮件 HTML，放大查看，点击外链安全跳转
- 📋 **日志中心** — 业务 / 系统 / 前端请求 / 外部 HTTP 四通道日志全部入库，可搜索、脱敏展示
- 🗄️ **自动迁移** — 数据库结构版本化（`schema_version`），启动时自动升级老库，不影响已有数据

## 界面一览

| 邮件详情 | 新建分组弹窗 |
|---|---|
| ![邮件详情](screenshots/email.png) | ![新建分组](screenshots/rename.png) |

| 批量管理（勾选后移入分组） | 日志中心 |
|---|---|
| ![批量管理](screenshots/manage.png) | ![日志中心](screenshots/logs.png) |

## 下载安装（Windows）

不想装 Python，直接下打包好的单文件 exe：

- 最新版：[Releases](https://github.com/mojiansheng/TempMailManager/releases/latest)（当前 v1.1.0）
- 文件名：`TempMailManager-v1.1.0-win64.exe`，双击运行后自动打开 <http://127.0.0.1:8720/>
- 数据保存在 exe 同级的 `data/tempmail.db`；升级只需替换 exe，数据库会在启动时自动升级结构，建议先备份 `data/`
- 首次运行若被 SmartScreen 拦截，点「更多信息 → 仍要运行」（exe 未做代码签名）
- 每个版本改了什么见 [Releases 说明](https://github.com/mojiansheng/TempMailManager/releases)
  （exe 未进仓库，作为 Release 附件上传）

仅提供 Windows x64 单文件版；Linux / macOS 请用下方源码方式运行。

## 快速开始

### 源码运行

```bash
python -m pip install -r requirements.txt
python run.py          # 或双击 start.bat
```

浏览器打开 <http://127.0.0.1:8720/>

### 打包为单文件 exe（Windows）

```bash
python build.py                # 单文件 exe（需要 Nuitka）
python build.py --standalone   # 目录模式，启动更快
```

## 配置

环境变量（均有默认值，可不配置）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `TEMPMAIL_HOST` | `127.0.0.1` | 监听地址 |
| `TEMPMAIL_PORT` | `8720` | 监听端口 |
| `TEMPMAIL_DATA_DIR` | `./data` | 数据目录（SQLite 所在地） |
| `TEMPMAIL_DEBUG` | `0` | 调试模式 |

## 数据库结构版本

应用启动时自动检查并升级数据库结构（见 `app/migrations.py`），也可手动执行：

```bash
python -m app.migrations            # 升级默认库
python -m app.migrations path/to/db # 升级指定库（已最新时提示「无需升级」）
```

- **v1** — 分组 / 邮箱新增 `sort_order` 列（拖动排序），老数据按 id 顺序回填，原数据不受影响
- 升级前自动整库备份为 `data/tempmail.db.bak-v<旧版本>`，备份成功才改结构；
  控制台、「运行日志」以及**页面顶部的提示条**都会告诉你升了什么、备份在哪
- 全新安装直接是最新结构（不产生备份）；重复启动不会重复升级；用旧版程序打开新库不会被降级
- 回滚：关掉程序，把 `tempmail.db.bak-v0` 改回 `tempmail.db`（同时删掉 `-wal` / `-shm`）

## 项目结构

```
app/
├── run.py               # 入口：启动服务并打开浏览器
├── build.py             # Nuitka 打包脚本
├── app/
│   ├── migrations.py    # 数据库结构版本化迁移
│   ├── database.py      # SQLite 连接与建表
│   ├── store.py         # 数据访问层
│   ├── routes/          # REST 接口（mailboxes/groups/emails/jobs/settings）
│   ├── services/        # 业务层（站点客户端/导入导出/续期调度/批量任务）
│   └── static/          # 前端（原生 HTML/CSS/JS 单页应用）
└── data/tempmail.db     # 运行时生成
```

## 技术栈

- 后端：Python 3.10+ / Flask / SQLite（WAL）
- 前端：原生 HTML/CSS/JS，无构建依赖
- 打包：Nuitka

## License

MIT
