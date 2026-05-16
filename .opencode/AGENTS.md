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
│   ├── articles/               # 结构化知识条目（JSON 格式）
│   ├── dead_letter/            # 多次处理失败的知识条目（死信队列）
│   │   ├── {source}_{date}_{slug}.json
│   │   └── _meta.json          # 死信队列元数据（失败原因、重试次数、进入时间）
│   └── archive/                # 归档数据
│       ├── raw/                # 超过保留期的原始数据
│       └── dead_letter/        # 超过保留期的死信数据
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
| `knowledge/dead_letter/` | 多次处理失败的知识条目，等待人工修复 |
| `knowledge/archive/` | 超过保留期的数据归档，压缩存储 |

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
  "retry_count": "number (optional, 当前重试次数, 默认 0)",
  "last_error": "string (optional, 最后一次失败的错误类型)",
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
                    ┌─────────────────────────────────────┐
                    │           处理成功                   │
                    ▼                                     │
pending ──► analyzing ──► reviewed ──► published        │
   ▲          │                              │            │
   │          │ 失败（未达最大重试次数）        │            │
   │          └────────────┬───────────────────┘            │
   │                       │                                │
   │                       │ 达到最大重试次数                │
   │                       ▼                                │
   │                 dead_letter                             │
   │                       │                                │
   │                       │ 人工修复后                     │
   └───────────────────────┘                                │
                                                            │
   ┌────────────────────────────────────────────────────────┘
   │
   └─► archived（手动触发或自动清理）
```

| 状态 | 说明 |
|------|------|
| `pending` | 刚采集或重试排队，等待分析 |
| `analyzing` | 大模型正在分析中 |
| `reviewed` | 人工或 Agent 审核通过 |
| `published` | 已成功分发到各渠道 |
| `archived` | 已归档，不再分发 |
| `dead_letter` | 多次处理失败，隔离到单独队列等待人工修复 |

### 5.3 Priority 策略

Priority 采用**两阶段决定**机制：

**阶段一：采集阶段（Collector）—— 基于硬规则初筛**

| 规则 | 触发条件 | Priority |
|------|----------|----------|
| GitHub 爆发式增长 | stars > 1000 且日增 > 500 | `high` |
| HN 热门 | score > 100 或 comments > 50 | `high` |
| 安全相关关键词 | 标题/描述匹配 `CVE`, `security`, `vulnerability`, `exploit` | `critical` |
| 重大更新关键词 | 标题/描述匹配 `breaking change`, `deprecated`, `major release` | `high` |
| 默认 | 不满足以上规则 | `medium` |

**阶段二：分析阶段（Analyzer）—— 基于内容质量精筛**

Analyzer 调用大模型分析内容后，可调整 Priority：

| 调整方向 | 触发条件 |
|----------|----------|
| 提升为 `critical` | 涉及重大安全漏洞、核心基础设施变更、主流框架大版本发布 |
| 提升为 `high` | 具有广泛影响力的技术突破或新范式 |
| 降为 `low` | Hello World 级别示例、个人博客随笔、营销软文 |
| 保持 | 常规技术更新、工具发布 |

**关键规则**：如果 Analyzer 将 priority 从 `medium` 提升为 `critical` 或 `high`，且该条目已经自动通过审核（进入 `reviewed`），系统必须**回溯审核策略**——将该条目从 `reviewed` 状态回退到 `analyzing`，等待人工审核。

### 5.4 审核策略

| Priority | 审核方式 | 目标耗时 |
|----------|----------|----------|
| `critical` | **强制人工审核** | < 5 分钟 |
| `high` | **自动审核 + 人工抽检**（每 10 条抽 1 条） | < 10 分钟 |
| `medium` | **全自动审核** | < 30 分钟 |
| `low` | **全自动审核 + 延迟处理**（低峰期批量处理） | < 2 小时 |

**Curator Agent 自动审核通过标准（Checklist）**：

1. ✅ JSON Schema 验证通过（所有必填字段非空，类型正确）
2. ✅ `summary` 长度在 200-500 字之间
3. ✅ `tags` 数量在 1-5 个之间，无重复
4. ✅ `ai_analysis.tech_category` 和 `ai_analysis.audience` 在枚举范围内
5. ✅ 不包含明显违规内容（通过关键词过滤列表）
6. ✅ `source_url` 可访问（HTTP 200）
7. ✅ 与已发布条目去重（标题相似度 < 85%）

**自动审核失败处理**：
- 首次失败：更新 `last_error`，`retry_count + 1`，回到 `pending`，按指数退避策略延迟重试
- 达到最大重试次数（3 次）：移入 `knowledge/dead_letter/`，触发聚合告警通知

---

## 6. Agent 角色概览

| Agent | 职责 | 输入 | 输出 | 触发时机 |
|-------|------|------|------|----------|
| **采集 Agent (Collector)** | 从 GitHub Trending、Hacker News 等平台抓取原始数据，按规则初筛 Priority | 平台 URL / API | `knowledge/raw/` 下的原始文件 + 带 priority 的待处理条目 | 定时调度（每小时/每日）或手动触发 |
| **分析 Agent (Analyzer)** | 调用大模型分析原始内容，提取摘要、标签、核心观点，精筛 Priority | `knowledge/raw/` 中的原始数据 | 结构化 JSON 知识条目（`knowledge/articles/`） | 新原始数据入库后自动触发 |
| **整理 Agent (Curator)** | 审核知识条目质量（自动 checklist + 人工策略），决定分发策略，执行多渠道推送 | `knowledge/articles/` 中 `reviewed` 状态的条目 | Telegram / 飞书消息、状态更新为 `published` | 即时推送（critical/high）或定时聚合推送（medium/low） |

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

### 6.2 通知策略

**告警聚合原则**：避免单条失败即触发通知造成告警疲劳。

| 通知类型 | 触发条件 | 聚合策略 | 通知渠道 |
|----------|----------|----------|----------|
| 死信队列告警 | 条目进入 `dead_letter` | 每 5 分钟或累计 10 条失败聚合发送一次，包含失败原因分类统计 | Telegram + 飞书 |
| 审核召回通知 | Analyzer 提升 priority 导致已审核条目需回溯 | 即时单条通知 | Telegram + 飞书 |
| 系统错误 | 速率限制、API 连续失败、存储异常 | 即时通知，5 分钟内同类错误只发一次 | Telegram + 飞书 |
| 日报 | 每日处理统计 | 每日固定时间（如 09:00）发送 | 飞书 |

**通知内容格式**：
```
🚨 死信队列告警（最近 5 分钟）
━━━━━━━━━━━━━━━━━━━━
总计：12 条
├─ parse_error: 5 条
├─ llm_timeout: 4 条
├─ llm_rate_limit: 2 条
└─ schema_mismatch: 1 条

