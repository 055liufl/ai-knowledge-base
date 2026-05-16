---
name: tech-summary
description: 当需要对采集的技术内容进行深度分析总结时使用此技能。读取 knowledge/raw/ 中的采集数据，逐条进行技术评估、趋势发现，生成结构化分析 JSON。
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# 技术内容深度分析技能

## 使用场景

- 需要对 Collector 采集的原始数据进行技术价值评估
- 需要为每个技术项目撰写精炼的深度摘要和亮点分析
- 需要发现技术趋势和新兴概念，为知识库提供洞察
- 需要为下游 Organizer 提供带评分和标签的结构化分析结果
- 定时任务触发：Collector 完成后自动触发，或手动触发单批分析

## 执行步骤

### 第 1 步：读取最新采集文件

使用 Glob 查找 `knowledge/raw/` 目录下最新的采集文件：

```
knowledge/raw/github-trending-YYYY-MM-DD.json
```

**选择规则**：
- 优先选择当天日期的文件
- 如有多个文件，选择文件名中时间戳最新者
- 如无当天文件，选择最近 3 天内的文件

使用 Read 读取 JSON 内容，解析 `items` 数组获取待分析项目列表。

### 第 2 步：逐条深度分析

对 `items` 数组中的每个项目执行深度分析，**逐条处理，不可批量跳过**。

#### 2.1 精炼摘要（≤ 50 字）

用一句话概括项目核心价值，**不得超过 50 字**：

```
摘要 = 项目名 + 核心能力 + 适用场景
```

**示例**：

```
LangChain 是 LLM 应用开发标准中间件，提供 Chain/Agent/RAG 抽象，帮助开发者快速构建复杂 AI 应用。
```

**要求**：
- 中文为主，技术术语保留英文
- 不含主观评价词（如"最好的"、"最强大的"）
- 不含未来预测（如"将成为"、"有望"）
- 聚焦"它是什么"和"能做什么"

#### 2.2 技术亮点（2-3 个，用事实说话）

提取 2-3 个**可验证的技术亮点**，每个亮点 15-30 字：

**可用事实类型**：
- **性能数据**："MMLU 得分 86.1%，超越 GPT-4"（需附数据来源）
- **架构特性**："支持 128K 上下文窗口和 GQA 注意力机制"
- **生态规模**："统一接口封装 5000+ 预训练模型"
- **生产验证**："被 Google/Uber/Airbnb 等数千家企业用于生产环境"
- **开源指标**："18.4万 stars，4.6万 forks，社区活跃度极高"

**禁止内容**：
- 主观臆断（"我认为"、"显然"）
- 营销话术（"业界领先"、"颠覆性创新"）
- 无法验证的声明（"大幅提升"、"显著优化"）

#### 2.3 影响力评分（1-10 分，附理由）

按以下标准评分，**15 个项目中 9-10 分不得超过 2 个**：

| 分数段 | 含义 | 判定标准 |
|--------|------|----------|
| **9-10** | 改变格局 | 定义新标准、引发行业重构、生态系统级影响 | **最多 2 个** |
| **7-8** | 直接有帮助 | 解决当前痛点、显著提升效率、可立即应用 | 不限 |
| **5-6** | 值得了解 | 有趣但非必需、中长期可能有用、技术储备 | 不限 |
| **1-4** | 可略过 | Hello World 级别、营销软文、过时技术 | 不限 |

**评分理由要求**：
- 50-80 字，说明评分依据
- 引用具体事实（stars 数、使用企业、性能指标）
- 如评 9-10 分，必须说明"改变了什么格局"

**评分示例**：

```json
{
  "impact_score": 8.5,
  "score_rationale": "定义了 LLM 应用开发的标准架构模式（Chain/Agent/RAG），几乎所有现代 LLM 应用都依赖此库或其衍生方案。生态完整但学习曲线较陡，扣 0.5 分。"
}
```

