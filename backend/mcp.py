"""
Model Context Protocol (MCP) Streamable HTTP / JSON-RPC 2.0 server for Klukva.
Supports authentication via Personal Access Tokens (klk_...) or JWT Bearer tokens.
"""

import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from backend.auth import get_current_user, has_min_role
from backend.db import VALID_CLUSTERS, VALID_STATUSES, VALID_TASK_TYPES, db

mcp_router = APIRouter()

MCP_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "list_tasks",
        "description": "Получить список задач с фильтрацией по статусу, исполнителю, типу, кластеру, спринту и поиску.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": VALID_STATUSES},
                "task_type": {"type": "string", "enum": VALID_TASK_TYPES},
                "epic_id": {"type": "integer"},
                "sirius_id": {"type": "integer"},
                "assignee": {"type": "string"},
                "search": {"type": "string"},
                "in_sprint": {"type": "boolean"},
            },
        },
    },
    {
        "name": "get_task",
        "description": "Получить подробную информацию о задаче по ID, включая комментарии, связи и дочерние задачи/эпики.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "create_task",
        "description": "Создать новую задачу, Эпик или Сириус в Klukva.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "story_points": {"type": "number"},
                "assignee": {"type": "string"},
                "status": {"type": "string", "enum": VALID_STATUSES},
                "task_type": {"type": "string", "enum": VALID_TASK_TYPES},
                "epic_id": {"type": "integer"},
                "sirius_id": {"type": "integer"},
                "in_sprint": {"type": "boolean"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "update_task",
        "description": "Обновить поля задачи (статус, исполнитель, тип, epic_id, sirius_id, SP, название, описание).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "status": {"type": "string", "enum": VALID_STATUSES},
                "task_type": {"type": "string", "enum": VALID_TASK_TYPES},
                "epic_id": {"type": ["integer", "null"]},
                "sirius_id": {"type": ["integer", "null"]},
                "assignee": {"type": ["string", "null"]},
                "story_points": {"type": ["number", "null"]},
                "in_sprint": {"type": "boolean"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "add_comment",
        "description": "Добавить комментарий к задаче.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "text": {"type": "string"},
            },
            "required": ["task_id", "text"],
        },
    },
    {
        "name": "list_sprints",
        "description": "Получить список всех спринтов.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_active_sprint",
        "description": "Получить текущий активный спринт.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_users",
        "description": "Получить список пользователей трекера.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_analytics",
        "description": "Получить сводную аналитику и метрики по задачам, спринтам и исполнителям.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "create_link",
        "description": "Связать две задачи (relates, blocks, parent).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_id": {"type": "integer"},
                "target_id": {"type": "integer"},
                "type": {"type": "string", "enum": ["relates", "blocks", "parent"]},
            },
            "required": ["source_id", "target_id", "type"],
        },
    },
]

