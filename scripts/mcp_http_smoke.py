from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(slots=True)
class SmokeConfig:
    base_url: str
    mcp_path: str
    bearer_token: str
    timeout_seconds: float
    verify_tls: bool


class SmokeFailure(RuntimeError):
    """Raised when a smoke assertion fails."""


def parse_args(argv: list[str] | None = None) -> SmokeConfig:
    parser = argparse.ArgumentParser(
        description="Run end-to-end smoke checks against the pggraphrag-mcp HTTPS endpoint."
    )
    parser.add_argument(
        "--base-url",
        default="https://localhost:8443",
        help="Public base URL served by the reverse proxy.",
    )
    parser.add_argument(
        "--mcp-path",
        default="/mcp",
        help="HTTP path for the MCP endpoint.",
    )
    parser.add_argument(
        "--bearer-token",
        required=True,
        help="Bearer token expected by the auth gateway.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=10.0,
        help="Per-request timeout in seconds.",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification for local self-signed certificates.",
    )
    args = parser.parse_args(argv)

    return SmokeConfig(
        base_url=args.base_url.rstrip("/"),
        mcp_path=normalize_path(args.mcp_path),
        bearer_token=args.bearer_token,
        timeout_seconds=args.timeout_seconds,
        verify_tls=not args.insecure,
    )


def normalize_path(path: str) -> str:
    if not path.startswith("/"):
        path = f"/{path}"
    return path


def build_mcp_url(config: SmokeConfig) -> str:
    return f"{config.base_url}{config.mcp_path}"


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)

    try:
        with httpx.Client(
            timeout=config.timeout_seconds, verify=config.verify_tls
        ) as client:
            mcp_url = build_mcp_url(config)

            unauthorized_response = check_unauthorized_access(client, mcp_url)
            authorized_response = check_authorized_health(
                client, mcp_url, config.bearer_token
            )
            tool_response = check_minimal_tool_invocation(
                client, mcp_url, config.bearer_token
            )
            seeded_document_response = seed_smoke_document(
                client, mcp_url, config.bearer_token
            )
            hybrid_response = check_hybrid_retrieval(
                client, mcp_url, config.bearer_token
            )
            hybrid_payload = parse_json_response(hybrid_response)
            retrieval_id = extract_retrieval_id(
                hybrid_payload,
                expected_id="smoke-hybrid",
            )
            trace_response = check_source_trace(
                client,
                mcp_url,
                config.bearer_token,
                retrieval_id,
            )

        result = {
            "status": "ok",
            "base_url": config.base_url,
            "mcp_url": mcp_url,
            "checks": {
                "unauthorized": summarize_response(unauthorized_response),
                "health_check": summarize_response(authorized_response),
                "minimal_tool_invocation": summarize_response(tool_response),
                "seed_document": summarize_response(seeded_document_response),
                "hybrid_retrieval": summarize_response(hybrid_response),
                "source_trace": summarize_response(trace_response),
            },
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except SmokeFailure as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": str(exc),
                },
                indent=2,
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    except httpx.HTTPError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": f"HTTP client error: {exc}",
                },
                indent=2,
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


def check_unauthorized_access(client: httpx.Client, mcp_url: str) -> httpx.Response:
    response = client.post(mcp_url, json=minimal_mcp_request())

    if response.status_code != 401:
        raise SmokeFailure(
            f"Expected unauthorized MCP request to return 401, got {response.status_code} with body: {safe_response_text(response)}"
        )

    return response


def check_authorized_health(
    client: httpx.Client,
    mcp_url: str,
    bearer_token: str,
) -> httpx.Response:
    response = client.post(
        mcp_url,
        headers=auth_headers(bearer_token),
        json=health_check_request(),
    )

    if response.status_code != 200:
        raise SmokeFailure(
            f"Expected authenticated health check to return 200, got {response.status_code} with body: {safe_response_text(response)}"
        )

    payload = parse_json_response(response)
    if payload is None:
        raise SmokeFailure("Authenticated health check did not return JSON.")

    ensure_jsonrpc_result(payload, expected_id="smoke-health")
    return response


