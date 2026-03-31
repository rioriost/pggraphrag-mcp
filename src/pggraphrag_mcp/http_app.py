from __future__ import annotations

import argparse
import json
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .config import AppConfig
from .db import Database, DatabaseBootstrapError
from .graphrag_service import (
    EntityExpandCommand,
    EntitySearchCommand,
    GraphRAGApplicationService,
    GraphRefreshCommand,
    IngestDocumentCommand,
    RetrievalCommand,
    SourceTraceCommand,
)
from .logging_utils import (
    clear_request_context,
    configure_logging,
    get_logger,
    set_request_context,
)
from .streamable_http import (
    StreamableHttpRequest,
    build_streamable_http_endpoint,
)

LOGGER = get_logger(__name__)


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: dict[str, Any] | None = None


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    result: dict[str, Any] | None = None
    error: JsonRpcError | None = None


class ToolCallParams(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: ToolCallParams | dict[str, Any] | None = None


FROZEN_TOOL_NAMES = [
    "health_check",
    "index_status",
    "graph_status",
    "document_ingest",
    "document_reingest",
    "document_delete",
    "graph_refresh",
    "retrieve_naive",
    "entity_search",
    "entity_expand",
    "retrieve_local_graph",
    "retrieve_hybrid",
    "source_trace",
]

FROZEN_RESOURCE_DEFINITIONS = [
    {
        "name": "document",
        "uri_template": "graphrag://document/{document_id}",
        "description": "Document resource by canonical document identifier.",
    },
    {
        "name": "chunk",
        "uri_template": "graphrag://chunk/{chunk_id}",
        "description": "Chunk resource by canonical chunk identifier.",
    },
    {
        "name": "entity",
        "uri_template": "graphrag://entity/{entity_id}",
        "description": "Entity resource by canonical entity identifier.",
    },
    {
        "name": "retrieval",
        "uri_template": "graphrag://retrieval/{retrieval_id}",
        "description": "Retrieval trace resource by retrieval identifier.",
    },
    {
        "name": "graph-status",
        "uri_template": "graphrag://graph/status",
        "description": "Current graph status resource.",
    },
]


def build_initialize_result(config: AppConfig) -> dict[str, Any]:
    return {
        "protocolVersion": "2024-11-05",
        "serverInfo": {
            "name": config.app_name,
            "version": config.app_version,
        },
        "capabilities": {
            "tools": {"listChanged": False},
            "resources": {"listChanged": False},
        },
    }


def build_tools_list_result() -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": tool_name,
                "description": f"{tool_name} tool",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True,
                },
            }
            for tool_name in FROZEN_TOOL_NAMES
        ]
    }


def build_resources_list_result() -> dict[str, Any]:
    return {
        "resources": [
            {
                "name": item["name"],
                "uriTemplate": item["uri_template"],
                "description": item["description"],
            }
            for item in FROZEN_RESOURCE_DEFINITIONS
        ]
    }


class ReadyResponse(BaseModel):
    status: str
    app_name: str
    version: str
    environment: str
    database: dict[str, Any]
    age_graph_name: str


@dataclass(slots=True)
class ServiceContainer:
    config: AppConfig
    database: Database
    graphrag: GraphRAGApplicationService


def jsonrpc_result(
    request_id: str | int | None,
    result: dict[str, Any],
) -> JSONResponse:
    payload = JsonRpcResponse(id=request_id, result=result)
    return JSONResponse(payload.model_dump(exclude_none=True))


def jsonrpc_error(
    request_id: str | int | None,
    code: int,
    message: str,
    *,
    data: dict[str, Any] | None = None,
    http_status: int = 200,
) -> JSONResponse:
    payload = JsonRpcResponse(
        id=request_id,
        error=JsonRpcError(code=code, message=message, data=data),
    )
    return JSONResponse(
        status_code=http_status,
        content=payload.model_dump(exclude_none=True),
    )


def create_database(config: AppConfig) -> Database:
    return Database(
        config.database_url,
        age_graph_name=config.age_graph_name,
        app_name=config.app_name,
    )


def create_graphrag_service(config: AppConfig) -> GraphRAGApplicationService:
    from .repository import GraphRagRepository

    repository = GraphRagRepository(
        config.database_url,
        age_graph_name=config.age_graph_name,
        embedding_dimensions=config.embedding_dimensions,
        max_return_chunks=config.max_return_chunks,
        max_return_entities=config.max_return_entities,
        max_graph_hops=config.max_graph_hops,
        app_name=config.app_name,
    )
    return GraphRAGApplicationService(
        repository=repository,
        config=config,
    )


