"""MCP Knowledge Server — 本地知识库 MCP 服务。

通过 stdio 提供 JSON-RPC 2.0 接口，让 AI 工具可以搜索和读取
knowledge/articles/ 目录下的知识条目。

协议: Model Context Protocol (MCP) over stdio
依赖: 仅 Python 3.10+ 标准库

工具:
    - search_articles: 按关键词搜索文章
    - get_article: 按 ID 获取文章详情
    - knowledge_stats: 知识库统计信息
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

ARTICLES_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "articles"
SERVER_NAME = "knowledge-base-server"
SERVER_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("/tmp/mcp_knowledge_server.log")],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 知识库索引
# ---------------------------------------------------------------------------


class KnowledgeIndex:
    """知识库索引，加载并缓存 articles 目录下的所有 JSON 文件。"""

    def __init__(self, articles_dir: Path) -> None:
        self._dir = articles_dir
        self._articles: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        """加载所有文章到内存索引。"""
        if not self._dir.exists():
            logger.warning("Articles directory not found: %s", self._dir)
            return

        count = 0
        for filepath in self._dir.glob("*.json"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    article = json.load(f)

                article_id = article.get("id")
                if not article_id:
                    logger.warning("Skipping article without id: %s", filepath)
                    continue

                self._articles[article_id] = article
                count += 1
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load %s: %s", filepath, exc)

        logger.info("Loaded %d articles from %s", count, self._dir)

    def search(self, keyword: str, limit: int = 5) -> list[dict[str, Any]]:
        """按关键词搜索文章（标题 + 摘要 + 标签匹配）。

        Args:
            keyword: 搜索关键词，不区分大小写。
            limit: 最多返回条数。

        Returns:
            list[dict]: 匹配的文章列表，按相关性排序。
        """
        keyword_lower = keyword.lower()
        results: list[tuple[int, dict[str, Any]]] = []

        for article in self._articles.values():
            score = 0
            text_fields = [
                article.get("title", ""),
                article.get("summary", ""),
                article.get("source_platform", ""),
            ]
            full_text = " ".join(text_fields).lower()

            if keyword_lower in article.get("title", "").lower():
                score += 10
            if keyword_lower in article.get("summary", "").lower():
                score += 5
            if keyword_lower in full_text:
                score += 1

            # 标签匹配
            tags = article.get("tags", [])
            for tag in tags:
                if keyword_lower in str(tag).lower():
                    score += 3

            if score > 0:
                results.append((score, article))

        # 按分数降序，然后限制条数
        results.sort(key=lambda x: x[0], reverse=True)
        return [article for _, article in results[:limit]]

    def get_by_id(self, article_id: str) -> dict[str, Any] | None:
        """按 ID 获取文章。

        Args:
            article_id: 文章唯一标识。

        Returns:
            dict | None: 文章内容，不存在则返回 None。
        """
        return self._articles.get(article_id)

    def stats(self) -> dict[str, Any]:
        """返回知识库统计信息。

        Returns:
            dict: 包含总数、来源分布、热门标签等。
        """
        total = len(self._articles)
        if total == 0:
            return {
                "total": 0,
                "sources": {},
                "top_tags": [],
            }

        # 来源分布
        source_counter: Counter[str] = Counter()
        # 标签统计
        tag_counter: Counter[str] = Counter()

        for article in self._articles.values():
            source = article.get("source_platform", "unknown")
            source_counter[source] += 1

            tags = article.get("tags", [])
            for tag in tags:
                tag_counter[str(tag)] += 1

        return {
            "total": total,
            "sources": dict(source_counter.most_common()),
            "top_tags": [{"tag": tag, "count": count} for tag, count in tag_counter.most_common(10)],
        }


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 协议处理
# ---------------------------------------------------------------------------


class JSONRPCError(Exception):
    """JSON-RPC 错误。"""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)


# 标准错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class MCPServer:
    """MCP Server over stdio，处理 JSON-RPC 2.0 请求。"""

    def __init__(self, index: KnowledgeIndex) -> None:
        self._index = index
        self._initialized = False

    def _send(self, response: dict[str, Any]) -> None:
        """发送 JSON-RPC 响应到 stdout。"""
        text = json.dumps(response, ensure_ascii=False)
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
        logger.debug("<-- %s", text[:500])

    def _make_response(self, request_id: Any, result: Any) -> dict[str, Any]:
        """构造成功响应。"""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }

    def _make_error(self, request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
        """构造错误响应。"""
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": error,
        }

    def handle(self, request_text: str) -> None:
        """处理单条 JSON-RPC 请求。

        Args:
            request_text: 从 stdin 读取的 JSON 字符串。
        """
        logger.debug("--> %s", request_text[:500])

        # 解析 JSON
        try:
            request = json.loads(request_text)
        except json.JSONDecodeError as exc:
            self._send(self._make_error(None, PARSE_ERROR, f"Parse error: {exc}"))
            return

        # 校验基本结构
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            self._send(self._make_error(request.get("id"), INVALID_REQUEST, "Invalid Request"))
            return

        request_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})

        # 处理 notification（无 id）
        if request_id is None and method not in ("initialized", "$/cancelRequest"):
            # notification 不需要响应，但 initialize 必须有 id
            return

        try:
            result = self._dispatch(method, params)
            if request_id is not None:
                self._send(self._make_response(request_id, result))
        except JSONRPCError as exc:
            if request_id is not None:
                self._send(self._make_error(request_id, exc.code, exc.message, exc.data))
        except Exception as exc:
            logger.exception("Internal error handling %s", method)
            if request_id is not None:
                self._send(self._make_error(request_id, INTERNAL_ERROR, str(exc)))

    def _dispatch(self, method: str, params: Any) -> Any:
        """分发到具体的 MCP 方法处理器。"""
        if method == "initialize":
            return self._handle_initialize(params)
        elif method == "initialized":
            return self._handle_initialized()
        elif method == "tools/list":
            return self._handle_tools_list()
        elif method == "tools/call":
            return self._handle_tools_call(params)
        else:
            raise JSONRPCError(METHOD_NOT_FOUND, f"Method not found: {method}")

    # -----------------------------------------------------------------------
    # MCP 方法实现
    # -----------------------------------------------------------------------

    def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """处理 initialize 请求。"""
        self._initialized = True
        return {
            "protocolVersion": "2024-11-05",
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
            "capabilities": {
                "tools": {},
            },
        }

    def _handle_initialized(self) -> None:
        """处理 initialized notification（无响应）。"""
        pass

    def _handle_tools_list(self) -> dict[str, Any]:
        """返回可用工具列表。"""
        return {
            "tools": [
                {
                    "name": "search_articles",
                    "description": "按关键词搜索知识库文章，匹配标题、摘要和标签",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string",
                                "description": "搜索关键词",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "最多返回条数（默认 5）",
                                "default": 5,
                            },
                        },
                        "required": ["keyword"],
                    },
                },
                {
                    "name": "get_article",
                    "description": "按 ID 获取单篇文章的完整内容",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "article_id": {
                                "type": "string",
                                "description": "文章唯一 ID",
                            },
                        },
                        "required": ["article_id"],
                    },
                },
                {
                    "name": "knowledge_stats",
                    "description": "获取知识库统计信息（文章总数、来源分布、热门标签）",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                    },
                },
            ],
        }

    def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """调用具体的工具。"""
        name = params.get("name", "")
        arguments = params.get("arguments", {})

        if name == "search_articles":
            keyword = arguments.get("keyword", "")
            limit = arguments.get("limit", 5)
            if not isinstance(limit, int) or limit < 1:
                limit = 5
            articles = self._index.search(keyword, limit)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(articles, ensure_ascii=False, indent=2),
                    }
                ],
            }

        elif name == "get_article":
            article_id = arguments.get("article_id", "")
            article = self._index.get_by_id(article_id)
            if article is None:
                raise JSONRPCError(INVALID_PARAMS, f"Article not found: {article_id}")
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(article, ensure_ascii=False, indent=2),
                    }
                ],
            }

        elif name == "knowledge_stats":
            stats = self._index.stats()
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(stats, ensure_ascii=False, indent=2),
                    }
                ],
            }

        else:
            raise JSONRPCError(METHOD_NOT_FOUND, f"Tool not found: {name}")


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------


def main() -> int:
    """MCP Server 主入口。

    从 stdin 读取 JSON-RPC 请求，处理后写入 stdout。
    """
    logger.info("Starting %s v%s", SERVER_NAME, SERVER_VERSION)
    logger.info("Articles directory: %s", ARTICLES_DIR)

    index = KnowledgeIndex(ARTICLES_DIR)
    server = MCPServer(index)

    logger.info("Server ready, waiting for requests...")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        server.handle(line)

    return 0


if __name__ == "__main__":
    sys.exit(main())