def check_minimal_tool_invocation(
    client: httpx.Client,
    mcp_url: str,
    bearer_token: str,
) -> httpx.Response:
    response = client.post(
        mcp_url,
        headers=auth_headers(bearer_token),
        json=minimal_tool_request(),
    )

    if response.status_code != 200:
        raise SmokeFailure(
            f"Expected authenticated minimal tool invocation to return 200, got {response.status_code} with body: {safe_response_text(response)}"
        )

    payload = parse_json_response(response)
    if payload is None:
        raise SmokeFailure("Minimal tool invocation did not return JSON.")

    ensure_jsonrpc_result(payload, expected_id="smoke-tool")
    return response


def auth_headers(bearer_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def seed_smoke_document(
    client: httpx.Client,
    mcp_url: str,
    bearer_token: str,
) -> httpx.Response:
    response = client.post(
        mcp_url,
        headers=auth_headers(bearer_token),
        json=seed_document_request(),
    )

    if response.status_code != 200:
        raise SmokeFailure(
            f"Expected authenticated document seed request to return 200, got {response.status_code} with body: {safe_response_text(response)}"
        )

    payload = parse_json_response(response)
    if payload is None:
        raise SmokeFailure("Seed document request did not return JSON.")

    result = ensure_jsonrpc_result(payload, expected_id="smoke-seed")

    ingestion_job_id = result.get("ingestion_job_id")
    if not isinstance(ingestion_job_id, str) or not ingestion_job_id:
        raise SmokeFailure(
            f"Seed document request did not include a valid ingestion_job_id: {json.dumps(payload, ensure_ascii=False)}"
        )

    document = result.get("document")
    if not isinstance(document, dict):
        raise SmokeFailure(
            f"Seed document request did not include a document object: {json.dumps(payload, ensure_ascii=False)}"
        )

    document_id = document.get("document_id")
    if not isinstance(document_id, str) or not document_id:
        raise SmokeFailure(
            f"Seed document request did not include a valid document_id: {json.dumps(payload, ensure_ascii=False)}"
        )

    chunk_count = result.get("chunk_count")
    if not isinstance(chunk_count, int) or chunk_count < 1:
        raise SmokeFailure(
            f"Seed document request did not report a positive chunk_count: {json.dumps(payload, ensure_ascii=False)}"
        )

    return response


def check_hybrid_retrieval(
    client: httpx.Client,
    mcp_url: str,
    bearer_token: str,
) -> httpx.Response:
    response = client.post(
        mcp_url,
        headers=auth_headers(bearer_token),
        json=hybrid_retrieval_request(),
    )

    if response.status_code != 200:
        raise SmokeFailure(
            f"Expected authenticated hybrid retrieval to return 200, got {response.status_code} with body: {safe_response_text(response)}"
        )

    payload = parse_json_response(response)
    if payload is None:
        raise SmokeFailure("Hybrid retrieval did not return JSON.")

    result = ensure_jsonrpc_result(payload, expected_id="smoke-hybrid")
    retrieval_id = result.get("retrieval_id")
    if not isinstance(retrieval_id, str) or not retrieval_id:
        raise SmokeFailure(
            f"Hybrid retrieval did not include a retrieval_id in payload: {json.dumps(payload, ensure_ascii=False)}"
        )

    if "sources" not in result:
        raise SmokeFailure(
            f"Hybrid retrieval did not include sources in payload: {json.dumps(payload, ensure_ascii=False)}"
        )

    return response


def check_source_trace(
    client: httpx.Client,
    mcp_url: str,
    bearer_token: str,
    retrieval_id: str,
) -> httpx.Response:
    response = client.post(
        mcp_url,
        headers=auth_headers(bearer_token),
        json=source_trace_request(retrieval_id),
    )

    if response.status_code != 200:
        raise SmokeFailure(
            f"Expected authenticated source trace to return 200, got {response.status_code} with body: {safe_response_text(response)}"
        )

    payload = parse_json_response(response)
    if payload is None:
        raise SmokeFailure("Source trace did not return JSON.")

    result = ensure_jsonrpc_result(payload, expected_id="smoke-trace")
    if "sources" not in result:
        raise SmokeFailure(
            f"Source trace did not include sources in payload: {json.dumps(payload, ensure_ascii=False)}"
        )

    if not isinstance(result.get("sources"), list):
        raise SmokeFailure(
            f"Source trace sources field was not a list: {json.dumps(payload, ensure_ascii=False)}"
        )

    return response


def extract_retrieval_id(
    payload: dict[str, Any] | None,
    *,
    expected_id: str,
) -> str:
    if payload is None:
        raise SmokeFailure("Response payload was empty when extracting retrieval_id.")

    result = ensure_jsonrpc_result(payload, expected_id=expected_id)
    retrieval_id = result.get("retrieval_id")
    if not isinstance(retrieval_id, str) or not retrieval_id:
        raise SmokeFailure(
            f"Expected retrieval_id in payload: {json.dumps(payload, ensure_ascii=False)}"
        )
    return retrieval_id


def minimal_mcp_request() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": "smoke-unauthorized",
        "method": "tools/call",
        "params": {
            "name": "health_check",
            "arguments": {},
        },
    }


