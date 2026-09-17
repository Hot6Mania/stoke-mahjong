import os
import shutil
import sqlite3
import glob
from datetime import datetime, timezone
from typing import Tuple, Optional, Dict, Any, List

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "stoke_mahjong.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")

def ensure_backup_dir() -> str:
    """Ensure backup directory exists."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    return BACKUP_DIR

def create_backup(
    db_path: str = DB_PATH,
    reason: str = "auto",
    max_keep: int = 30
) -> Tuple[bool, str, Optional[str]]:
    """
    Safely creates a consistent online hot backup using SQLite's backup API.
    Verifies database integrity after copying and rotates older backup files.
    """
    if not os.path.exists(db_path):
        return False, f"데이터베이스 파일이 존재하지 않습니다: {db_path}", None

    ensure_backup_dir()
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
    safe_reason = "".join(c for c in reason if c.isalnum() or c in "_-")
    backup_filename = f"stoke_mahjong_{safe_reason}_{now_str}.db"
    backup_file_path = os.path.join(BACKUP_DIR, backup_filename)

    try:
        # Use SQLite online backup API for crash-safe, lock-free copy
        src_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10.0)
        dst_conn = sqlite3.connect(backup_file_path, timeout=10.0)

        try:
            with dst_conn:
                src_conn.backup(dst_conn, pages=1000)
        finally:
            src_conn.close()
            dst_conn.close()

        # Verify integrity of newly created backup file
        verify_conn = sqlite3.connect(backup_file_path, timeout=5.0)
        try:
            cur = verify_conn.cursor()
            cur.execute("PRAGMA quick_check;")
            res = cur.fetchone()
            if not res or res[0].lower() != "ok":
                cur.execute("PRAGMA integrity_check;")
                full_res = cur.fetchone()
                if not full_res or full_res[0].lower() != "ok":
                    if os.path.exists(backup_file_path):
                        os.remove(backup_file_path)
                    return False, f"백업 무결성 검증 실패: {res or full_res}", None
        finally:
            verify_conn.close()

        # Rotate older backups if count exceeds max_keep
        rotate_backups(max_keep=max_keep)

        return True, f"DB 백업 완료: {backup_filename}", backup_file_path
    except Exception as e:
        if os.path.exists(backup_file_path):
            try:
                os.remove(backup_file_path)
            except Exception:
                pass
        return False, f"DB 백업 예외 발생: {e}", None

def verify_db_integrity(db_path: str = DB_PATH) -> Dict[str, Any]:
    """
    Checks SQLite database health using PRAGMA integrity_check and table row counts.
    """
    if not os.path.exists(db_path):
        return {
            "is_healthy": False,
            "error": "데이터베이스 파일이 존재하지 않습니다.",
            "file_size_bytes": 0,
            "checked_at": datetime.now(timezone.utc).isoformat()
        }

    try:
        file_size = os.path.getsize(db_path)
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10.0)
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA quick_check;")
            quick_res = cur.fetchone()
            quick_ok = bool(quick_res and quick_res[0].lower() == "ok")

            cur.execute("PRAGMA integrity_check;")
            integrity_res = cur.fetchall()
            integrity_ok = bool(integrity_res and len(integrity_res) == 1 and integrity_res[0][0].lower() == "ok")

            # Collect table record counts
            table_counts = {}
            for table in [
                "users", "positions", "market_state",
                "orders_limit", "bankruptcy_applications", "donation_records"
            ]:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {table};")
                    table_counts[table] = cur.fetchone()[0]
                except Exception:
                    table_counts[table] = 0

            return {
                "is_healthy": quick_ok and integrity_ok,
                "quick_check": quick_res[0] if quick_res else "unknown",
                "integrity_check": integrity_res[0][0] if integrity_res else "unknown",
                "file_size_bytes": file_size,
                "file_size_formatted": f"{file_size / 1024:.1f} KB",
                "table_counts": table_counts,
                "checked_at": datetime.now(timezone.utc).isoformat()
            }
        finally:
            conn.close()
    except Exception as e:
        return {
            "is_healthy": False,
            "error": f"검증 중 예외 발생: {e}",
            "file_size_bytes": 0,
            "checked_at": datetime.now(timezone.utc).isoformat()
        }

def list_backups() -> List[Dict[str, Any]]:
    """Lists all stored database backups sorted from newest to oldest."""
    ensure_backup_dir()
    files = glob.glob(os.path.join(BACKUP_DIR, "*.db"))
    result = []
    for f in sorted(files, key=os.path.getmtime, reverse=True):
        try:
            sz = os.path.getsize(f)
            mtime = os.path.getmtime(f)
            dt_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            result.append({
                "filename": os.path.basename(f),
                "path": f,
                "size_bytes": sz,
                "size_formatted": f"{sz / 1024:.1f} KB",
                "created_at": dt_str
            })
        except Exception:
            continue
    return result

def rotate_backups(max_keep: int = 30) -> int:
    """Removes oldest backups if file count exceeds max_keep."""
    ensure_backup_dir()
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, "*.db")), key=os.path.getmtime)
    deleted_count = 0
    if len(files) > max_keep:
        to_delete = files[:len(files) - max_keep]
        for f in to_delete:
            try:
                os.remove(f)
                deleted_count += 1
            except Exception:
                pass
    return deleted_count

def restore_backup(backup_filename: str, db_path: str = DB_PATH) -> Tuple[bool, str]:
    """
    Safely restores database from a designated backup file after verifying integrity.
    Creates a pre-restore backup of the current database before replacing it.
    """
    # Prevent path traversal attacks
    safe_name = os.path.basename(backup_filename)
    target_backup_path = os.path.join(BACKUP_DIR, safe_name)

    if not os.path.exists(target_backup_path):
        return False, f"지정된 백업 파일이 존재하지 않습니다: {safe_name}"

    # Verify backup file health first
    verify = verify_db_integrity(target_backup_path)
    if not verify.get("is_healthy"):
        return False, f"복원 대상 백업 파일의 무결성이 손상되었습니다: {verify.get('error', 'Integrity check failed')}"

    # 1. Create a safety backup of CURRENT db before overwriting
    if os.path.exists(db_path):
        ok, msg, _ = create_backup(db_path, reason="pre_restore_safety")
        if not ok:
            print(f"[Backup] ⚠️ 사전 안전 백업 실패했으나 복원을 계속 진행합니다: {msg}")

    # 2. Perform online restore
    try:
        b_conn = sqlite3.connect(f"file:{target_backup_path}?mode=ro", uri=True, timeout=10.0)
        cur_conn = sqlite3.connect(db_path, timeout=15.0)
        try:
            with cur_conn:
                b_conn.backup(cur_conn, pages=1000)
        finally:
            b_conn.close()
            cur_conn.close()

        # 3. Verify restored active DB
        verify_after = verify_db_integrity(db_path)
        if not verify_after.get("is_healthy"):
            return False, f"복원 후 활성 DB 무결성 검증 실패: {verify_after.get('error')}"

        return True, f"'{safe_name}' 백업으로부터 데이터베이스 복원이 안전하게 완료되었습니다."
    except Exception as e:
        return False, f"복원 작업 중 예외 발생: {e}"
