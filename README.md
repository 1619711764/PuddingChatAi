# 🍮 PuddingChat AI

> 多用户 AI 聊天助手，搭载风格蒸馏人格引擎 | FastAPI + DeepSeek + SQLite

[![Version](https://img.shields.io/badge/version-2.0.0-blue)](https://github.com/1619711764/PuddingChatAi)
[![Python](https://img.shields.io/badge/python-3.11+-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-orange)](LICENSE)

---

## ✨ 特性

- 🔐 **多用户系统** — 邮箱注册登录，bcrypt + JWT 双 Token，数据完全隔离
- 🎭 **AI 人格引擎** — 风格蒸馏技术，从对话中自动学习用户风格，生成专属 AI 人格
- 👥 **4 种预设人格** — 布丁(毒舌吐槽) /无过滤 / 文档助手
- 💬 **流式对话** — SSE 逐 Token 输出，支持中途停止生成
- 📋 **管理面板** — 用户列表、IP 归属地、统计数据、对话记录查看
- 📱 **响应式 UI** — 纯原生 HTML/CSS/JS，系统字体栈，国内网络秒开
- 🌐 **公网隧道** — 内置 serveo/ngrok 双隧道，开箱即用

---

## 🚀 快速开始

### 环境要求

- Python >= 3.11
- DeepSeek API Key

### 安装

```bash
git clone https://github.com/1619711764/PuddingChatAi.git
cd PuddingChatAi
pip install -r requirements.txt
```

### 配置

编辑 `.env` 或直接设置环境变量：

```env
DEEPSEEK_API_KEY=sk-your-key
JWT_SECRET_KEY=your-secret-key-change-me
DATABASE_URL=sqlite:///data/chat.db
```

### 启动

```bash
python api/main.py
```

访问 `http://localhost:8004`

---

## 📖 使用指南

### Web 界面

| 页面 | 地址 | 说明 |
|------|------|------|
| 聊天界面 | `/` | 主界面，登录后使用 |
| 登录注册 | `/login` | 邮箱注册 + 登录 |
| 管理面板 | `/admin` | 密钥: `pudding-admin-2026` |

### 功能操作

1. **注册账号** → 使用邮箱注册登录
2. **选择人格** → 点击顶部胶囊按钮切换 AI 性格
3. **开始聊天** → 流式输出，支持 Markdown 和代码高亮
4. **管理面板** → `/admin` 查看用户统计和对话记录

---

## 🏗️ 项目结构

```
PuddingChatAi/
├── api/
│   ├── main.py              # FastAPI 入口 + CORS
│   ├── middleware/
│   │   └── auth.py          # JWT 认证中间件
│   └── routes/
│       ├── auth.py           # 注册/登录/Refresh/头像
│       ├── chat.py           # 对话 API + SSE 流式
│       ├── persona.py        # 人格管理 + 蒸馏触发
│       ├── admin.py          # 管理面板 API
│       ├── memory.py         # 用户记忆 API
│       └── wechat_routes.py  # 微信扫码 (待启用)
├── core/
│   ├── config.py             # 配置管理
│   ├── database.py           # SQLite 数据库
│   ├── llm_client.py         # DeepSeek API 客户端
│   ├── persona.py            # 人格引擎 + 风格蒸馏
│   └── memory.py             # 用户对话记忆
├── static/
│   ├── index.html            # 聊天界面
│   ├── login.html            # 登录注册页
│   └── admin.html            # 管理面板
├── adapters/
│   └── wechat.py             # 微信扫码适配器
└── requirements.txt
```

---

## 🔧 API 接口

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 邮箱注册 |
| POST | `/api/auth/login` | 登录获取 Token |
| POST | `/api/auth/refresh` | 刷新 Token |
| POST | `/api/auth/avatar` | 上传头像 |

### 对话

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat/send` | 发送消息 (SSE 流式) |
| GET | `/api/chat/history` | 获取对话列表 |
| GET | `/api/chat/conversation/{id}` | 获取对话消息 |
| DELETE | `/api/chat/conversation/{id}` | 删除对话 |

### 人格

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/persona/list` | 获取人格列表 |
| POST | `/api/persona/select` | 切换人格 |
| POST | `/api/persona/distill` | 触发风格蒸馏 |

---

## 🎭 人格系统

### 风格蒸馏原理

```
用户对话 → 收集 15 条消息 → LLM 分析风格特征 → 炼丹？
                                ↓
                          更新人格 Prompt
                                ↓
                    下次对话带上新人格 🤖✨
```

### 预设人格

| 人格 | 风格 | 适用场景 |
|------|------|---------|
| 🍮 布丁 (默认) | 毒舌、专业、犀利吐槽 | 日常聊天 |
| 💕 男朋友 | 温柔、体贴、鼓励 | 肆月专属 |
| 🔓 无过滤 | 直接、不加修饰 | 技术问答 |
| 📚 文档助手 | 严谨、结构化 | 文档编写 |

---

## 📊 管理面板

访问 `/admin`，密钥 `pudding-admin-2026`

功能：
- 用户列表 (邮箱、IP、注册时间、登录时间)
- 统计数据 (用户数、对话数、消息数)
- 对话记录查看 (选择用户 → 查看完整对话 → 分页浏览)
- 用户删除 (级联删除所有数据)

---

## 🌐 公网访问

```bash
# serveo (推荐，无拦截页)
ssh -R 80:localhost:8004 serveo.net

# ngrok (备用)
ngrok http 8004
```

---

## 🛠️ 技术栈

- **后端**: FastAPI (异步) + SQLite
- **AI**: DeepSeek API (OpenAI 兼容)
- **认证**: bcrypt + JWT (access + refresh)
- **前端**: 原生 HTML/CSS/JS，零框架
- **隧道**: serveo + ngrok

---

## 📄 License

MIT

---

> 🍮 *"你这个需求…挺简单的嘛"* — 布丁
