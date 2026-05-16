# AI 知识库助手 — Agent 协作规范

## 1. 项目概述

本项目是一个自动化 AI 技术动态采集与分发系统。Agent 从 GitHub Trending 和 Hacker News 采集 AI/LLM/Agent 领域的前沿技术动态，经大模型分析后结构化存储为 JSON 知识条目，最终通过 Telegram、飞书等多渠道进行内容分发，帮助用户及时跟踪 AI 领域最新趋势。

---

## 2. 技术栈

| 层级 | 技术 |
|------|------|
| 语言 | Python 3.12 |
| Agent 框架 | OpenCode + 国产大模型（DeepSeek / 通义千问 / 文心一言） |
| 工作流编排 | LangGraph |
| 数据采集 | OpenClaw（爬虫与 API 调度） |
| 数据存储 | JSON 文件（结构化知识条目） |
| 消息分发 | Telegram Bot API、飞书 Webhook |

---

## 3. 编码规范

### 3.1 通用规范
- 严格遵循 **PEP 8**
- 变量/函数使用 **snake_case**
- 类名使用 **PascalCase**
- 常量使用 **UPPER_SNAKE_CASE**
- 模块名使用小写，可含下划线

### 3.2 文档规范
- 所有公共函数必须使用 **Google 风格 docstring**
- 包含 Args、Returns、Raises（如适用）
- 示例：
  ```python
  def analyze_article(content: str, source: str) -> dict:
      """Analyze article content and extract structured knowledge.

      Args:
          content: Raw article text content.
          source: Source URL or identifier.

      Returns:
          Structured knowledge entry as a dictionary.

      Raises:
          ValueError: If content is empty or source is invalid.
      """
      ...
  ```

### 3.3 日志规范
- **禁止裸 `print()` 语句**（代码审查红线）
- 统一使用标准库 `logging`：
  ```python
  import logging
  logger = logging.getLogger(__name__)
  logger.info("Task completed: %s", task_id)
  ```
- 日志级别规范：
  - `DEBUG`：详细流程、变量状态
  - `INFO`：业务里程碑、成功完成
  - `WARNING`：可恢复异常、降级处理
  - `ERROR`：业务失败、需人工关注
  - `CRITICAL`：系统级故障、服务中断

---

## 4. 项目结构

```
ai-knowledge-base/
├── .opencode/
│   ├── agents/                 # Agent 角色定义与配置
│   │   ├── collector.yaml      # 采集 Agent 配置
│   │   ├── analyzer.yaml       # 分析 Agent 配置
│   │   └── curator.yaml        # 整理 Agent 配置
│   ├── skills/                 # 可复用技能模块
│   │   ├── web_scraper.py
│   │   ├── llm_analyzer.py
│   │   └── notifier.py
│   └── AGENTS.md               # 本文件
├── knowledge/
│   ├── raw/                    # 原始采集数据（HTML / Markdown / API 响应）
│   └── articles/               # 结构化知识条目（JSON 格式）
├── src/                        # 核心源码
├── tests/                      # 测试用例
├── pyproject.toml              # 项目依赖与配置
└── README.md
```

### 关键目录说明

| 目录 | 用途 |
|------|------|
| `.opencode/agents/` | Agent 角色配置：提示词模板、模型参数、工具绑定 |
| `.opencode/skills/` | 可复用技能：封装爬虫、分析、通知等原子能力 |
| `knowledge/raw/` | 原始数据缓存，按日期分区存储 |
| `knowledge/articles/` | 结构化知识条目，可直接供下游消费 |

---

## 5. 知识条目 JSON 格式

每条知识条目存储为独立 JSON 文件，命名规则：`{source}_{date}_{slug}.json`

### 5.1 字段定义

```json
{
  "id": "string (required, UUID v4)",
  "title": "string (required, 文章标题)",
  "source_url": "string (required, 原始 URL)",
  "source_platform": "string (required, 来源平台: github_trending | hackernews | ...)",
  "summary": "string (required, AI 生成的中文摘要, 200-500 字)",
  "tags": ["string (optional, AI 提取的标签数组, 如 [\"LLM\", \"Agent\", \"RAG\"])"],
  "author": "string (optional, 作者或仓库 owner)",
  "published_at": "string (required, ISO 8601 格式, 如 2024-01-15T08:30:00Z)",
  "collected_at": "string (required, ISO 8601 格式, 采集时间)",
  "status": "string (required, 状态: pending | analyzing | reviewed | published | archived)",
  "priority": "string (optional, 优先级: low | medium | high | critical)",
  "language": "string (optional, 原文语言: en | zh | ...)",
  "metrics": {
    "stars": "number (optional, GitHub stars 数量)",
    "forks": "number (optional, GitHub forks 数量)",
    "hn_score": "number (optional, HN 投票数)",
    "hn_comments": "number (optional, HN 评论数)"
  },
  "ai_analysis": {
    "key_insights": ["string (AI 提取的核心观点)"],
    "tech_category": "string (技术分类: model | infra | tool | application | research)",
    "audience": "string (目标受众: researcher | developer | product | general)"
  },
  "version": "number (required, 数据格式版本号, 当前为 1)"
}
```

