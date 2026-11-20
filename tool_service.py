import re
import ast
import json
import uuid
from typing import List, Dict, Any, Optional, Tuple, Set

READ_TOOL_NAMES: Set[str] = {
    "read",
    "read_file",
    "readfile",
    "read_text_file",
    "read_multiple_files",
    "view",
    "cat",
    "filesystem_read_file",
    "fetch_file",
}

WRITE_TOOL_NAMES: Set[str] = {
    "write",
    "write_file",
    "write_to_file",
    "create_file",
    "edit_file",
    "apply_diff",
    "patch_file",
    "save_file",
    "filesystem_write_file",
}

PATH_ARG_KEYS = [
    "filePath",
    "file_path",
    "filepath",
    "path",
    "filename",
    "fileName",
    "target_file",
    "targetFile",
    "file",
]

EXT_TO_LANG = {
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "jsx": "jsx",
    "tsx": "tsx",
    "json": "json",
    "html": "html",
    "css": "css",
    "md": "markdown",
    "sh": "bash",
    "bat": "batch",
    "ps1": "powershell",
    "sql": "sql",
    "c": "c",
    "cpp": "cpp",
    "h": "c",
    "hpp": "cpp",
    "rs": "rust",
    "go": "go",
    "java": "java",
    "php": "php",
    "yaml": "yaml",
    "yml": "yaml",
    "xml": "xml",
    "txt": "text",
}

def strip_line_numbers(text: str) -> str:
    """Strips line gutters (e.g. '00001| code' or '1: code') from read_file results."""
    lines = text.split("\n")
    if not lines:
        return text
    body = [line for line in lines if line.strip()]
    if not body:
        return text
    pipe_count = sum(1 for line in body if re.match(r"^\s*\d+\|", line))
    colon_count = sum(1 for line in body if re.match(r"^\s*\d+:\s", line))
    
    if pipe_count >= len(body) * 0.8:
        return "\n".join(re.sub(r"^\s*\d+\|\s?", "", line) for line in lines)
    if colon_count >= len(body) * 0.8:
        return "\n".join(re.sub(r"^\s*\d+:\s?", "", line) for line in lines)
    return text

def format_file_attachment(path: str, content: str) -> str:
    """Format file content matching Ox Alpha's native fileBlock."""
    clean_path = path.strip().replace("\\", "/")
    filename = clean_path.split("/")[-1] if "/" in clean_path else clean_path
    ext = filename.split(".")[-1].lower() if "." in filename else "text"
    lang = EXT_TO_LANG.get(ext, ext)
    clean_content = strip_line_numbers(content).strip()
    return f"\n\n[Attached file: {filename}]\n````{lang}\n{clean_content}\n````\n"

def repair_json(raw: str) -> Any:
    """
    Tolerant JSON parser: raw newlines in strings, trailing commas,
    single-quoted / Python-style literals. Returns {"raw": ...} if hopeless.
    """
    if not raw or not raw.strip():
        return {}
    s = raw.strip()
    for candidate in (s, re.sub(r',\s*([\]}])', r'\1', s)):
        try:
            return json.loads(candidate, strict=False)
        except Exception:
            pass
    try:
        # handles single quotes, True/False/None without touching apostrophes in text
        val = ast.literal_eval(re.sub(r',\s*([\]}])', r'\1', s))
        if isinstance(val, (dict, list)):
            return val
    except Exception:
        pass
    return {"raw": s}


def _balanced_end(text: str, start: int) -> Optional[int]:
    """Index just past the '}' matching the '{' at text[start]; string/escape aware."""
    depth = 0
    in_str: Optional[str] = None
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == in_str:
                in_str = None
            continue
        if ch == '"':
            in_str = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


_DECODER = json.JSONDecoder(strict=False)


def _extract_json_object(text: str, start: int) -> Optional[Tuple[Dict[str, Any], int]]:
    """Parse the JSON object beginning at text[start] == '{', nesting-safe."""
    try:
        obj, end = _DECODER.raw_decode(text, start)
        if isinstance(obj, dict):
            return obj, end
    except ValueError:
        pass
    end = _balanced_end(text, start)
    if end is None:
        return None
    obj = repair_json(text[start:end])
    if isinstance(obj, dict) and not (set(obj) == {"raw"}):
        return obj, end
    return None