def normalize_tool_params(
    raw_params: ToolCallParams | dict[str, Any] | None,
) -> ToolCallParams:
    if isinstance(raw_params, ToolCallParams):
        return raw_params

    if isinstance(raw_params, dict):
        name = raw_params.get("name")
        arguments = raw_params.get("arguments", {})
        if not isinstance(name, str) or not name:
            raise ValueError("Tool name is required.")
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object.")
        return ToolCallParams(name=name, arguments=arguments)

    raise ValueError("Tool call params are required.")


def request_id_from_http_headers(request: Request) -> str:
    header_value = request.headers.get("x-request-id")
    if header_value:
        return header_value
    return str(uuid.uuid4())


def _authorization_query_value(request: Request) -> str | None:
    value = request.headers.get("authorization")
    if value is None:
        return None
    normalized = value.strip()
    return normalized if normalized else None


def _query_items_with_authorization(request: Request) -> list[tuple[str, str]]:
    items = list(request.query_params.multi_items())
    authorization = _authorization_query_value(request)
    if authorization is None:
        return items
    return [item for item in items if item[0] != "authorization"] + [
        ("authorization", authorization)
    ]


def _query_string_from_request(request: Request) -> str:
    items = _query_items_with_authorization(request)
    if not items:
        return ""
    from urllib.parse import urlencode

    return urlencode(items)


def _full_path_with_query(request: Request) -> str:
    query_string = _query_string_from_request(request)
    if not query_string:
        return request.url.path
    return f"{request.url.path}?{query_string}"


def _request_body_text(body: bytes) -> str | None:
    if not body:
        return None
    return body.decode("utf-8")


def _response_from_streamable_result(result: Any) -> Response:
    payload = getattr(result, "payload", None)
    status_code = getattr(result, "status_code", 200)
    headers = dict(getattr(result, "headers", {}) or {})

    if payload is None:
        return Response(
            content=b"",
            status_code=status_code,
            headers=headers,
        )

    headers.setdefault("content-type", "application/json")
    return Response(
        content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        status_code=status_code,
        headers=headers,
        media_type="application/json",
    )