MCP_SYSTEM_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "get_audit_log",
        "description": "Системный журнал всех изменений в трекере (только для системного пользователя).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "username": {"type": "string"},
                "action": {"type": "string"},
                "search": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "list_all_files",
        "description": "Список всех вложений и файлов пользователей (только для системного пользователя).",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _execute_tool(name: str, args: Dict[str, Any], user: Dict[str, Any]) -> Any:
    if name == "list_tasks":
        return db.get_tasks(
            status=args.get("status"),
            task_type=args.get("task_type"),
            cluster=args.get("cluster"),
            epic_id=args.get("epic_id"),
            sirius_id=args.get("sirius_id"),
            assignee=args.get("assignee"),
            search=args.get("search"),
            in_sprint=args.get("in_sprint"),
        )
    if name == "get_task":
        tid = int(args["task_id"])
        task = db.get_task_by_id(tid)
        if not task:
            raise ValueError("Задача не найдена")
        children = db.get_task_hierarchy_children(tid)
        return {**task, "comments": db.get_comments(tid), "links": db.get_links(tid), **children}
    if name == "create_task":
        if not has_min_role(user, "member"):
            raise PermissionError("Недостаточно прав для создания задачи")
        t = db.create_task(
            title=args["title"],
            description=args.get("description") or "",
            story_points=args.get("story_points"),
            assignee=args.get("assignee"),
            status=args.get("status") or "Бэклог",
            task_type=args.get("task_type") or "Задача",
            cluster=args.get("cluster") or "",
            epic_id=args.get("epic_id"),
            sirius_id=args.get("sirius_id"),
            in_sprint=bool(args.get("in_sprint", False)),
            created_by=user["username"],
        )
        db.add_activity(user["username"], "task_created", t["id"], t["key"], t["title"], f"Создана через MCP ({t['task_type']})")
        return t
    if name == "update_task":
        if not has_min_role(user, "member"):
            raise PermissionError("Недостаточно прав для изменения задачи")
        tid = int(args["task_id"])
        updates = {k: v for k, v in args.items() if k != "task_id"}
        updated = db.update_task(tid, updates)
        if not updated:
            raise ValueError("Задача не найдена")
        db.add_activity(user["username"], "task_updated", updated["id"], updated["key"], updated["title"], "Обновлена через MCP")
        return updated
    if name == "add_comment":
        if not has_min_role(user, "member"):
            raise PermissionError("Недостаточно прав для добавления комментария")
        tid = int(args["task_id"])
        c = db.add_comment(tid, user["username"], args["text"], [])
        task = db.get_task_by_id(tid)
        if task:
            db.add_activity(user["username"], "comment_added", tid, task["key"], task["title"], args["text"][:120])
        return c
    if name == "list_sprints":
        return db.get_sprints()
    if name == "get_active_sprint":
        return db.get_active_sprint()
    if name == "list_users":
        return db.get_users()
    if name == "get_analytics":
        return db.get_analytics()
    if name == "create_link":
        if not has_min_role(user, "member"):
            raise PermissionError("Недостаточно прав для создания связи")
        link = db.create_link(args["type"], int(args["source_id"]), int(args["target_id"]), user["username"])
        db.add_activity(user["username"], "link_created", int(args["source_id"]), details=f"Связь через MCP: {args['type']} -> #{args['target_id']}")
        return link
    if name == "get_audit_log":
        if not user.get("is_system"):
            raise PermissionError("Доступно только системному пользователю")
        return db.get_all_activities(
            username=args.get("username"),
            action=args.get("action"),
            search=args.get("search"),
            limit=int(args.get("limit") or 200),
        )
    if name == "list_all_files":
        if not user.get("is_system"):
            raise PermissionError("Доступно только системному пользователю")
        return db.get_all_attachments()
    raise KeyError(f"Неизвестный инструмент: {name}")


def _rpc_error(req_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


@mcp_router.get("/mcp")
@mcp_router.get("/api/mcp")
async def mcp_info(current_user: Dict = Depends(get_current_user)):
    tools = MCP_TOOLS + (MCP_SYSTEM_TOOLS if current_user.get("is_system") else [])
    return {
        "name": "klukva-mcp",
        "version": "1.0.0",
        "protocol": "mcp-jsonrpc-2.0",
        "user": current_user["username"],
        "role": current_user.get("role", "member"),
        "is_system": bool(current_user.get("is_system")),
        "tools": [t["name"] for t in tools],
    }


@mcp_router.post("/mcp")
@mcp_router.post("/api/mcp")
async def mcp_endpoint(request: Request, current_user: Dict = Depends(get_current_user)):
    try:
        body = await request.json()
    except Exception:
        return _rpc_error(None, -32700, "Parse error")

    req_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params") or {}

    if method == "initialize":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": params.get("protocolVersion") or "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "klukva-mcp", "version": "1.0.0"},
            },
        })

    if method in ("notifications/initialized", "notifications/cancelled"):
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {}})

    if method == "ping":
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {}})

    if method == "tools/list":
        tools = MCP_TOOLS + (MCP_SYSTEM_TOOLS if current_user.get("is_system") else [])
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": tools},
        })

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments") or {}
        try:
            res = _execute_tool(tool_name, tool_args, current_user)
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=2)}],
                    "isError": False,
                },
            })
        except PermissionError as e:
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": str(e)}], "isError": True},
            })
        except Exception as e:
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": f"Ошибка: {e}"}], "isError": True},
            })

    return _rpc_error(req_id, -32601, f"Method not found: {method}")