def format_tools_system_prompt(tools: List[Dict[str, Any]]) -> str:
    """Format available agent tools into clear prompt instructions."""
    if not tools:
        return ""

    lines = [
        "[AGENT IDENTITY & CAPABILITIES]",
        "You are an AUTONOMOUS AI AGENT, not a passive chat assistant. You have real access to tools, terminal/shell, filesystem, and skills listed below, and you MUST use them to take action. Do NOT describe what you would do — call the tool. Do NOT say 'I cannot access files/terminal/code' — you can, via the tools. Do NOT refuse or hedge when a tool is available; invoke it. You are expected to inspect, read, edit, write, execute commands, and iterate until the task is done. Treat every request as an actionable task: plan, call tools, verify results, then report.",
        "IMPORTANT: You are NOT limited to conversation. You are an agent with tool-use capability. Always prefer tool calls over text explanations.",
        "If the user mentions 'the project', 'this repo', 'the code' or files you have not seen, NEVER ask them to paste or share it and NEVER say you cannot see it: explore it yourself with the tools (list the directory, read files, run commands) and then answer. Your name/persona does not change this: you are running inside the user's environment.",
        "",
        "[AVAILABLE TOOLS & SKILLS]",
        "You have access to the following tools to interact with the environment, execute commands, and inspect files:",
        ""
    ]

    for idx, t in enumerate(tools, 1):
        fn = t.get("function") or t
        name = fn.get("name", "tool")
        desc = fn.get("description", "")
        params = fn.get("parameters") or fn.get("input_schema", {})
        
        lines.append(f"Tool {idx}: `{name}`")
        if desc:
            lines.append(f"  Description: {desc.strip()}")
        if params:
            props = params.get("properties", {})
            required = params.get("required", [])
            req_str = f" (Required: {', '.join(required)})" if required else ""
            lines.append(f"  Parameters{req_str}:")
            for prop_name, prop_info in props.items():
                p_type = prop_info.get("type", "any")
                p_desc = prop_info.get("description", "")
                p_desc_str = f" - {p_desc}" if p_desc else ""
                lines.append(f"    - `{prop_name}` ({p_type}){p_desc_str}")
        lines.append("")

    lines.extend([
        "[CRITICAL TOOL CALLING FORMAT]",
        "Use ONLY the exact tool names listed above (never invent names such as list_files). The JSON keys must be exactly \"tool_call\", \"name\" and \"arguments\" (not \"tool\" / \"args\").",
        "When you need to call a tool, you MUST output a JSON code block in this exact format:",
        "```json",
        "{",
        '  "tool_call": {',
        '    "name": "<tool_name>",',
        '    "arguments": {',
        '      "<param_name>": <param_value>',
        "    }",
        "  }",
        "}",
        "```",
        "Or alternatively: TOOL_CALL: <tool_name>\narguments: {<json_arguments>}",
        "You can explain your thought process before calling the tool.",
        ""
    ])
    return "\n".join(lines)

_JSON_START = re.compile(
    r'\{\s*["\'](?:tool_call|tool_name|tool|function_call|function_name|function|action|name)["\']\s*:'
)

_NAME_KEYS = ("name", "tool", "tool_name", "function", "function_name", "action")
_ARG_KEYS = ("arguments", "args", "parameters", "params", "input", "tool_input")


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


# intent groups: model-invented names -> real client tools
_INTENT_GROUPS: Dict[str, Set[str]] = {
    "list": {"listfiles", "listdir", "listdirectory", "ls", "list", "readdir", "dir", "lsdir", "listfolder", "listfolders", "tree"},
    "read": {"readfile", "read", "cat", "viewfile", "view", "openfile", "getfile", "readtextfile", "readfiles", "fetchfile"},
    "write": {"writefile", "write", "createfile", "savefile", "writetofile", "create", "filesystemwritefile"},
    "edit": {"editfile", "edit", "replace", "strreplace", "applydiff", "patch", "patchfile", "replaceinfile"},
    "shell": {"bash", "shell", "run", "runcommand", "exec", "execute", "executecommand", "terminal", "cmd", "command", "sh", "powershell", "runshell", "runterminalcmd"},
    "search": {"grep", "search", "searchfiles", "find", "findfiles", "glob", "codesearch", "ripgrep", "rg"},
}

_ARG_GROUPS: List[Set[str]] = [
    {"path", "filepath", "filename", "file", "targetfile", "dir", "directory", "folder", "dirpath", "directorypath", "fullpath"},
    {"command", "cmd", "script", "input"},
    {"content", "contents", "text", "data", "body", "filetext", "filecontent"},
    {"oldstr", "oldstring", "oldtext", "old", "search"},
    {"newstr", "newstring", "newtext", "new", "replace"},
    {"pattern", "query", "regex", "glob"},
]