async def invoke_tool(
    *,
    config: AppConfig,
    database: Database,
    graphrag: GraphRAGApplicationService,
    tool_name: str,
    arguments: dict[str, Any],
    identity: str,
    request_id: str,
) -> dict[str, Any]:
    LOGGER.info(
        "Invoking tool",
        extra={
            "event": "tool_invocation",
            "tool_name": tool_name,
            "tool_arguments": arguments,
            "request_id": request_id,
            "authenticated_identity": identity,
        },
    )

    if tool_name == "health_check":
        db_status = database.get_status().to_dict()
        return {
            "status": "ok" if db_status["is_ready"] else "degraded",
            "app_name": config.app_name,
            "version": config.app_version,
            "environment": config.env,
            "database": db_status,
        }

    if tool_name == "index_status":
        db_status = database.get_status().to_dict()
        return {
            "embedding_provider": config.embedding_provider,
            "embedding_model": config.embedding_model,
            "embedding_dimensions": config.embedding_dimensions,
            "max_vector_candidates": config.max_vector_candidates,
            "max_return_chunks": config.max_return_chunks,
            "database_ready": db_status["is_ready"],
            "vector_extension_installed": db_status["vector_extension_installed"],
            "document_table_exists": db_status["document_table_exists"],
            "chunk_table_exists": db_status["chunk_table_exists"],
        }

    if tool_name == "graph_status":
        db_status = database.get_status().to_dict()
        return {
            "graph_name": config.age_graph_name,
            "max_graph_hops": config.max_graph_hops,
            "max_return_entities": config.max_return_entities,
            "age_extension_installed": db_status["age_extension_installed"],
            "age_graph_exists": db_status["age_graph_exists"],
            "database_ready": db_status["is_ready"],
        }

    if tool_name == "document_ingest":
        return graphrag.document_ingest(
            IngestDocumentCommand(
                tenant_id=str(arguments.get("tenant_id", "default")),
                source_uri=str(arguments.get("source_uri", "")),
                title=str(arguments.get("title", "")),
                text=str(arguments.get("text", arguments.get("content", ""))),
                mime_type=str(arguments.get("mime_type", "text/plain")),
                metadata=arguments.get("metadata")
                if isinstance(arguments.get("metadata"), dict)
                else {},
                reingest=bool(arguments.get("reingest", True)),
            )
        )

    if tool_name == "document_reingest":
        return graphrag.document_reingest(
            IngestDocumentCommand(
                tenant_id=str(arguments.get("tenant_id", "default")),
                source_uri=str(arguments.get("source_uri", "")),
                title=str(arguments.get("title", "")),
                text=str(arguments.get("text", arguments.get("content", ""))),
                mime_type=str(arguments.get("mime_type", "text/plain")),
                metadata=arguments.get("metadata")
                if isinstance(arguments.get("metadata"), dict)
                else {},
                reingest=True,
            )
        )

    if tool_name == "document_delete":
        return graphrag.document_delete(
            document_id=str(arguments.get("document_id", ""))
        )

    if tool_name == "graph_refresh":
        document_id = arguments.get("document_id")
        return graphrag.graph_refresh(
            GraphRefreshCommand(
                document_id=uuid.UUID(str(document_id)) if document_id else None,
                full_rebuild=bool(arguments.get("full_rebuild", False)),
            )
        )

    if tool_name == "retrieve_naive":
        return graphrag.retrieve_naive(
            RetrievalCommand(
                query=str(arguments.get("query", "")),
                top_k=int(arguments.get("top_k", 5)),
            )
        )

    if tool_name == "entity_search":
        return graphrag.entity_search(
            EntitySearchCommand(
                query=str(arguments.get("query", "")),
                limit=int(arguments.get("limit", config.max_return_entities)),
            )
        )

    if tool_name == "entity_expand":
        return graphrag.entity_expand(
            EntityExpandCommand(
                entity_id=uuid.UUID(str(arguments.get("entity_id", ""))),
                hops=int(arguments.get("hops", 1)),
                limit=int(arguments.get("limit", config.max_return_entities)),
            )
        )

    if tool_name == "retrieve_local_graph":
        return graphrag.retrieve_local_graph(
            RetrievalCommand(
                query=str(arguments.get("query", "")),
                top_k=int(arguments.get("top_k", 5)),
                graph_limit=int(
                    arguments.get("graph_limit", config.max_return_entities)
                ),
            )
        )

    if tool_name == "retrieve_hybrid":
        return graphrag.retrieve_hybrid(
            RetrievalCommand(
                query=str(arguments.get("query", "")),
                top_k=int(arguments.get("top_k", 5)),
                graph_limit=int(
                    arguments.get("graph_limit", config.max_return_entities)
                ),
            )
        )

    if tool_name == "source_trace":
        return graphrag.source_trace(
            SourceTraceCommand(
                retrieval_id=uuid.UUID(str(arguments.get("retrieval_id", ""))),
            )
        )

    raise HTTPException(status_code=404, detail=f"Unsupported tool: {tool_name}")


