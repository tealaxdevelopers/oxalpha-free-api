import json
import re
import uuid
from typing import List, Dict, Any, Optional, Tuple

TOOL_INSTRUCTION_HEADER = """
[AVAILABLE TOOLS]
You have access to the following functions to help answer the user's request:

"""

TOOL_INSTRUCTION_FOOTER = """
[TOOL CALLING FORMAT]
If you need to call a function, you MUST respond ONLY with a JSON block in this exact format:
```json
{
  "tool_call": {
    "name": "<function_name>",
    "arguments": {
      "<param_name>": <param_value>
    }
  }
}
```
If you do not need to call a function, respond directly in natural language without any tool JSON.
"""

def format_tools_prompt(tools: List[Dict[str, Any]]) -> str:
    """Format OpenAI tools array into clear system prompt instructions."""
    if not tools:
        return ""
        
    lines = [TOOL_INSTRUCTION_HEADER]
    for idx, tool in enumerate(tools, 1):
        fn = tool.get("function", {})
        name = fn.get("name", "unknown")
        desc = fn.get("description", "")
        params = fn.get("parameters", {})
        
        lines.append(f"Function {idx}: {name}")
        if desc:
            lines.append(f"  Description: {desc}")
        if params:
            lines.append(f"  Parameters: {json.dumps(params, ensure_ascii=False)}")
        lines.append("")
        
    lines.append(TOOL_INSTRUCTION_FOOTER)
    return "\n".join(lines)

def parse_tool_call(text: str) -> Optional[Tuple[str, Dict[str, Any], str]]:
    """
    Check if model response contains a tool call.
    Returns (tool_name, arguments_dict, remaining_prose) or None.
    """
    if not text:
        return None
        
    # 1. Match ```json ... "tool_call": ... ``` or raw {"tool_call": ...}
    match = re.search(r'```(?:json)?\s*(\{[\s\S]*?"tool_call"[\s\S]*?\})\s*```', text, re.IGNORECASE)
    if not match:
        match = re.search(r'(\{\s*"tool_call"\s*:\s*\{[\s\S]*?\}\s*\})', text)
        
    if match:
        json_str = match.group(1)
        try:
            data = json.loads(json_str)
            tc = data.get("tool_call") or data
            name = tc.get("name")
            args = tc.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    pass
            if name:
                # Prose outside tool call
                prose = (text[:match.start()] + text[match.end():]).strip()
                return name, args, prose
        except Exception:
            pass

    # 2. Match standard XML / DSML format <invoke name="...">...</invoke>
    dsml_match = re.search(r'<invoke\s+name=["\']([^"\']+)["\']>([\s\S]*?)</invoke>', text)
    if dsml_match:
        name = dsml_match.group(1)
        raw_body = dsml_match.group(2).strip()
        args = {}
        try:
            args = json.loads(raw_body)
        except Exception:
            # Try parsing <parameter name="...">value</parameter>
            for pm in re.finditer(r'<parameter\s+name=["\']([^"\']+)["\']>([\s\S]*?)</parameter>', raw_body):
                p_name = pm.group(1)
                p_val = pm.group(2).strip()
                try:
                    args[p_name] = json.loads(p_val)
                except Exception:
                    args[p_name] = p_val
        prose = (text[:dsml_match.start()] + text[dsml_match.end():]).strip()
        return name, args, prose

    return None

def build_openai_tool_calls(name: str, args: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert parsed tool into OpenAI tool_calls structure."""
    return [
        {
            "id": f"call_{uuid.uuid4().hex[:12]}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(args, ensure_ascii=False)
            }
        }
    ]
