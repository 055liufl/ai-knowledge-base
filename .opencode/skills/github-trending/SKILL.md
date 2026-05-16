---
name: github-trending
description: 当需要采集 GitHub 热门开源项目时使用此技能。自动抓取 GitHub Trending/Search API 数据，过滤 AI/LLM/Agent 相关项目，生成结构化 JSON 知识条目存入 knowledge/raw/。
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# GitHub Trending 采集技能

## 使用场景

- 需要获取本周/今日 GitHub 上热门的 AI/LLM/Agent 相关开源项目
- 需要为 AI 知识库采集新的技术动态素材
- 需要跟踪特定技术领域（如大语言模型、AI Agent、RAG 等）的最新开源趋势
- 定时任务触发：建议每天 UTC 0:00 执行一次

## 执行步骤

### 第 1 步：搜索热门仓库

使用 GitHub Search API 获取 AI 相关热门仓库：

```
GET https://api.github.com/search/repositories?q={QUERY}&sort=stars&order=desc&per_page=30
```

**推荐查询组合**（可并行执行多个查询后合并结果）：

| 查询 | 用途 |
|------|------|
| `llm+language:python` | Python LLM 项目 |
| `ai+agent+stars:>1000` | AI Agent 项目（ stars > 1000） |
| `topic:machine-learning` | 机器学习主题项目 |
| `rag+stars:>500` | RAG 相关项目 |

**备用方案**：如果 Search API 限流或不可用，可使用 WebFetch 访问 `https://github.com/trending/python?since=daily` 解析 HTML。

### 第 2 步：提取信息

对每个仓库提取以下字段：

| 字段 | 来源 | 说明 |
|------|------|------|
| `name` | `repo.name` | 仓库名称 |
| `url` | `repo.html_url` | 仓库链接 |
| `stars` | `repo.stargazers_count` | Star 数量 |
| `language` | `repo.language` | 主语言 |
| `topics` | `repo.topics` | 话题标签 |
| `description` | `repo.description` | 项目描述 |
| `created_at` | `repo.created_at` | 创建时间 |
| `updated_at` | `repo.updated_at` | 最后更新时间 |

### 第 3 步：过滤

**纳入条件**（满足任意一条即可）：
- 标题/描述/话题包含 `ai`、`llm`、`agent`、`rag`、`gpt`、`llama`、`mistral`、`openai`、`anthropic`、`claude`
- 话题包含 `machine-learning`、`deep-learning`、`nlp`、`transformer`
- 描述中明确提及 AI/ML 应用场景

**排除条件**（满足任意一条即丢弃）：
- 名称或描述包含 `awesome-` 或 `awesome`（Awesome 列表类项目只收集链接，不产出差分价值）
- 非软件项目（如纯文档、书籍、课程仓库）
- 已归档（archived）的仓库
- 创建时间超过 5 年且无近期更新（`updated_at` 早于 6 个月前）

### 第 4 步：去重

在合并多个查询结果后执行去重：

1. **URL 去重**：以 `url` 字段为唯一键，完全相同的只保留一条
2. **名称去重**：计算名称相似度（Levenshtein 距离），相似度 > 85% 的视为重复，保留 stars 更高的一条
3. **历史去重**：使用 Glob 检查 `knowledge/raw/github-trending-*.json`，排除过去 7 天内已采集过的 URL

### 第 5 步：撰写中文摘要

为每个保留的项目撰写中文摘要，**严格遵循公式**：

```
摘要 = 项目名 + 做什么 + 为什么值得关注
```

**示例**：

```
LangChain 是一个 AI Agent 和 LLM 应用开发的标准中间件，提供了 Chain、Agent、RAG、Memory 等核心抽象，帮助开发者快速构建基于大语言模型的复杂应用。它几乎定义了现代 LLM 应用开发的架构范式，拥有完整的生态（LangGraph、LangServe、LangSmith），被全球数百万开发者使用，是连接 LLM 与外部世界的标准桥梁。
```

**摘要要求**：
- 中文为主，技术术语保留英文（如 `LangChain`、`RAG`、`LLM`）
- 长度 80-150 字
- 不编造项目未声明的能力
- 突出项目独特价值（为什么值得收录）

### 第 6 步：排序取 Top 15

按以下优先级排序，取前 15 条：

1. ** stars 数量**（降序，主要依据）
2. **最近 7 天 star 增长**（如有，降序）
3. **与 AI/LLM/Agent 的相关度**（根据话题标签匹配度）
4. **创建时间**（越新越优先，反映新兴趋势）

如果总数不足 15 条，保留全部并标注 `"warning": "insufficient_data"`。

### 第 7 步：输出 JSON

将结果写入标准格式的 JSON 文件：