#### 2.4 标签建议（3-5 个）

从以下预定义词库中选择 3-5 个最相关的标签：

| 分类 | 可选标签 |
|------|----------|
| **模型** | `LLM`, `多模态`, `Embedding`, `代码模型`, `开源模型` |
| **架构** | `Transformer`, `Diffusion`, `MoE`, `状态空间模型` |
| **Agent** | `Agent框架`, `工作流编排`, `工具调用`, `自主Agent` |
| **RAG** | `向量数据库`, `检索增强`, `知识图谱` |
| **训练** | `预训练`, `微调`, `RLHF`, `量化`, `蒸馏` |
| **推理** | `推理优化`, `模型压缩`, `边缘部署` |
| **应用** | `代码生成`, `数据分析`, `内容创作`, `搜索` |
| **安全** | `AI安全`, `对齐`, `提示注入` |
| **基础设施** | `GPU集群`, `推理引擎`, `模型服务`, `数据管道` |
| **平台** | `低代码`, `可视化`, `企业级`, `自托管` |

**标签规则**：
- 优先选择一级标签，必要时补充二级
- 标签必须来自上表，不可自创
- 按相关性排序，第一个标签最核心

### 第 3 步：趋势发现

在完成逐条分析后，对整批项目进行**横向对比分析**，发现技术趋势：

#### 3.1 共同主题

识别 2-3 个贯穿多个项目的共同技术主题：

```
示例：
- 「Agent 基础设施」: LangChain、AutoGPT、Hermes Agent 均聚焦 LLM Agent 开发工具链
- 「私有化部署」: Open WebUI、Dify 均强调企业私有化 LLM 部署方案
```

#### 3.2 新概念/新趋势

识别 1-2 个本批次中出现的新兴概念或趋势变化：

```
示例：
- 「多模型协作」: Hermes Agent 引入智能路由，标志 Agent 从单模型向多模型协作演进
- 「提示词逆向工程」: system-prompts 项目的高关注度反映社区对商业 AI 工具透明化的强烈需求
```

**要求**：
- 基于实际分析的项目，不臆造趋势
- 每个趋势至少引用 2 个项目作为支撑
- 区分「持续趋势」（已存在多期）和「新兴趋势」（本期首次显著）

### 第 4 步：输出分析结果 JSON

将分析结果写入标准格式的 JSON 文件：

```json
{
  "source": "tech_summary",
  "skill": "tech-summary",
  "input_file": "knowledge/raw/github-trending-2026-05-16.json",
  "analyzed_at": "2026-05-16T10:00:00Z",
  "items_analyzed": 15,
  "items": [
    {
      "name": "langchain",
      "url": "https://github.com/langchain-ai/langchain",
      "summary": "LLM 应用开发标准中间件，提供 Chain/Agent/RAG 抽象，帮助开发者快速构建复杂 AI 应用。",
      "highlights": [
        "定义了 LLM 应用开发的标准架构模式（Chain/Agent/RAG/Memory）",
        "生态完整：开发(LangChain)/工作流(LangGraph)/部署(LangServe)/监控(LangSmith)"
      ],
      "impact_score": 8.5,
      "score_rationale": "定义了 LLM 应用开发的标准架构模式，几乎所有现代 LLM 应用都依赖此库。生态完整但学习曲线较陡，扣 0.5 分。",
      "tags": ["Agent框架", "RAG", "基础设施"]
    }
  ],
  "trends": {
    "common_themes": [
      {
        "theme": "Agent 基础设施",
        "description": "多个项目聚焦 LLM Agent 开发工具链",
        "projects": ["langchain", "autogpt", "hermes-agent"]
      }
    ],
    "emerging_concepts": [
      {
        "concept": "多模型协作",
        "description": "Agent 从单模型向多模型智能路由演进",
        "projects": ["hermes-agent"],
        "is_new": true
      }
    ]
  }
}
```

