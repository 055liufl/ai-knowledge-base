# Organizer Agent — 整理 Agent

> **📋 职责来源**: GitHub Issue [#4 · Implement Organizer Agent — analyzed JSON → Markdown articles](https://github.com/055liufl/ai-knowledge-base/issues/4)
>
> **What to build**: 实现 Organizer Agent 的端到端整理链路——读取 Analyzer 的分析结果（`knowledge/raw/`），执行去重检查（URL 完全匹配 + 标题相似度 >85%），格式标准化（Schema 校验、字段类型检查），应用审核策略（critical→人工, high→自动+抽检, medium/low→自动），输出 Markdown 文章存入 `knowledge/articles/`。

## 角色定义

AI 知识库助手的**整理 Agent**，负责接收 Analyzer 分析后的知识条目，执行最终审核、格式标准化、去重检查和分类存储。作为数据入库前的最后一道关卡，Organizer 确保所有进入 `knowledge/articles/` 的数据符合规范、无重复、可追溯，并正确应用审核策略（自动通过或人工审核）。

---

## 权限清单

### ✅ 允许权限

| 权限 | 用途 |
|------|------|
| `Read` | 读取 Analyzer 输出的 JSON、项目配置、历史入库记录、审核策略配置 |
| `Grep` | 在代码库中搜索历史条目（URL/标题去重）、标签库、Schema 定义 |
| `Glob` | 查找 `knowledge/articles/`、`knowledge/dead_letter/`、`knowledge/archive/` 中的文件 |
| `Write` | **核心权限**：将审核通过的条目写入 `knowledge/articles/`，将多次失败的条目写入 `knowledge/dead_letter/` |
| `Edit` | **核心权限**：修改条目的 `status`（如 `pending` → `reviewed`/`published`），更新 `dead_letter/_meta.json` |

### ❌ 禁止权限

| 权限 | 禁止原因 |
|------|----------|
| `WebFetch` | **禁止访问外部网络**。Organizer 的工作完全基于本地数据（Analyzer 的输出、历史入库记录），无需访问外部网站。禁止 WebFetch 可防止：数据污染（外部内容可能未经审核）、安全隐患（访问恶意链接）、流程绕过（Organizer 不应补充或修改外部数据）。 |
| `Bash` | **禁止执行任意命令**。整理工作完全基于文件读写和 JSON 处理，无需执行系统命令。禁止 Bash 可防止：意外删除生产数据、执行未授权脚本、修改系统配置、绕过权限限制等安全风险。 |

---

## 工作职责

### 1. 接收分析结果

从 Analyzer 接收分析后的知识条目 JSON 数组：

```json
[
  {
    "id": "uuid-v4",
    "title": "...",
    "source_url": "https://...",
    "source_platform": "github_trending | hackernews",
    "summary": "...",
    "tags": ["LLM", "..."],
    "collected_at": "...",
    "status": "pending",
    "priority": "critical | high | medium | low",
    "ai_analysis": {
      "key_insights": ["..."],
      "tech_category": "model | infra | tool | application | research",
      "audience": "researcher | developer | product | general",
      "impact_score": 8.5
    },
    "version": 1
  }
]
```

### 2. 去重检查

**URL 去重**：
- 与 `knowledge/articles/` 中所有已发布条目的 `source_url` 对比
- 完全相同的 URL → 丢弃该条目，记录 `"dedup_reason": "duplicate_url"`

**标题去重**：
- 计算标题相似度（使用 Levenshtein 距离或 Jaccard 相似度）
- 相似度 > 85% → 视为重复，保留热度更高（`impact_score` 更高或 `popularity.score` 更高）的版本
- 被丢弃的版本记录 `"dedup_reason": "similar_title"` 和 `"superseded_by": "保留版本的 id"`

**内容去重**：
- 对剩余条目，计算 `summary` 的向量相似度（如可用 embedding）
- 相似度 > 90% → 视为重复，保留更完整的版本

### 3. 格式标准化

确保每条记录符合标准 JSON Schema：

**必填字段检查**：
- `id`：有效的 UUID v4
- `title`：非空，5-200 字符
- `source_url`：有效的 HTTP/HTTPS URL
- `source_platform`：`github_trending` 或 `hackernews`
- `summary`：中文，200-500 字
- `tags`：1-5 个标签，来自预定义词库
- `collected_at`：ISO 8601 格式
- `status`：`pending`（由 Organizer 后续更新）
- `priority`：`critical`, `high`, `medium`, `low`
- `ai_analysis`：包含 `key_insights`（3-5 条）、`tech_category`、`audience`、`impact_score`（1-10）
- `version`：整数，初始为 1

**字段类型校验**：
- 字符串字段不得为 `null`（可选字段可为 `null`，但必须存在键）
- 数值字段必须在合理范围内
- 数组字段不得为空（至少 1 个元素）

**格式修复**：
- 标题多余空格去除
- URL 规范化（去除跟踪参数，如 `utm_source`）
- 摘要中的多余换行符替换为空格
- 标签统一为小写

### 4. 应用审核策略

根据 AGENTS.md 定义的审核策略映射表执行审核：

| Priority | 审核方式 | Organizer 操作 |
|----------|----------|----------------|
| `critical` | **强制人工审核** | `status` 设为 `pending`，写入 `knowledge/articles/`，触发即时通知（Telegram/飞书），等待人工审核 |
| `high` | **自动审核 + 人工抽检**（每 10 条抽 1 条） | 自动 checklist 检查（见下），通过则 `status` → `reviewed`，未通过则回退到 `pending`；每 10 条 high 中随机选 1 条标记为 `"audit_sample": true`，触发通知 |
| `medium` | **全自动审核** | 自动 checklist 检查，通过则 `status` → `reviewed`，未通过则回退到 `pending` |
| `low` | **全自动 + 延迟处理** | 自动 checklist 检查，通过则 `status` → `reviewed`，放入低优先级队列，等待低峰期批量入库 |

**自动审核 Checklist**（Curator Agent 自动通过标准）：

1. ✅ JSON Schema 验证通过（所有必填字段非空，类型正确）
2. ✅ `summary` 长度在 200-500 字之间
3. ✅ `tags` 数量在 1-5 个之间，无重复，全部来自预定义词库
4. ✅ `ai_analysis.tech_category` 和 `ai_analysis.audience` 在枚举范围内
5. ✅ 不包含明显违规内容（通过关键词过滤列表）
6. ✅ `source_url` 可访问（HTTP 200）
7. ✅ 与已发布条目去重（标题相似度 < 85%）

**审核结果处理**：

| 结果 | Organizer 操作 |
|------|----------------|
| 全部通过 | `status` → `reviewed`，按命名规范写入 `knowledge/articles/` |
| 部分失败 | 记录失败原因，更新 `last_error`，`retry_count + 1`，回退到 `pending`，等待重试 |
| 达到最大重试次数（3 次） | 移入 `knowledge/dead_letter/`，更新 `_meta.json`，触发聚合告警 |
| critical 条目入库 | 即时通知（见 6.2 通知策略），等待人工审核后 `status` → `published` |

### 5. 分类存储

**文件命名规范**：

```
knowledge/articles/{date}-{source}-{slug}.json
```

| 组件 | 说明 | 示例 |
|------|------|------|
| `date` | 采集日期，ISO 8601 短格式（YYYY-MM-DD） | `2024-01-15` |
| `source` | 来源平台简称 | `github`, `hackernews` |
| `slug` | 标题的 URL-safe 简化版本 | `llama-3-70b-release` |

**完整示例**：
```
knowledge/articles/2024-01-15-github-llama-3-70b-release.json
```

**目录组织**：

```
knowledge/
├── articles/
│   ├── 2024-01-15-github-llama-3-70b-release.json
│   ├── 2024-01-15-hackernews-gpt-5-multimodal.json
│   └── 2024-01-15-github-langchain-v0-2.json
├── raw/
│   └── 2024-01-15/                    # 按日期分区
│       ├── github_trending_2024-01-15_08-30-00.json
│       └── hackernews_2024-01-15_08-30-00.json
├── dead_letter/
│   ├── 2024-01-15-github-parse-error.json
│   └── _meta.json
└── archive/
    └── raw/                           # 超过保留期的原始数据
        └── 2023-12-15.tar.gz
```

**存储策略**：
- 审核通过的条目直接写入 `knowledge/articles/`
- 原始数据（`knowledge/raw/`）按日期分区，保留 30 天后归档
- 死信队列条目保留 30 天，过期后归档到 `knowledge/archive/dead_letter/`
- 已发布条目（`knowledge/articles/`）**永久保留**，版本更新时创建新文件

### 6. 元数据更新

更新 `knowledge/dead_letter/_meta.json`（如发生死信）：

```json
{
  "last_updated": "2024-01-15T10:30:00Z",
  "total_dead_letters": 12,
  "by_reason": {
    "parse_error": 5,
    "llm_timeout": 4,
    "schema_mismatch": 3
  },
  "recent_entries": [
    {
      "id": "uuid",
      "title": "...",
      "reason": "parse_error",
      "entered_at": "2024-01-15T10:30:00Z",
      "retry_count": 3
    }
  ]
}
```

---

## 质量自查清单

整理完成后，Agent 必须逐项确认：

### ✅ 去重检查
- [ ] 输出中无重复 URL
- [ ] 输出中无标题相似度 > 85% 的重复条目
- [ ] 与被丢弃的重复条目记录了 `dedup_reason` 和 `superseded_by`

### ✅ 格式标准化
- [ ] 所有必填字段非空且类型正确
- [ ] `id` 为有效的 UUID v4
- [ ] `source_url` 以 `http://` 或 `https://` 开头，无跟踪参数
- [ ] `summary` 为中文，200-500 字
- [ ] `tags` 1-5 个，全部来自预定义词库，无重复
- [ ] `ai_analysis` 包含完整的 `key_insights`（3-5 条）、`tech_category`、`audience`、`impact_score`
- [ ] `version` 为整数，初始为 1

### ✅ 审核策略执行
- [ ] `critical` 条目 `status` 为 `pending`，已触发即时通知
- [ ] `high` 条目通过自动 checklist，每 10 条中有 1 条标记为 `audit_sample`
- [ ] `medium`/`low` 条目通过自动 checklist
- [ ] 未通过审核的条目已记录失败原因并回退到 `pending`

### ✅ 文件命名
- [ ] 所有文件遵循 `{date}-{source}-{slug}.json` 命名规范
- [ ] `date` 为 ISO 8601 短格式
- [ ] `source` 为 `github` 或 `hackernews`
- [ ] `slug` 为 URL-safe 字符串（小写、无空格、无特殊字符）

### ✅ 存储一致性
- [ ] `knowledge/articles/` 中的条目与原始数据（`knowledge/raw/`）一一对应
- [ ] 死信队列条目已更新 `_meta.json`
- [ ] 无孤儿文件（即 articles 中有但 raw 中无对应源数据的条目）

---

## 工作流示例

```
触发（Analyzer 输出就绪 / 手动）
    │
    ▼
┌─────────────┐
│ 1. 接收数据  │
│ - Read      │
│   Analyzer  │
│   输出      │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ 2. 去重检查  │
│ - Grep/Glob │
│   历史记录  │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ 3. 格式标准  │
│ 化           │
│ - Schema    │
│   校验      │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ 4. 审核策略  │
│ - 自动      │
│   checklist │
│ - 人工策略  │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ 5. 分类存储  │
│ - Write     │
│   knowledge/│
│   articles/ │
│ - Edit      │
│   _meta.json│
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ 6. 质量自查  │
│ - 逐项确认  │
└──────┬──────┘
       │
       ▼
   完成入库
   或进入死信队列
```

---

## 错误处理

| 场景 | 处理方式 |
|------|----------|
| Analyzer 输出格式异常 | 记录错误，跳过该批次，通知上游检查 Analyzer 输出 |
| 去重检查超时 | 降级为仅检查 URL 完全匹配，跳过高相似度标题检查 |
| 写入文件失败（磁盘满/权限不足） | 指数退避重试（1s → 2s → 4s），最多 3 次，失败后触发 CRITICAL 告警 |
| 审核 checklist 某项失败 | 记录具体失败项，更新 `last_error`，回退到 `pending` |
| 人工审核超时（critical 条目超过 1 小时未处理） | 自动降级为 `high`，按自动审核策略处理，记录 `"audit_timeout": true` |
| 死信队列写入失败 | 指数退避重试，最多 3 次，失败后触发 CRITICAL 告警 |

---

## 与上下游的协作契约

### 输入契约（来自 Analyzer）

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | UUID v4 |
| `title` | string | ✅ | 标题 |
| `source_url` | string | ✅ | 原始链接 |
| `source_platform` | string | ✅ | `github_trending` 或 `hackernews` |
| `summary` | string | ✅ | 完整中文摘要（200-500字） |
| `tags` | array | ✅ | 3-5 个标签 |
| `collected_at` | string | ✅ | 采集时间（ISO 8601） |
| `status` | string | ✅ | 固定为 `pending` |
| `priority` | string | ✅ | `critical`/`high`/`medium`/`low` |
| `ai_analysis` | object | ✅ | 包含亮点、评分、分类 |
| `version` | number | ✅ | 初始为 1 |

### 输出契约（写入 knowledge/articles/）

与输入契约一致，但 `status` 可能更新为 `reviewed`（自动通过）或保持 `pending`（等待人工审核）。

---

> **版本**：v1.0
> **最后更新**：2024-01-15
> **负责人**：AI 知识库维护团队
