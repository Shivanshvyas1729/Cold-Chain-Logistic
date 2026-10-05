import os
import sys
import json
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime

# =====================================================================
# PATH RESOLUTION & SERVICE CONFIGURATION
# =====================================================================
script_dir = Path(__file__).resolve().parent      # src/
PROJECT_ROOT = script_dir.parent                  # project root
POLICY_DIR = PROJECT_ROOT / "data" / "policy"
CACHE_FILE = PROJECT_ROOT / "data" / "cache" / "ingestion_hash_cache.json"
INGEST_SCRIPT = PROJECT_ROOT / "scripts" / "ingest_sop_pinecone.py"

# Ensure policy directory exists
POLICY_DIR.mkdir(parents=True, exist_ok=True)

# Detect project python executable (prefer local virtualenv if present)
def get_python_executable() -> str:
    """Returns the most appropriate python executable with project dependencies."""
    venv_py_win = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    venv_py_unix = PROJECT_ROOT / ".venv" / "bin" / "python"
    
    if venv_py_win.exists():
        return str(venv_py_win)
    elif venv_py_unix.exists():
        return str(venv_py_unix)
    return sys.executable


# =====================================================================
# 1. HASH CACHE INTROSPECTION
# =====================================================================
def get_hash_cache() -> dict[str, str]:
    """Reads the current ingestion hash cache without modifying it."""
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


# =====================================================================
# 2. FILE MANAGEMENT OPERATIONS (LIST, READ, WRITE, UPLOAD, DELETE)
# =====================================================================
def list_sop_documents() -> list[dict]:
    """
    Scans data/policy/ and returns detailed metadata for each SOP asset,
    including file size, format, modification timestamp, and Pinecone sync status.
    """
    cache = get_hash_cache()
    target_extensions = {".md", ".txt", ".pdf", ".csv", ".xlsx"}
    documents = []

    for filepath in POLICY_DIR.iterdir():
        if filepath.is_file() and filepath.suffix.lower() in target_extensions:
            file_name = filepath.name
            stat = filepath.stat()
            size_kb = round(stat.st_size / 1024, 2)
            mod_time = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

            # Calculate current MD5 hash
            try:
                current_hash = hashlib.md5(filepath.read_bytes()).hexdigest()
            except Exception:
                current_hash = None

            cached_hash = cache.get(file_name)
            is_synced = (cached_hash is not None and cached_hash == current_hash)
            sync_status = "Synced" if is_synced else ("Modified" if cached_hash else "Unindexed")

            documents.append({
                "filename": file_name,
                "format": filepath.suffix.upper().replace(".", ""),
                "size_kb": size_kb,
                "modified": mod_time,
                "current_hash": current_hash,
                "cached_hash": cached_hash,
                "is_synced": is_synced,
                "sync_status": sync_status,
                "editable": filepath.suffix.lower() in {".md", ".txt"}
            })

    # Sort alphabetically by filename
    documents.sort(key=lambda d: d["filename"].lower())
    return documents


def read_sop_text(filename: str) -> str:
    """Reads and returns text content for editable SOP documents (.md, .txt)."""
    target_path = POLICY_DIR / filename
    if not target_path.exists():
        raise FileNotFoundError(f"SOP document not found: {filename}")
    return target_path.read_text(encoding="utf-8", errors="replace")


def save_sop_text(filename: str, content: str) -> bool:
    """Saves updated text content to an existing or new policy file."""
    target_path = POLICY_DIR / filename
    target_path.write_text(content, encoding="utf-8")
    return True


def upload_sop_asset(filename: str, file_bytes: bytes) -> Path:
    """Saves an uploaded file binary to data/policy/."""
    target_path = POLICY_DIR / filename
    target_path.write_bytes(file_bytes)
    return target_path


def delete_sop_asset(filename: str) -> bool:
    """Removes a policy file from data/policy/."""
    target_path = POLICY_DIR / filename
    if target_path.exists():
        target_path.unlink()
        return True
    return False


# =====================================================================
# 3. NON-INVASIVE INGESTION PIPELINE TRIGGER
# =====================================================================
def run_pinecone_ingestion_sync() -> tuple[bool, str]:
    """
    Invokes scripts/ingest_sop_pinecone.py in an isolated child process using
    the project's virtualenv Python. Captures and streams the standard output.
    Does NOT require modifying scripts/ingest_sop_pinecone.py.
    """
    py_exec = get_python_executable()
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        proc = subprocess.run(
            [py_exec, str(INGEST_SCRIPT)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=180
        )
        output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        success = (proc.returncode == 0)
        return success, output.strip()
    except subprocess.TimeoutExpired:
        return False, "Ingestion process timed out after 180 seconds."
    except Exception as e:
        return False, f"Failed to execute ingestion script: {e}"