def health_check_request() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": "smoke-health",
        "method": "tools/call",
        "params": {
            "name": "health_check",
            "arguments": {},
        },
    }


def minimal_tool_request() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": "smoke-tool",
        "method": "tools/call",
        "params": {
            "name": "index_status",
            "arguments": {},
        },
    }


def seed_document_request() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": "smoke-seed",
        "method": "tools/call",
        "params": {
            "name": "document_ingest",
            "arguments": {
                "tenant_id": "smoke-tenant",
                "source_uri": "memory://smoke/docs/graphrag",
                "title": "Smoke GraphRAG Seed",
                "text": (
                    "GraphRAG retrieval smoke test uses Source Trace. "
                    "Source Trace depends on Graph Memory. "
                    "Graph Memory contains Evidence Bundle."
                ),
                "mime_type": "text/plain",
                "metadata": {
                    "seeded_by": "mcp_http_smoke",
                    "scenario": "hybrid_retrieval",
                },
            },
        },
    }


def hybrid_retrieval_request() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": "smoke-hybrid",
        "method": "tools/call",
        "params": {
            "name": "retrieve_hybrid",
            "arguments": {
                "query": "GraphRAG retrieval smoke test Source Trace Graph Memory",
                "top_k": 3,
            },
        },
    }


def source_trace_request(retrieval_id: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": "smoke-trace",
        "method": "tools/call",
        "params": {
            "name": "source_trace",
            "arguments": {
                "retrieval_id": retrieval_id,
            },
        },
    }


def parse_json_response(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except ValueError:
        return None

    if not isinstance(payload, dict):
        return None

    return payload


def ensure_jsonrpc_result(
    payload: dict[str, Any],
    expected_id: str,
) -> dict[str, Any]:
    if payload.get("jsonrpc") != "2.0":
        raise SmokeFailure(
            f"Expected jsonrpc='2.0', got payload: {json.dumps(payload, ensure_ascii=False)}"
        )

    if payload.get("id") != expected_id:
        raise SmokeFailure(
            f"Expected response id '{expected_id}', got '{payload.get('id')}' in payload: {json.dumps(payload, ensure_ascii=False)}"
        )

    if "error" in payload:
        raise SmokeFailure(
            f"Expected successful JSON-RPC result, got error payload: {json.dumps(payload, ensure_ascii=False)}"
        )

    result = payload.get("result")
    if not isinstance(result, dict):
        raise SmokeFailure(
            f"Expected JSON-RPC result object, got payload: {json.dumps(payload, ensure_ascii=False)}"
        )

    return result


def summarize_response(response: httpx.Response) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "status_code": response.status_code,
    }

    try:
        summary["json"] = response.json()
    except ValueError:
        summary["text"] = safe_response_text(response)

    return summary


def safe_response_text(response: httpx.Response, max_length: int = 500) -> str:
    text = response.text.strip()
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}..."


if __name__ == "__main__":
    raise SystemExit(main())