**文件路径**：`knowledge/raw/{input-filename}-analyzed.json`

**命名规则**：
- 基于输入文件名追加 `-analyzed`
- 示例：`github-trending-2026-05-16.json` → `github-trending-2026-05-16-analyzed.json`

## 注意事项

### 评分约束

**硬性约束**：15 个项目中，9-10 分项目**不得超过 2 个**。

**校准方法**：
- 先对所有项目初步评分
- 如 9-10 分项目超过 2 个，将第 3 名及以下的高分项目降级为 8 分
- 降级时更新 `score_rationale`，说明"虽具有重要影响，但尚未达到改变行业格局的程度"

### 摘要约束

**硬性约束**：每个摘要 **≤ 50 字**（含标点）。

**压缩技巧**：
- 删除冗余修饰词（"一个非常强大的" → 删除）
- 用技术术语替代解释性短语（"帮助人们更好地写代码" → "代码生成"）
- 合并并列能力（"支持文本、图像、音频" → "多模态"）

### 事实核查

- ** stars 数**：必须与输入文件一致，不可四舍五入或估算
- **性能指标**：如引用 benchmark 数据，必须注明来源（如 "MMLU 得分 86.1%，来自官方技术报告"）
- **使用企业**：如提及企业名称，必须来自项目 README 或官网的公开声明

### 质量自查

输出前逐项确认：

- [ ] 分析了输入文件中的所有项目（不遗漏、不跳过）
- [ ] 所有摘要 ≤ 50 字
- [ ] 每个项目 2-3 个技术亮点，且均为可验证事实
- [ ] 评分 1-10，15 个项目中 9-10 分 ≤ 2 个
- [ ] 每个评分附 50-80 字理由
- [ ] 标签 3-5 个，全部来自预定义词库
- [ ] 趋势发现基于实际分析项目，每个趋势至少引用 2 个项目
- [ ] JSON 文件可正常解析（无语法错误）

## 输出格式

### JSON Schema

