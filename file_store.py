import os
import re
import time
import json
import uuid
from typing import Dict, Any, Optional, List

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".files_cache")
META_FILE = os.path.join(CACHE_DIR, "meta.json")

_FILE_ID_RE = re.compile(r"^file-[0-9a-f]{16}$")

# Only these fields are ever returned to API clients. Server-side paths never are.
PUBLIC_FIELDS = ("id", "object", "bytes", "created_at", "filename", "purpose", "status")


def public_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {k: rec[k] for k in PUBLIC_FIELDS if k in rec}


def _safe_filename(name: Optional[str]) -> str:
    name = (name or "").replace("\\", "/").split("/")[-1].strip()
    name = re.sub(r"[\x00-\x1f]", "", name)
    return name[:255] or "uploaded_file.txt"


class FileStore:
    def __init__(self):
        os.makedirs(CACHE_DIR, exist_ok=True)
        self.files: Dict[str, Dict[str, Any]] = {}
        self._load_meta()

    def _path_for(self, file_id: str) -> Optional[str]:
        """Disk path derived from a validated id only (never from stored/user data)."""
        if not _FILE_ID_RE.match(file_id or ""):
            return None
        return os.path.join(CACHE_DIR, file_id)

    def _load_meta(self):
        if os.path.exists(META_FILE):
            try:
                with open(META_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # drop any legacy 'file_path' and invalid ids
                self.files = {
                    fid: {k: v for k, v in rec.items() if k != "file_path"}
                    for fid, rec in loaded.items()
                    if _FILE_ID_RE.match(fid) and isinstance(rec, dict)
                }
            except Exception:
                self.files = {}

    def _save_meta(self):
        try:
            tmp = META_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.files, f, indent=2)
            os.replace(tmp, META_FILE)
        except Exception:
            pass

    def save_file(self, filename: str, content: bytes, purpose: str = "assistants") -> Dict[str, Any]:
        file_id = f"file-{uuid.uuid4().hex[:16]}"
        with open(self._path_for(file_id), "wb") as f:
            f.write(content)

        record = {
            "id": file_id,
            "object": "file",
            "bytes": len(content),
            "created_at": int(time.time()),
            "filename": _safe_filename(filename),
            "purpose": purpose,
            "status": "processed",
        }
        self.files[file_id] = record
        self._save_meta()
        return public_record(record)

    def list_files(self, purpose: Optional[str] = None) -> List[Dict[str, Any]]:
        res = [public_record(r) for r in self.files.values()]
        if purpose:
            res = [r for r in res if r.get("purpose") == purpose]
        return res

    def get_file(self, file_id: str) -> Optional[Dict[str, Any]]:
        rec = self.files.get(file_id)
        return public_record(rec) if rec else None

    def get_file_content(self, file_id: str) -> Optional[bytes]:
        if file_id not in self.files:
            return None
        path = self._path_for(file_id)
        if path and os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()
        return None

    def delete_file(self, file_id: str) -> bool:
        rec = self.files.pop(file_id, None)
        if rec:
            self._save_meta()
            path = self._path_for(file_id)
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
            return True
        return False

file_store = FileStore()