### 5.2 状态流转

```
pending → analyzing → reviewed → published
  │          │          │
  └──────────┴──────────┴──→ archived
```

| 状态 | 说明 |
|------|------|
| `pending` | 刚采集，等待分析 |
| `analyzing` | 大模型正在分析中 |
| `reviewed` | 人工或 Agent 审核通过 |
| `published` | 已成功分发到各渠道 |
| `archived` | 已归档，不再分发 |

---

## 6. Agent 角色概览

| Agent | 职责 | 输入 | 输出 | 触发时机 |
|-------|------|------|------|----------|
| **采集 Agent (Collector)** | 从 GitHub Trending、Hacker News 等平台抓取原始数据 | 平台 URL / API | `knowledge/raw/` 下的原始文件 | 定时调度（每小时/每日）或手动触发 |
| **分析 Agent (Analyzer)** | 调用大模型分析原始内容，提取摘要、标签、核心观点 | `knowledge/raw/` 中的原始数据 | 结构化 JSON 知识条目（`knowledge/articles/`） | 新原始数据入库后自动触发 |
| **整理 Agent (Curator)** | 审核知识条目质量，决定分发策略，执行多渠道推送 | `knowledge/articles/` 中 `reviewed` 状态的条目 | Telegram / 飞书消息、状态更新为 `published` | 定时聚合推送或即时推送（高优先级） |

### 6.1 协作流程

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────────┐
│   Source    │────▶│  Collector   │────▶│   Analyzer  │────▶│   Curator    │
│(GitHub/HN)  │     │   (采集)     │     │   (分析)    │     │   (整理分发) │
└─────────────┘     └──────────────┘     └─────────────┘     └──────────────┘
                                                          │
                                                          ▼
                                              ┌─────────────────────┐
                                              │ Telegram / 飞书 / ...│
                                              └─────────────────────┘
```

---

## 7. 红线（绝对禁止的操作）

以下行为在代码审查和 Agent 执行中 **绝对禁止**：

### 7.1 代码层面
1. **禁止裸 `print()`** —— 必须使用 `logging` 模块
2. **禁止提交 API Key / Token** —— 全部使用环境变量或密钥管理服务
3. **禁止硬编码配置** —— 平台 URL、超时时间等必须可配置
4. **禁止无异常处理的网络请求** —— 必须捕获超时、连接错误、HTTP 错误码
5. **禁止在循环中无节制调用大模型 API** —— 必须实现速率限制（Rate Limiting）和熔断机制

### 7.2 数据层面
6. **禁止覆盖已发布的知识条目** —— 已发布（`published`）条目不可修改，只能创建新版本
7. **禁止采集非公开/敏感数据** —— 仅限公开平台数据，禁止爬取需要授权的内容
8. **禁止在 JSON 中存储原始 HTML** —— 原始 HTML 仅存于 `knowledge/raw/`，JSON 中只存纯文本摘要

### 7.3 运维层面
9. **禁止在生产环境直接修改 `knowledge/articles/` 中的文件** —— 必须通过 Agent 工作流
10. **禁止无版本控制的配置变更** —— Agent 配置变更必须提交到 Git

---

## 附录：环境变量清单

| 变量名 | 说明 | 是否必填 |
|--------|------|----------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | 条件必填（至少配置一个大模型） |
| `QWEN_API_KEY` | 通义千问 API 密钥 | 条件必填 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | 如需 Telegram 推送 |
| `FEISHU_WEBHOOK_URL` | 飞书 Webhook 地址 | 如需飞书推送 |
| `GITHUB_TOKEN` | GitHub Personal Access Token | 如需提高 API 限流 |
| `RAW_DATA_RETENTION_DAYS` | 原始数据保留天数（默认 30） | 否 |
| `LOG_LEVEL` | 日志级别（默认 INFO） | 否 |

---

> 本文档由项目初始化 Agent 生成，后续修改请通过 Pull Request 进行。