def _invoke_tool_sync(
    *,
    config: AppConfig,
    database: Database,
    graphrag: GraphRAGApplicationService,
    tool_name: str,
    arguments: dict[str, Any],
    identity: str,
    request_id: str,
) -> dict[str, Any]:
    LOGGER.info(
        "Invoking tool",
        extra={
            "event": "tool_invocation",
            "tool_name": tool_name,
            "tool_arguments": arguments,
            "request_id": request_id,
            "authenticated_identity": identity,
        },
    )

    if tool_name == "health_check":
        db_status = database.get_status().to_dict()
        return {
            "status": "ok" if db_status["is_ready"] else "degraded",
            "app_name": config.app_name,
            "version": config.app_version,
            "environment": config.env,
            "database": db_status,
        }

    if tool_name == "index_status":
        db_status = database.get_status().to_dict()
        return {
            "embedding_provider": config.embedding_provider,
            "embedding_model": config.embedding_model,
            "embedding_dimensions": config.embedding_dimensions,
            "max_vector_candidates": config.max_vector_candidates,
            "max_return_chunks": config.max_return_chunks,
            "database_ready": db_status["is_ready"],
            "vector_extension_installed": db_status["vector_extension_installed"],
            "document_table_exists": db_status["document_table_exists"],
            "chunk_table_exists": db_status["chunk_table_exists"],
        }

    if tool_name == "graph_status":
        db_status = database.get_status().to_dict()
        return {
            "graph_name": config.age_graph_name,
            "max_graph_hops": config.max_graph_hops,
            "max_return_entities": config.max_return_entities,
            "age_extension_installed": db_status["age_extension_installed"],
            "age_graph_exists": db_status["age_graph_exists"],
            "database_ready": db_status["is_ready"],
        }

    if tool_name == "document_ingest":
        return graphrag.document_ingest(
            IngestDocumentCommand(
                tenant_id=str(arguments.get("tenant_id", "default")),
                source_uri=str(arguments.get("source_uri", "")),
                title=str(arguments.get("title", "")),
                text=str(arguments.get("text", arguments.get("content", ""))),
                mime_type=str(arguments.get("mime_type", "text/plain")),
                metadata=arguments.get("metadata")
                if isinstance(arguments.get("metadata"), dict)
                else {},
                reingest=bool(arguments.get("reingest", True)),
            )
        )

    if tool_name == "document_reingest":
        return graphrag.document_reingest(
            IngestDocumentCommand(
                tenant_id=str(arguments.get("tenant_id", "default")),
                source_uri=str(arguments.get("source_uri", "")),
                title=str(arguments.get("title", "")),
                text=str(arguments.get("text", arguments.get("content", ""))),
                mime_type=str(arguments.get("mime_type", "text/plain")),
                metadata=arguments.get("metadata")
                if isinstance(arguments.get("metadata"), dict)
                else {},
                reingest=True,
            )
        )

    if tool_name == "document_delete":
        return graphrag.document_delete(
            document_id=str(arguments.get("document_id", ""))
        )

    if tool_name == "graph_refresh":
        document_id = arguments.get("document_id")
        return graphrag.graph_refresh(
            GraphRefreshCommand(
                document_id=uuid.UUID(str(document_id)) if document_id else None,
                full_rebuild=bool(arguments.get("full_rebuild", False)),
            )
        )

    if tool_name == "retrieve_naive":
        return graphrag.retrieve_naive(
            RetrievalCommand(
                query=str(arguments.get("query", "")),
                top_k=int(arguments.get("top_k", 5)),
            )
        )

    if tool_name == "entity_search":
        return graphrag.entity_search(
            EntitySearchCommand(
                query=str(arguments.get("query", "")),
                limit=int(arguments.get("limit", config.max_return_entities)),
            )
        )

    if tool_name == "entity_expand":
        return graphrag.entity_expand(
            EntityExpandCommand(
                entity_id=uuid.UUID(str(arguments.get("entity_id", ""))),
                hops=int(arguments.get("hops", 1)),
                limit=int(arguments.get("limit", config.max_return_entities)),
            )
        )

    if tool_name == "retrieve_local_graph":
        return graphrag.retrieve_local_graph(
            RetrievalCommand(
                query=str(arguments.get("query", "")),
                top_k=int(arguments.get("top_k", 5)),
                graph_limit=int(
                    arguments.get("graph_limit", config.max_return_entities)
                ),
            )
        )

    if tool_name == "retrieve_hybrid":
        return graphrag.retrieve_hybrid(
            RetrievalCommand(
                query=str(arguments.get("query", "")),
                top_k=int(arguments.get("top_k", 5)),
                graph_limit=int(
                    arguments.get("graph_limit", config.max_return_entities)
                ),
            )
        )

    if tool_name == "source_trace":
        return graphrag.source_trace(
            SourceTraceCommand(
                retrieval_id=uuid.UUID(str(arguments.get("retrieval_id", ""))),
            )
        )

    raise HTTPException(status_code=404, detail=f"Unsupported tool: {tool_name}")