查看：knowledge/dead_letter/
```

---

## 7. 可靠性设计

### 7.1 失败分类与重试策略

| 错误类型 | 说明 | 重试策略 | 最大重试次数 |
|----------|------|----------|--------------|
| `parse_error` | HTML/JSON 解析失败 | 指数退避（1min → 2min → 4min） | 3 次 |
| `llm_timeout` | 大模型 API 超时 | 指数退避（30s → 1min → 2min） | 3 次 |
| `llm_rate_limit` | 速率限制 | 指数退避（1min → 2min → 4min） | 3 次 |
| `schema_mismatch` | 输出不符合 JSON Schema | 立即重试（可能模型输出格式不稳定） | 3 次 |
| `content_filter` | 内容被模型安全过滤 | **不重试**，直接归档（内容本身有问题） | 0 次 |
| `network_error` | 网络连接错误 | 指数退避（10s → 20s → 40s） | 3 次 |

**指数退避公式**：`delay = base_delay × 2^retry_count + random_jitter(0, 30s)`

### 7.2 死信队列（Dead Letter Queue）

**进入条件**：`retry_count >= 3` 且最后一次重试仍失败。

**处理流程**：
1. 将失败条目从 `knowledge/articles/` 移入 `knowledge/dead_letter/`
2. 更新 `_meta.json`，记录失败原因、重试历史、进入时间
3. 触发聚合告警通知（见 6.2 通知策略）
4. 人工审查并修复后，更新 `fixed_at` 和 `fix_reason`，移回 `pending` 重新处理

**修复规范**：
- 在死信队列中原地修改 JSON，不要重新采集（原始数据可能已变化）
- 修复后必须填写 `fix_reason`，便于后续统计和优化
- 如果无法修复（如源内容已删除），标记为 `archived`

### 7.3 熔断机制

当某个外部服务（如 DeepSeek API、GitHub API）连续失败率达到阈值时，触发熔断：

| 服务 | 熔断阈值 | 熔断后行为 |
|------|----------|------------|
| 大模型 API | 5 分钟内失败率 > 50% | 暂停调用 2 分钟，切换到备用模型 |
| GitHub API | 1 分钟内失败率 > 30% | 暂停调用 5 分钟，降级到缓存数据 |
| HN API | 1 分钟内失败率 > 30% | 暂停调用 5 分钟，降级到缓存数据 |

---

## 8. 数据生命周期

### 8.1 保留策略

| 数据类型 | 存储位置 | 保留期 | 过期后处理 |
|----------|----------|--------|------------|
| 原始采集数据 | `knowledge/raw/` | 30 天 | 压缩归档到 `knowledge/archive/raw/` |
| 已发布知识条目 | `knowledge/articles/` | **永久** | 不可删除，版本化更新 |
| 死信队列 | `knowledge/dead_letter/` | 30 天 | 压缩归档到 `knowledge/archive/dead_letter/` |
| 归档数据 | `knowledge/archive/` | 1 年 | 自动清理 |

### 8.2 版本控制

- 已发布（`published`）条目**不可原地修改**
- 如需更新，创建新版本（`version + 1`），新文件命名为 `{source}_{date}_{slug}_v{version}.json`
- 旧版本保持 `published` 状态，新版本从 `pending` 开始重新流转
- 版本更新必须在 `changelog` 字段说明变更原因

---

## 9. 红线（绝对禁止的操作）

以下行为在代码审查和 Agent 执行中 **绝对禁止**：

### 9.1 代码层面
1. **禁止裸 `print()`** —— 必须使用 `logging` 模块
2. **禁止提交 API Key / Token** —— 全部使用环境变量或密钥管理服务
3. **禁止硬编码配置** —— 平台 URL、超时时间、重试次数等必须可配置
4. **禁止无异常处理的网络请求** —— 必须捕获超时、连接错误、HTTP 错误码
5. **禁止在循环中无节制调用大模型 API** —— 必须实现速率限制（Rate Limiting）和熔断机制

### 9.2 数据层面
6. **禁止覆盖已发布的知识条目** —— 已发布（`published`）条目不可修改，只能创建新版本
7. **禁止采集非公开/敏感数据** —— 仅限公开平台数据，禁止爬取需要授权的内容
8. **禁止在 JSON 中存储原始 HTML** —— 原始 HTML 仅存于 `knowledge/raw/`，JSON 中只存纯文本摘要
9. **禁止删除死信队列中的 `_meta.json`** —— 元数据是审计和统计的依据

### 9.3 运维层面
10. **禁止在生产环境直接修改 `knowledge/articles/` 中的文件** —— 必须通过 Agent 工作流
11. **禁止无版本控制的配置变更** —— Agent 配置变更必须提交到 Git
12. **禁止跳过审核流程发布 critical 条目** —— critical 必须人工审核

---

## 附录：环境变量清单

| 变量名 | 说明 | 是否必填 | 默认值 |
|--------|------|----------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | 条件必填（至少配置一个大模型） | - |
| `QWEN_API_KEY` | 通义千问 API 密钥 | 条件必填 | - |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | 如需 Telegram 推送 | - |
| `FEISHU_WEBHOOK_URL` | 飞书 Webhook 地址 | 如需飞书推送 | - |
| `GITHUB_TOKEN` | GitHub Personal Access Token | 如需提高 API 限流 | - |
| `RAW_DATA_RETENTION_DAYS` | 原始数据保留天数 | 否 | 30 |
| `DEAD_LETTER_RETENTION_DAYS` | 死信队列保留天数 | 否 | 30 |
| `MAX_RETRY_COUNT` | 最大重试次数 | 否 | 3 |
| `LOG_LEVEL` | 日志级别 | 否 | INFO |
| `NOTIFICATION_AGGREGATION_WINDOW_SECONDS` | 通知聚合窗口（秒） | 否 | 300 |

---

> 本文档由项目初始化 Agent 生成，经审查和优化后定稿。后续修改请通过 Pull Request 进行。