```json
{
  "source": "github_trending",
  "skill": "github-trending",
  "collected_at": "2026-05-16T08:00:00Z",
  "items": [
    {
      "name": "langchain",
      "url": "https://github.com/langchain-ai/langchain",
      "summary": "LangChain 是一个 AI Agent 和 LLM 应用开发的标准中间件...",
      "stars": 136898,
      "language": "Python",
      "topics": ["llm", "agent", "rag", "ai"]
    }
  ]
}
```

**文件路径**：`knowledge/raw/github-trending-{YYYY-MM-DD}.json`

**命名规范**：
- `{YYYY-MM-DD}`：采集日期（ISO 8601 短格式）
- 同一天多次采集时，追加 `-{序号}`，如 `github-trending-2026-05-16-2.json`

## 注意事项

### API 限流处理

GitHub Search API 的速率限制为每分钟 10 次（未认证）或每分钟 30 次（已认证）。如遇限流：

1. 检查环境变量 `GITHUB_TOKEN` 是否存在
2. 如被限流，指数退避重试（30s → 1min → 2min），最多 3 次
3. 如仍失败，记录 `"error": "rate_limited"` 并终止采集

### 数据真实性

- **绝不编造数据**：stars 数、语言、话题必须来自 API 实际返回
- **绝不篡改描述**：摘要基于 `description` 提炼，不可添加原文未提及的信息
- **URL 规范化**：去除 GitHub URL 中的跟踪参数（如 `utm_source`）

### 质量自查

输出前逐项确认：

- [ ] 条目数量 ≥ 15（或已标注 `insufficient_data`）
- [ ] 无重复 URL
- [ ] 无 Awesome 列表类项目
- [ ] 所有摘要均为中文，长度 80-150 字
- [ ] 所有 stars 数为整数，且来自 API 真实数据
- [ ] `collected_at` 为有效 ISO 8601 格式
- [ ] JSON 文件可正常解析（无语法错误）

## 输出格式

### JSON Schema

```json
{
  "type": "object",
  "required": ["source", "skill", "collected_at", "items"],
  "properties": {
    "source": {
      "type": "string",
      "const": "github_trending"
    },
    "skill": {
      "type": "string",
      "const": "github-trending"
    },
    "collected_at": {
      "type": "string",
      "format": "date-time"
    },
    "warning": {
      "type": "string",
      "enum": ["insufficient_data"]
    },
    "error": {
      "type": "string"
    },
    "items": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["name", "url", "summary", "stars"],
        "properties": {
          "name": {
            "type": "string",
            "description": "仓库名称"
          },
          "url": {
            "type": "string",
            "format": "uri",
            "description": "仓库 GitHub 链接"
          },
          "summary": {
            "type": "string",
            "description": "中文摘要（80-150字）"
          },
          "stars": {
            "type": "integer",
            "description": "Star 数量"
          },
          "language": {
            "type": ["string", "null"],
            "description": "主编程语言"
          },
          "topics": {
            "type": "array",
            "items": {
              "type": "string"
            },
            "description": "GitHub 话题标签"
          }
        }
      }
    }
  }
}
```

### 完整示例

```json
{
  "source": "github_trending",
  "skill": "github-trending",
  "collected_at": "2026-05-16T08:00:00Z",
  "items": [
    {
      "name": "transformers",
      "url": "https://github.com/huggingface/transformers",
      "summary": "Hugging Face 开源的 Transformer 模型库，提供数千种预训练模型的统一接口，涵盖 BERT、GPT、LLaMA 等主流架构，支持文本、图像、音频和多模态任务。它是当今 LLM 生态系统的核心基础设施，几乎所有现代 NLP 项目都直接或间接依赖此库。",
      "stars": 160665,
      "language": "Python",
      "topics": ["llm", "transformer", "nlp", "pytorch"]
    },
    {
      "name": "AutoGPT",
      "url": "https://github.com/Significant-Gravitas/AutoGPT",
      "summary": "AI Agent 领域的开创性项目，实现了让大语言模型自主分解任务、执行操作并迭代优化的闭环系统。AutoGPT 提出了自主 Agent 范式，激发了全球开发者对 AI Agent 的热情，直接催生了 BabyAGI 等衍生项目。",
      "stars": 184354,
      "language": "Python",
      "topics": ["ai-agent", "autonomous-agents", "gpt", "llm"]
    }
  ]
}
```

---

> **版本**: v1.0  
> **最后更新**: 2026-05-16  
> **关联 Agent**: [Collector Agent](../agents/collector.md)  
> **关联 Issue**: [#1 · Implement Collector Agent](https://github.com/055liufl/ai-knowledge-base/issues/1)
