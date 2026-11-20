import re
import json
from typing import List, Dict, Any, Tuple, Optional
from tool_service import (
    READ_TOOL_NAMES, 
    WRITE_TOOL_NAMES, 
    PATH_ARG_KEYS, 
    format_file_attachment, 
    strip_line_numbers,
    build_tool_reminder,
    detect_lang,
)
from config import CONFIG
from file_store import file_store

MAX_CONTEXT_CHARS = 38000
KEEP_RECENT_TURNS = 14

def extract_file_path_from_args(args: Any) -> Optional[str]:
    """Find file path inside tool arguments dict or JSON string."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            pass
    if isinstance(args, dict):
        for k in PATH_ARG_KEYS:
            if k in args and isinstance(args[k], str) and args[k].strip():
                return args[k].strip()
    return None

def build_tool_calls_map(messages: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Builds a map from tool_call_id to {name, args} from prior assistant messages."""
    calls_map: Dict[str, Dict[str, Any]] = {}
    for msg in messages:
        if not msg:
            continue
        role = msg.get("role")
        if role == "assistant" and msg.get("tool_calls"):
            for tc in msg.get("tool_calls", []):
                call_id = tc.get("id") or tc.get("tool_call_id")
                fn = tc.get("function", {})
                if call_id and fn:
                    calls_map[str(call_id)] = {
                        "name": fn.get("name", ""),
                        "args": fn.get("arguments", {})
                    }
        if isinstance(msg.get("content"), list):
            for part in msg.get("content", []):
                if isinstance(part, dict) and part.get("type") in ("tool_use", "tool_call"):
                    call_id = part.get("id") or part.get("tool_use_id")
                    if call_id:
                        calls_map[str(call_id)] = {
                            "name": part.get("name", ""),
                            "args": part.get("input", {})
                        }
    return calls_map

def partition_system_prompt(text: str, max_chunk_chars: int = 3500) -> List[str]:
    """Splits large system prompt into section parts so Ox Alpha digests each skill cleanly."""
    if len(text) <= max_chunk_chars:
        return [text]

    sections = re.split(r'\n(?=[#\[][^\n]+)', text)
    chunks: List[str] = []
    current_chunk = ""

    for sec in sections:
        if len(current_chunk) + len(sec) < max_chunk_chars:
            current_chunk += ("\n\n" if current_chunk else "") + sec
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sec

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks if chunks else [text]