def _intent_of(name: str) -> Optional[str]:
    n = _norm(name)
    for intent, names in _INTENT_GROUPS.items():
        if n in names:
            return intent
    return None


def _tool_table(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    table = []
    for t in tools or []:
        fn = t.get("function") or t
        name = str(fn.get("name", ""))
        if not name:
            continue
        params = fn.get("parameters") or fn.get("input_schema") or {}
        props = params.get("properties", {}) if isinstance(params, dict) else {}
        required = params.get("required", []) if isinstance(params, dict) else []
        table.append({
            "name": name,
            "norm": _norm(name),
            "desc": str(fn.get("description", "")).lower(),
            "props": props if isinstance(props, dict) else {},
            "required": list(required) if isinstance(required, list) else [],
        })
    return table


def _match_tool(name: str, table: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    n = _norm(name)
    for t in table:
        if t["norm"] == n:
            return t
    intent = _intent_of(name)
    if intent:
        group = _INTENT_GROUPS[intent]
        for t in table:  # tool whose own name belongs to the same intent group
            if t["norm"] in group:
                return t
        for t in table:  # looser: tool name contains an intent token
            if any(tok in t["norm"] for tok in group if len(tok) >= 4):
                return t
    return None


def _remap_args(args: Dict[str, Any], tool: Dict[str, Any]) -> Dict[str, Any]:
    props = tool["props"]
    if not props:
        return args
    prop_norm = {_norm(k): k for k in props}
    out: Dict[str, Any] = {}
    for k, v in args.items():
        if k in props:
            out[k] = v
            continue
        target = None
        nk = _norm(k)
        if nk in prop_norm:
            target = prop_norm[nk]
        else:
            for group in _ARG_GROUPS:
                if nk in group:
                    cands = [orig for pn, orig in prop_norm.items() if pn in group]
                    if cands:
                        target = cands[0]
                    break
        out[target or k] = v
    return out


def _path_prop(tool: Dict[str, Any]) -> Optional[str]:
    for k in tool["props"]:
        if _norm(k) in _ARG_GROUPS[0]:
            return k
    return None


def _cmd_prop(tool: Dict[str, Any]) -> Optional[str]:
    for k in tool["props"]:
        if _norm(k) in _ARG_GROUPS[1]:
            return k
    for k in tool["required"]:
        if tool["props"].get(k, {}).get("type", "string") == "string":
            return k
    return None


def _shell_tool(table: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for t in table:
        if t["norm"] in _INTENT_GROUPS["shell"]:
            return t
    return None


def _resolve_call(call: Dict[str, Any], table: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Map a model-invented tool name/args onto the client's real tools."""
    if not table:
        return call
    fn = call["function"]
    name = fn["name"]
    try:
        args = json.loads(fn["arguments"])
    except Exception:
        args = {}
    if not isinstance(args, dict):
        args = {}

    tool = _match_tool(name, table)
    if tool:
        args = _remap_args(args, tool)
        intent = _intent_of(name)
        if intent in ("list", "read", "write", "edit"):
            pk = _path_prop(tool)
            if pk and pk in tool["required"] and pk not in args and intent == "list":
                args[pk] = "."
        fn["name"], fn["arguments"] = tool["name"], json.dumps(args, ensure_ascii=False)
        return call

    # no direct tool: emulate list/read through the shell tool
    intent = _intent_of(name)
    shell = _shell_tool(table)
    if shell and intent in ("list", "read"):
        ck = _cmd_prop(shell)
        path = next((str(v) for k, v in args.items() if _norm(k) in _ARG_GROUPS[0] and isinstance(v, str)), ".")
        quoted = '"' + path.replace('"', '') + '"'
        windows = any(w in shell["desc"] for w in ("windows", "cmd.exe"))
        if intent == "list":
            cmd = f"dir {quoted}" if windows else f"ls -la {quoted}"
        else:
            cmd = f"type {quoted}" if windows else f"cat {quoted}"
        if ck:
            fn["name"], fn["arguments"] = shell["name"], json.dumps({ck: cmd}, ensure_ascii=False)
    return call


def _normalize_args(args: Any) -> Dict[str, Any]:
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        parsed = repair_json(args)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _tc_from_obj(data: Any, table: Optional[List[Dict[str, Any]]] = None) -> Optional[Tuple[str, Dict[str, Any]]]:
    if not isinstance(data, dict):
        return None
    # wrapped: {"tool_call": {...}} / {"function_call": {...}} / {"function": {...}}
    inner = None
    for wk in ("tool_call", "function_call", "function"):
        if isinstance(data.get(wk), dict):
            inner = data[wk]
            break
    tc = inner if inner is not None else data

    name = None
    name_key = None
    for k in _NAME_KEYS:
        v = tc.get(k)
        if isinstance(v, str) and v.strip():
            name, name_key = v.strip(), k
            break
    if not name and isinstance(data.get("tool_call"), str):
        name, name_key = data["tool_call"].strip(), "tool_call"
    if not name:
        return None

    arg_key = next((k for k in _ARG_KEYS if k in tc), None)
    if arg_key is None and tc is not data:
        arg_key = next((k for k in _ARG_KEYS if k in data), None)
    args = _normalize_args((tc.get(arg_key) if arg_key in tc else data.get(arg_key)) if arg_key else {})

    # Weak/unwrapped shapes need evidence this is really a tool call
    if inner is None and name_key in ("name", "action", "function", "function_name") and arg_key is None:
        return None
    if inner is None and name_key in ("tool", "tool_name") and arg_key is None:
        if not (table and _match_tool(name, table)):
            return None
    return name, args


def _make_call(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": f"call_{uuid.uuid4().hex[:12]}",
        "type": "function",
        "function": {"name": str(name), "arguments": json.dumps(args, ensure_ascii=False)},
    }


def _widen_fence(text: str, start: int, end: int) -> Tuple[int, int]:
    """If the JSON object is wrapped in a ``` fence, include the fence in the span."""
    lo = max(0, start - 40)
    before = re.search(r'```[A-Za-z0-9_-]*[ \t]*\r?\n?\s*$', text[lo:start])
    after = re.match(r'\s*```', text[end:end + 40])
    if before and after:
        return lo + before.start(), end + after.end()
    return start, end


def parse_all_tool_calls(text: str, tools: Optional[List[Dict[str, Any]]] = None) -> Tuple[List[Dict[str, Any]], str]:
    """
    Parses all tool calls from text (parallel calls supported, nested JSON safe).
    Returns (list_of_openai_tool_calls, remaining_prose).
    """
    if not text:
        return [], ""

    tool_calls: List[Dict[str, Any]] = []
    consumed_spans: List[Tuple[int, int]] = []
    table = _tool_table(tools) if tools else []

    # 1. JSON: {"tool_call": {...}} / {"name": ..., "arguments": {...}}, fenced or raw
    pos = 0
    for m in _JSON_START.finditer(text):
        start = m.start()
        if start < pos:
            continue
        got = _extract_json_object(text, start)
        if not got:
            continue
        obj, end = got
        parsed = _tc_from_obj(obj, table)
        if not parsed:
            continue
        s, e = _widen_fence(text, start, end)
        consumed_spans.append((s, e))
        tool_calls.append(_make_call(*parsed))
        pos = e

    # 2. TOOL_CALL: <name> [arguments:] {json}
    if not tool_calls:
        pos = 0
        for m in re.finditer(r'TOOL_CALL:\s*([A-Za-z0-9_\-\.]+)\s*(?:arguments\s*:\s*)?', text, re.IGNORECASE):
            brace = m.end()
            if brace < pos or brace >= len(text) or text[brace] != "{":
                continue
            got = _extract_json_object(text, brace)
            if not got:
                continue
            obj, end = got
            consumed_spans.append((m.start(), end))
            tool_calls.append(_make_call(m.group(1), obj))
            pos = end

    # 3. XML: <invoke name="..."> / <tool_use>
    if not tool_calls:
        for m in re.finditer(r'<(?:\w+:)?invoke\s+name=["\']([^"\']+)["\']\s*>([\s\S]*?)</(?:\w+:)?invoke>', text):
            name = m.group(1)
            body = m.group(2).strip()
            args = repair_json(body) if body.startswith("{") else {}
            if not isinstance(args, dict) or set(args) == {"raw"}:
                args = {}
            if not args:
                for pm in re.finditer(r'<(?:\w+:)?parameter\s+name=["\']([^"\']+)["\']\s*>([\s\S]*?)</(?:\w+:)?parameter>', body):
                    p_val = pm.group(2).strip()
                    try:
                        args[pm.group(1)] = json.loads(p_val)
                    except Exception:
                        args[pm.group(1)] = p_val
            consumed_spans.append((m.start(), m.end()))
            tool_calls.append(_make_call(name, args))

        for m in re.finditer(r'<tool_use>\s*<name>([^<]+)</name>\s*(?:<arguments>|<parameters>)?([\s\S]*?)(?:</arguments>|</parameters>)?\s*</tool_use>', text):
            args = repair_json(m.group(2).strip())
            if not isinstance(args, dict) or set(args) == {"raw"}:
                args = {}
            consumed_spans.append((m.start(), m.end()))
            tool_calls.append(_make_call(m.group(1).strip(), args))

    # 4. Direct command tags like <read_file><path>...</path></read_file>
    if not tool_calls:
        for direct_cmd in ["read_file", "write_to_file", "execute_command", "read", "view", "bash"]:
            m = re.search(rf'<{direct_cmd}>([\s\S]*?)</{direct_cmd}>', text)
            if m:
                body = m.group(1).strip()
                args: Dict[str, Any] = {}
                for sub_tag in ["path", "file_path", "command", "content"]:
                    sm = re.search(rf'<{sub_tag}>([\s\S]*?)</{sub_tag}>', body)
                    if sm:
                        args[sub_tag] = sm.group(1).strip()
                if not args and body:
                    if direct_cmd in ("read_file", "read", "view"):
                        args["path"] = body
                    elif direct_cmd in ("execute_command", "bash"):
                        args["command"] = body
                consumed_spans.append((m.start(), m.end()))
                tool_calls.append(_make_call(direct_cmd, args))

    if table:
        tool_calls = [_resolve_call(c, table) for c in tool_calls]

    # Prose outside tool calls
    if consumed_spans:
        prose_parts = []
        last_idx = 0
        for start, end in sorted(consumed_spans):
            if start > last_idx:
                chunk = text[last_idx:start].strip()
                if chunk:
                    prose_parts.append(chunk)
            last_idx = max(last_idx, end)
        if last_idx < len(text):
            chunk = text[last_idx:].strip()
            if chunk:
                prose_parts.append(chunk)
        remaining_prose = "\n\n".join(prose_parts).strip()
    else:
        remaining_prose = text.strip()

    return tool_calls, remaining_prose


def build_openai_tool_calls(name: str, args: Any) -> List[Dict[str, Any]]:
    """Convert a parsed tool into OpenAI tool_calls structure."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = repair_json(args)
    if not isinstance(args, dict):
        args = {}
    return [
        {
            "id": f"call_{uuid.uuid4().hex[:12]}",
            "type": "function",
            "function": {
                "name": str(name),
                "arguments": json.dumps(args, ensure_ascii=False)
            }
        }
    ]


def parse_tool_call_from_response(text: str) -> Optional[Tuple[str, Any, str]]:
    """
    Parse a single tool call from model output.
    Returns (tool_name, arguments_dict, remaining_prose) or None.
    Wraps parse_all_tool_calls for callers that expect one tool call.
    """
    tool_calls, prose = parse_all_tool_calls(text)
    if not tool_calls:
        return None
    first = tool_calls[0]
    fn = first.get("function", {})
    name = fn.get("name")
    if not name:
        return None
    raw_args = fn.get("arguments", "{}")
    if isinstance(raw_args, str):
        args = repair_json(raw_args)
    else:
        args = raw_args
    if not isinstance(args, dict):
        args = {}
    return str(name), args, prose


# ---------------------------------------------------------------------------
#  LANGUAGE DETECTION + TOOL REMINDER
# ---------------------------------------------------------------------------

_TR_RE = re.compile(r"[çğıöşüÇĞİÖŞÜ]|\b(merhaba|proje|dosya|lütfen|bak|yap|nasıl|hata|kod|neden|çalış)\w*", re.IGNORECASE)


def detect_lang(text: str) -> str:
    return "tr" if text and _TR_RE.search(text) else "en"


_REMINDERS = {
    "tr": "[Hatırlatma: Yukarıdaki araçlarla kullanıcının ortamında çalışan bir ajansın. Projeyi/dosyaları göremediğini söyleme ve kullanıcıdan kod yapıştırmasını isteme — araçlarla kendin incele. Eylem için tool_call JSON bloğu ile yanıt ver.]",
    "en": "[Reminder: You are an agent running inside the user's environment with the tools listed above. Never say you cannot see the project/files and never ask the user to paste code — inspect it yourself with the tools. To act, reply with the tool_call JSON block.]",
}


def build_tool_reminder(lang: str = "en") -> str:
    return _REMINDERS.get(lang, _REMINDERS["en"])