```json
{
  "type": "object",
  "required": ["source", "skill", "input_file", "analyzed_at", "items_analyzed", "items", "trends"],
  "properties": {
    "source": {
      "type": "string",
      "const": "tech_summary"
    },
    "skill": {
      "type": "string",
      "const": "tech-summary"
    },
    "input_file": {
      "type": "string",
      "description": "输入的原始采集文件路径"
    },
    "analyzed_at": {
      "type": "string",
      "format": "date-time"
    },
    "items_analyzed": {
      "type": "integer",
      "description": "分析的项目数量"
    },
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "url", "summary", "highlights", "impact_score", "score_rationale", "tags"],
        "properties": {
          "name": {
            "type": "string",
            "description": "项目名称"
          },
          "url": {
            "type": "string",
            "format": "uri"
          },
          "summary": {
            "type": "string",
            "maxLength": 50,
            "description": "精炼摘要（≤50字）"
          },
          "highlights": {
            "type": "array",
            "minItems": 2,
            "maxItems": 3,
            "items": {
              "type": "string"
            },
            "description": "技术亮点（2-3个，可验证事实）"
          },
          "impact_score": {
            "type": "number",
            "minimum": 1,
            "maximum": 10,
            "description": "影响力评分（1-10）"
          },
          "score_rationale": {
            "type": "string",
            "description": "评分理由（50-80字）"
          },
          "tags": {
            "type": "array",
            "minItems": 3,
            "maxItems": 5,
            "items": {
              "type": "string"
            },
            "description": "技术标签（3-5个）"
          }
        }
      }
    },
    "trends": {
      "type": "object",
      "required": ["common_themes", "emerging_concepts"],
      "properties": {
        "common_themes": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["theme", "description", "projects"],
            "properties": {
              "theme": {
                "type": "string"
              },
              "description": {
                "type": "string"
              },
              "projects": {
                "type": "array",
                "items": {
                  "type": "string"
                }
              }
            }
          }
        },
        "emerging_concepts": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["concept", "description", "projects", "is_new"],
            "properties": {
              "concept": {
                "type": "string"
              },
              "description": {
                "type": "string"
              },
              "projects": {
                "type": "array",
                "items": {
                  "type": "string"
                }
              },
              "is_new": {
                "type": "boolean",
                "description": "是否为本批次首次出现的趋势"
              }
            }
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
  "source": "tech_summary",
  "skill": "tech-summary",
  "input_file": "knowledge/raw/github-trending-2026-05-16.json",
  "analyzed_at": "2026-05-16T10:00:00Z",
  "items_analyzed": 3,
  "items": [
    {
      "name": "transformers",
      "url": "https://github.com/huggingface/transformers",
      "summary": "Hugging Face 开源 Transformer 模型库，统一接口支持 5000+ 预训练模型，LLM 生态核心基础设施。",
      "highlights": [
        "统一接口封装 BERT/GPT/LLaMA 等数千种模型，支持 PyTorch/TensorFlow/JAX",
        "160,665 stars，几乎所有现代 NLP 项目的基础依赖"
      ],
      "impact_score": 9.5,
      "score_rationale": "定义了 LLM 时代的模型接口标准，创新性地统一了不同框架和模型的使用方式。生态覆盖全球，且持续更新最新模型（如 DeepSeek、Qwen）。",
      "tags": ["LLM", "Transformer", "模型库", "基础设施"]
    },
    {
      "name": "AutoGPT",
      "url": "https://github.com/Significant-Gravitas/AutoGPT",
      "summary": "AI Agent 领域开创性项目，实现 LLM 自主任务分解和执行闭环，激发全球 Agent 开发热潮。",
      "highlights": [
        "184,354 stars，开创了 autonomous agent 这一全新技术范式",
        "模块化架构支持 GPT-4/Claude/本地模型，插件系统扩展性强"
      ],
      "impact_score": 9.0,
      "score_rationale": "首次实现 LLM 自主分解任务、调用工具、迭代优化的闭环，直接催生了 BabyAGI、CrewAI 等衍生项目和商业产品。",
      "tags": ["自主Agent", "Agent框架", "GPT"]
    },
    {
      "name": "Open WebUI",
      "url": "https://github.com/open-webui/open-webui",
      "summary": "自托管 AI 聊天界面，支持 Ollama/OpenAI API，提供类 ChatGPT 体验的私有化 LLM 前端方案。",
      "highlights": [
        "137,349 stars，私有化部署 LLM 的首选前端方案",
        "支持 RAG/语音/多用户，Python + Svelte 技术栈部署简单"
      ],
      "impact_score": 7.0,
      "score_rationale": "私有化部署是当前企业刚需，实用性很强。但 UI 层创新有限，与 ChatGPT-Next-Web、LobeChat 等竞品差异化不足。",
      "tags": ["LLM UI", "私有化部署", "自托管"]
    }
  ],
  "trends": {
    "common_themes": [
      {
        "theme": "Agent 基础设施",
        "description": "多个项目聚焦 LLM Agent 开发工具链，从框架到部署形成完整生态",
        "projects": ["transformers", "autogpt"]
      },
      {
        "theme": "私有化部署",
        "description": "企业对数据安全和合规的需求推动私有化 LLM 方案快速发展",
        "projects": ["open-webui"]
      }
    ],
    "emerging_concepts": [
      {
        "concept": "多模型智能路由",
        "description": "Agent 从单模型向多模型协作演进，根据任务类型自动选择最优模型",
        "projects": ["autogpt"],
        "is_new": true
      }
    ]
  }
}
```

---

> **版本**: v1.0  
> **最后更新**: 2026-05-16  
> **关联 Agent**: [Analyzer Agent](../agents/analyzer.md)  
> **关联 Issue**: [#3 · Implement Analyzer Agent](https://github.com/055liufl/ai-knowledge-base/issues/3)