def create_app(config: AppConfig | None = None) -> FastAPI:
    resolved_config = config or AppConfig.load()
    configure_logging(resolved_config.log_level)

    database = create_database(resolved_config)
    graphrag = create_graphrag_service(resolved_config)
    container = ServiceContainer(
        config=resolved_config,
        database=database,
        graphrag=graphrag,
    )

    class _StreamableHttpRuntimeAdapter:
        def handle_rpc_request(
            self,
            request: dict[str, Any],
        ) -> dict[str, Any] | None:
            request_id = request.get("id")
            method = request.get("method")
            raw_params = request.get("params")

            if method == "initialize":
                return JsonRpcResponse(
                    id=request_id,
                    result=build_initialize_result(container.config),
                ).model_dump(exclude_none=True)

            if method == "tools/list":
                return JsonRpcResponse(
                    id=request_id,
                    result=build_tools_list_result(),
                ).model_dump(exclude_none=True)

            if method == "resources/list":
                return JsonRpcResponse(
                    id=request_id,
                    result=build_resources_list_result(),
                ).model_dump(exclude_none=True)

            if isinstance(method, str) and method.startswith("notifications/"):
                LOGGER.info(
                    "Ignoring MCP notification",
                    extra={
                        "event": "ignored_mcp_notification",
                        "request_id": request_id,
                        "authenticated_identity": "streamable-http",
                        "method": method,
                    },
                )
                return None

            if method not in {"tools/call", "tool.call"}:
                LOGGER.warning(
                    "Unsupported MCP method received",
                    extra={
                        "event": "unsupported_mcp_method",
                        "request_id": request_id,
                        "authenticated_identity": "streamable-http",
                        "method": method,
                        "params_type": type(raw_params).__name__,
                        "params_preview": raw_params
                        if isinstance(raw_params, dict)
                        else None,
                    },
                )
                return JsonRpcResponse(
                    id=request_id,
                    error=JsonRpcError(
                        code=-32601,
                        message="Method not found.",
                        data={"method": method},
                    ),
                ).model_dump(exclude_none=True)

            try:
                tool_params = normalize_tool_params(raw_params)
            except ValueError as exc:
                return JsonRpcResponse(
                    id=request_id,
                    error=JsonRpcError(
                        code=-32602,
                        message="Invalid params.",
                        data={"reason": str(exc)},
                    ),
                ).model_dump(exclude_none=True)

            effective_request_id = (
                str(request_id) if request_id is not None else str(uuid.uuid4())
            )

            try:
                result = _invoke_tool_sync(
                    config=container.config,
                    database=container.database,
                    graphrag=container.graphrag,
                    tool_name=tool_params.name,
                    arguments=tool_params.arguments,
                    identity="streamable-http",
                    request_id=effective_request_id,
                )
                return JsonRpcResponse(id=request_id, result=result).model_dump(
                    exclude_none=True
                )
            except HTTPException as exc:
                return JsonRpcResponse(
                    id=request_id,
                    error=JsonRpcError(
                        code=-32601 if exc.status_code == 404 else -32000,
                        message=str(exc.detail),
                    ),
                ).model_dump(exclude_none=True)
            except Exception as exc:
                LOGGER.exception(
                    "Unhandled MCP tool execution error",
                    extra={
                        "event": "tool_invocation_failed",
                        "request_id": request_id,
                        "authenticated_identity": "streamable-http",
                        "error_type": type(exc).__name__,
                    },
                )
                return JsonRpcResponse(
                    id=request_id,
                    error=JsonRpcError(
                        code=-32603,
                        message="Internal error.",
                        data={"reason": str(exc)},
                    ),
                ).model_dump(exclude_none=True)

    streamable_endpoint = build_streamable_http_endpoint(
        _StreamableHttpRuntimeAdapter(),
        mcp_path=resolved_config.http_path,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.container = container
        app.state.config = resolved_config
        app.state.database = database
        app.state.graphrag = graphrag

        try:
            database.bootstrap()
            LOGGER.info(
                "Database bootstrap completed",
                extra={
                    "event": "database_bootstrap_completed",
                    "database_url": resolved_config.redacted_database_url,
                    "age_graph_name": resolved_config.age_graph_name,
                },
            )
        except DatabaseBootstrapError:
            LOGGER.exception(
                "Database bootstrap failed during startup",
                extra={
                    "event": "database_bootstrap_failed",
                    "database_url": resolved_config.redacted_database_url,
                    "age_graph_name": resolved_config.age_graph_name,
                },
            )

        yield

    app = FastAPI(
        title=resolved_config.app_name,
        version=resolved_config.app_version,
        lifespan=lifespan,
    )
    app.state.container = container
    app.state.config = resolved_config
    app.state.database = database
    app.state.graphrag = graphrag

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        started_at = time.perf_counter()
        request_id = request_id_from_http_headers(request)
        identity = (
            request.headers.get(resolved_config.auth_header_name)
            or request.headers.get("X-Auth-User")
            or request.headers.get("x-auth-user")
        )
        set_request_context(
            request_id=request_id,
            authenticated_identity=identity,
        )

        try:
            response = await call_next(request)
            return response
        finally:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            LOGGER.info(
                "Handled HTTP request",
                extra={
                    "event": "http_request",
                    "request_id": request_id,
                    "authenticated_identity": identity,
                    "method": request.method,
                    "path": request.url.path,
                    "query": str(request.url.query),
                    "status_code": getattr(
                        locals().get("response", None), "status_code", 500
                    ),
                    "duration_ms": duration_ms,
                    "client_host": request.client.host if request.client else None,
                },
            )
            clear_request_context()

    @app.get("/readyz", response_model=ReadyResponse)
    async def readyz() -> ReadyResponse:
        container: ServiceContainer = app.state.container
        status = container.database.get_status().to_dict()
        return ReadyResponse(
            status="ok" if status["is_ready"] else "degraded",
            app_name=container.config.app_name,
            version=container.config.app_version,
            environment=container.config.env,
            database=status,
            age_graph_name=container.config.age_graph_name,
        )

    @app.get("/")
    async def root() -> dict[str, Any]:
        return {
            "service": resolved_config.app_name,
            "version": resolved_config.app_version,
            "endpoint": resolved_config.http_path,
            "status": "ok",
        }

    @app.get(resolved_config.http_path)
    async def mcp_get(
        request: Request,
        x_authenticated_identity: str | None = Header(
            default=None,
            alias="X-Authenticated-Identity",
        ),
        x_auth_user: str | None = Header(
            default=None,
            alias="X-Auth-User",
        ),
        x_auth_mode: str | None = Header(
            default=None,
            alias="X-Auth-Mode",
        ),
    ) -> JSONResponse:
        identity = (
            x_authenticated_identity
            or x_auth_user
            or request.headers.get(resolved_config.auth_header_name)
            or request.headers.get("X-Auth-User")
            or request.headers.get("x-auth-user")
        )
        if not identity:
            return jsonrpc_error(
                None,
                -32001,
                "Missing authenticated identity header.",
                http_status=401,
            )

        return jsonrpc_result(
            None,
            {
                "service": resolved_config.app_name,
                "version": resolved_config.app_version,
                "protocol": "remote-mcp-http",
                "transport": "streamable-http",
                "status": "ok",
                "authenticated_identity": identity,
                "auth_mode": x_auth_mode or request.headers.get("X-Auth-Mode"),
                "tools": [
                    "health_check",
                    "index_status",
                    "graph_status",
                    "document_ingest",
                    "document_reingest",
                    "document_delete",
                    "graph_refresh",
                    "retrieve_naive",
                    "entity_search",
                    "entity_expand",
                    "retrieve_local_graph",
                    "retrieve_hybrid",
                    "source_trace",
                ],
            },
        )

    @app.post(resolved_config.http_path)
    async def mcp_post(
        request: Request,
        x_authenticated_identity: str | None = Header(
            default=None,
            alias="X-Authenticated-Identity",
        ),
        x_auth_user: str | None = Header(
            default=None,
            alias="X-Auth-User",
        ),
        x_auth_mode: str | None = Header(
            default=None,
            alias="X-Auth-Mode",
        ),
    ) -> Response:
        identity = (
            x_authenticated_identity
            or x_auth_user
            or request.headers.get(resolved_config.auth_header_name)
            or request.headers.get("X-Auth-User")
            or request.headers.get("x-auth-user")
        )

        if not identity:
            return jsonrpc_error(
                None,
                -32001,
                "Missing authenticated identity header.",
                http_status=401,
            )

        body = await request.body()
        result = streamable_endpoint.handle(
            StreamableHttpRequest(
                path=_full_path_with_query(request),
                body=_request_body_text(body),
                headers={key.lower(): value for key, value in request.headers.items()},
            )
        )
        return _response_from_streamable_result(result)

    if resolved_config.enable_debug_endpoints:

        @app.get("/debug/config")
        async def debug_config() -> dict[str, Any]:
            payload = resolved_config.model_dump()
            payload["database_url"] = resolved_config.redacted_database_url
            return payload

    return app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the pggraphrag-mcp HTTP app")
    parser.add_argument("--host", default=None, help="Override bind host")
    parser.add_argument("--port", type=int, default=None, help="Override bind port")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn auto reload",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = AppConfig.load()
    app = create_app(config)

    uvicorn.run(
        app,
        host=args.host or config.http_host,
        port=args.port or config.http_port,
        reload=args.reload,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
    return 0


app = create_app()


if __name__ == "__main__":
    raise SystemExit(main())