def compact_conversation_history(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    If total characters exceed MAX_CONTEXT_CHARS:
    Retains first turn (goal), compacts middle turns, retains last KEEP_RECENT_TURNS.
    """
    total_chars = sum(len(str(m.get("content", ""))) for m in messages)
    if total_chars <= MAX_CONTEXT_CHARS or len(messages) <= KEEP_RECENT_TURNS + 2:
        return messages

    head = messages[:2]  # First user request
    tail = messages[-KEEP_RECENT_TURNS:]  # Recent turns
    dropped_count = len(messages) - len(head) - len(tail)

    summary_marker = {
        "role": "user",
        "content": f"[Earlier conversation history ({dropped_count} messages) compacted by proxy to keep focus on immediate steps]"
    }
    return head + [summary_marker] + tail

def _last_user_text(messages: List[Dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m and m.get("role") == "user":
            c = m.get("content", "")
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                return " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
    return ""


def process_messages_for_oxalpha(
    messages: List[Dict[str, Any]], 
    tools_prompt: str = "",
    tools: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Production-grade message processor for OxAlpha:
    1. Compacts giant histories to stay inside the optimal reasoning window.
    2. Maps tool results (read -> attached file, write -> file written, command -> command output).
    3. Resolves uploaded file_id references into native file blocks.
    4. Formats system instructions and tool definitions into structured parts.
    5. Cleans into alternating user/assistant turns.
    """
    if not messages:
        return [{"role": "user", "content": "Hello"}]

    compacted = compact_conversation_history(messages)
    tool_calls_map = build_tool_calls_map(compacted)
    system_parts: List[str] = []
    normalized: List[Dict[str, Any]] = []

    for msg in compacted:
        if not msg:
            continue
        role = msg.get("role", "user")
        content = msg.get("content", "")

        # System message extraction
        if role == "system":
            if isinstance(content, str) and content.strip():
                system_parts.append(content.strip())
            elif isinstance(content, list):
                for p in content:
                    if isinstance(p, dict) and p.get("type") == "text":
                        t = p.get("text", "").strip()
                        if t:
                            system_parts.append(t)
            continue

        # Tool result mapping
        if role == "tool":
            tool_id = str(msg.get("tool_call_id") or msg.get("tool_use_id") or "")
            call_info = tool_calls_map.get(tool_id, {})
            tool_name = call_info.get("name", "").lower()
            tool_args = call_info.get("args", {})
            file_path = extract_file_path_from_args(tool_args)

            text_val = ""
            if isinstance(content, str):
                text_val = content
            elif isinstance(content, list):
                text_val = " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")

            # 1. READ FILE RESULT -> Native file attachment
            if (tool_name in READ_TOOL_NAMES or "read" in tool_name) and file_path:
                file_block = format_file_attachment(file_path, text_val)
                normalized.append({
                    "role": "user",
                    "content": f"[Result of {tool_name} for '{file_path}']:{file_block}"
                })
            # 2. WRITE FILE RESULT -> Acknowledgment
            elif tool_name in WRITE_TOOL_NAMES or "write" in tool_name:
                path_str = f" to '{file_path}'" if file_path else ""
                normalized.append({
                    "role": "user",
                    "content": f"[File Written{path_str}]\n{text_val.strip() or 'File updated successfully.'}"
                })
            # 3. COMMAND / SKILL EXECUTION
            else:
                call_label = f" {tool_name}" if tool_name else ""
                normalized.append({
                    "role": "user",
                    "content": f"[Command Output{call_label}]:\n{text_val.strip()}"
                })
            continue

        # Assistant messages
        if role == "assistant":
            if msg.get("tool_calls"):
                lines = []
                for tc in msg.get("tool_calls", []):
                    fn = tc.get("function", {})
                    fn_name = fn.get("name", "tool")
                    fn_args = fn.get("arguments", "{}")
                    lines.append(f'```json\n{{"tool_call": {{"name": "{fn_name}", "arguments": {fn_args}}}}}\n```')
                asst_content = "\n\n".join(lines)
                if content and isinstance(content, str):
                    asst_content = f"{content.strip()}\n\n{asst_content}"
                normalized.append({"role": "assistant", "content": asst_content})
            else:
                text_val = content if isinstance(content, str) else str(content)
                normalized.append({"role": "assistant", "content": text_val})
            continue

        # User messages
        if role == "user":
            if isinstance(content, str):
                normalized.append({"role": "user", "content": content})
            elif isinstance(content, list):
                text_accumulator = ""
                image_parts = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    p_type = part.get("type")
                    if p_type == "text":
                        text_accumulator += ("\n" if text_accumulator else "") + part.get("text", "")
                    elif p_type == "image_url":
                        image_parts.append(part)
                    elif p_type == "image":
                        src = part.get("source", {})
                        if src.get("type") == "base64":
                            m_type = src.get("media_type", "image/png")
                            data = src.get("data", "")
                            image_parts.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:{m_type};base64,{data}"}
                            })
                    elif p_type in ("file", "document"):
                        f_id = part.get("file_id") or (part.get("source", {}).get("file_id") if isinstance(part.get("source"), dict) else None)
                        if f_id:
                            f_meta = file_store.get_file(f_id)
                            f_bytes = file_store.get_file_content(f_id)
                            if f_meta and f_bytes:
                                f_name = f_meta.get("filename", "file.txt")
                                try:
                                    f_text = f_bytes.decode("utf-8")
                                    text_accumulator += format_file_attachment(f_name, f_text)
                                except Exception:
                                    pass

                if image_parts:
                    m_content = [{"type": "text", "text": text_accumulator or "Review the attached images."}] + image_parts
                    normalized.append({"role": "user", "content": m_content})
                else:
                    normalized.append({"role": "user", "content": text_accumulator or "(empty message)"})

    lang = detect_lang(_last_user_text(compacted))

    # Partition and attach system prompt and skills
    combined_system = "\n\n".join(system_parts).strip()
    system_chunks = partition_system_prompt(combined_system) if combined_system else []
    
    AGENT_IDENTITY = (
        "[AGENT IDENTITY]\n"
        "You are an AUTONOMOUS AI AGENT with tool-use capability (terminal, filesystem, read/write, skills). "
        "You are NOT a passive chat model. You MUST take action via tools instead of only talking. "
        "When a tool is available, call it. Never say 'I cannot access files/terminal' — use the tools. "
        "Never ask the user to paste their project or code: you run inside their environment, so inspect it yourself. "
        "Plan, execute tool calls, inspect results, iterate, then answer."
    )

    formatted_instructions: List[str] = [AGENT_IDENTITY]
    if len(system_chunks) == 1:
        formatted_instructions.append(f"[System Instructions]\n{system_chunks[0]}")
    elif len(system_chunks) > 1:
        total = len(system_chunks)
        for idx, chunk in enumerate(system_chunks, 1):
            if CONFIG.system_prompt_mode == "file":
                # legacy: each part is sent as an attached file block
                formatted_instructions.append(f"[Attached file: system_instructions_part_{idx}.txt]\n````text\n{chunk}\n````")
            else:
                # default: plain message text, no file wrapper / code fence
                formatted_instructions.append(f"[System Instructions {idx}/{total}]\n{chunk}")
    
    if tools_prompt:
        formatted_instructions.append(tools_prompt.strip())

    header_block = "\n\n".join(formatted_instructions).strip()

    if header_block:
        first_user_idx = -1
        for idx, m in enumerate(normalized):
            if m["role"] == "user":
                first_user_idx = idx
                break

        if first_user_idx != -1:
            u_content = normalized[first_user_idx]["content"]
            if isinstance(u_content, str):
                normalized[first_user_idx]["content"] = f"{header_block}\n\n[User Request]\n{u_content}"
            elif isinstance(u_content, list):
                text_part = {"type": "text", "text": f"{header_block}\n\n"}
                normalized[first_user_idx]["content"] = [text_part] + u_content
        else:
            normalized.insert(0, {"role": "user", "content": header_block})

    # Reminder on the last user turn (tools present, or a large agent-harness system prompt)
    if CONFIG.tool_reminder and (tools or len(combined_system) > 2000) and normalized:
        last = normalized[-1]
        if last["role"] == "user":
            reminder = build_tool_reminder(lang)
            if isinstance(last["content"], str):
                last["content"] = f"{last['content']}\n\n{reminder}"
            elif isinstance(last["content"], list):
                last["content"] = last["content"] + [{"type": "text", "text": reminder}]

    # Merge consecutive same-role messages
    cleaned: List[Dict[str, Any]] = []
    for m in normalized:
        if cleaned and cleaned[-1]["role"] == m["role"]:
            prev_content = cleaned[-1]["content"]
            cur_content = m["content"]
            if isinstance(prev_content, str) and isinstance(cur_content, str):
                cleaned[-1]["content"] = f"{prev_content}\n\n{cur_content}"
            elif isinstance(prev_content, list) and isinstance(cur_content, list):
                cleaned[-1]["content"] = prev_content + cur_content
            else:
                cleaned.append(m)
        else:
            cleaned.append(m)

    if cleaned and cleaned[0]["role"] != "user":
        cleaned.insert(0, {"role": "user", "content": "Proceed."})

    return cleaned
