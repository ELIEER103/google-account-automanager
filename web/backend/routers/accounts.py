"""
账号管理 API
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query

import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from database import DBManager
from create_window import get_browser_list
from ..schemas import (
    Account, AccountCreate, AccountUpdate, AccountListResponse,
    AccountStatus, ImportRequest, ExportResponse
)

router = APIRouter()


import re


def _is_2fa_secret(value: str) -> bool:
    """判断是否为 2FA 密钥（Base32 格式）"""
    if not value:
        return False
    # 移除空格
    clean = value.replace(" ", "").strip().upper()
    # Base32: 只包含 A-Z 和 2-7，长度 16-32
    if len(clean) < 16 or len(clean) > 32:
        return False
    return bool(re.match(r'^[A-Z2-7]+$', clean))


def _is_email(value: str) -> bool:
    """判断是否为邮箱格式"""
    if not value:
        return False
    return '@' in value and '.' in value


def _split_account_line(line: str, separator: str) -> List[str]:
    if separator and separator in line:
        parts = line.split(separator)
    else:
        parts = None
        for sep in ['----', '---', '|', ',', ';', '\t']:
            if sep in line:
                parts = line.split(sep)
                break
        if parts is None:
            parts = line.split()
    return [p.strip() for p in parts if p.strip()]


def _parse_account_line(line: str, separator: str) -> dict:
    """
    智能解析账号行，支持多种格式：

    格式1 (4字段): 邮箱----密码----辅助邮箱----2FA密钥
    格式2 (3字段): 邮箱----密码----2FA密钥
    格式3 (2字段): 邮箱----密码
    格式4 (1字段): 邮箱

    Returns:
        {"email": str, "password": str|None, "recovery_email": str|None, "secret_key": str|None}
    """
    parts = _split_account_line(line, separator)

    result = {
        "email": None,
        "password": None,
        "recovery_email": None,
        "secret_key": None,
    }

    if len(parts) < 1:
        return result

    # 第1个字段：邮箱
    result["email"] = parts[0].strip()

    if len(parts) < 2:
        return result

    # 第2个字段：密码
    result["password"] = parts[1].strip()

    if len(parts) == 2:
        return result

    if len(parts) == 3:
        # 3字段格式：判断第3个字段是辅助邮箱还是2FA密钥
        third = parts[2].strip()
        if _is_2fa_secret(third):
            # 邮箱----密码----2FA密钥
            result["secret_key"] = third
        elif _is_email(third):
            # 邮箱----密码----辅助邮箱
            result["recovery_email"] = third
        else:
            # 无法判断，默认当作2FA密钥（兼容旧逻辑）
            result["secret_key"] = third
        return result

    if len(parts) >= 4:
        # 4字段格式：邮箱----密码----辅助邮箱----2FA密钥
        result["recovery_email"] = parts[2].strip() if parts[2].strip() else None
        result["secret_key"] = parts[3].strip() if parts[3].strip() else None
        return result

    return result


@router.get("", response_model=AccountListResponse)
async def list_accounts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[AccountStatus] = None,
    search: Optional[str] = None,
):
    """获取账号列表（分页、筛选、搜索）"""
    all_accounts = DBManager.get_all_accounts()

    # 筛选状态
    if status:
        all_accounts = [a for a in all_accounts if a.get("status") == status.value]

    # 搜索邮箱
    if search:
        search_lower = search.lower()
        all_accounts = [a for a in all_accounts if search_lower in a.get("email", "").lower()]

    # 分页
    total = len(all_accounts)
    start = (page - 1) * page_size
    end = start + page_size
    items = all_accounts[start:end]

    try:
        browsers = get_browser_list(page=0, pageSize=1000) or []
        browser_map = {}
        for b in browsers:
            email = (b.get("userName") or "").strip().lower()
            if email and email not in browser_map:
                browser_map[email] = b

        for item in items:
            email = (item.get("email") or "").strip()
            if not email:
                continue
            key = email.lower()
            browser = browser_map.get(key)
            if browser:
                browser_id = browser.get("id")
                if browser_id and item.get("browser_id") != browser_id:
                    DBManager.save_browser_config(email, browser_id, browser)
                item["browser_id"] = browser_id
            else:
                if item.get("browser_id"):
                    DBManager.clear_browser_id(email)
                item["browser_id"] = None
    except Exception:
        pass

    return AccountListResponse(total=total, items=items)


@router.get("/stats")
async def get_stats():
    """获取账号统计信息"""
    all_accounts = DBManager.get_all_accounts()
    stats = {
        "total": len(all_accounts),
        "pending": 0,
        "eligible": 0,
        "link_ready": 0,
        "verified": 0,
        "bound": 0,
        "subscribed": 0,
        "family_pro": 0,
        "ineligible": 0,
        "error": 0,
        "wrong": 0,
        "with_browser": 0,
    }

    for account in all_accounts:
        status = account.get("status", "pending")
        if status in stats:
            stats[status] += 1
        if account.get("browser_id"):
            stats["with_browser"] += 1

    return stats


@router.get("/{email}", response_model=Account)
async def get_account(email: str):
    """获取单个账号详情"""
    account = DBManager.get_account_by_email(email)
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    return account


@router.post("", response_model=Account)
async def create_account(data: AccountCreate):
    """创建新账号"""
    existing = DBManager.get_account_by_email(data.email)
    if existing:
        raise HTTPException(status_code=400, detail="账号已存在")

    DBManager.upsert_account(
        email=data.email,
        password=data.password,
        recovery_email=data.recovery_email,
        secret_key=data.secret_key,
        status="pending"
    )

    return DBManager.get_account_by_email(data.email)


@router.put("/{email}", response_model=Account)
async def update_account(email: str, data: AccountUpdate):
    """更新账号信息"""
    existing = DBManager.get_account_by_email(email)
    if not existing:
        raise HTTPException(status_code=404, detail="账号不存在")

    DBManager.upsert_account(
        email=email,
        password=data.password,
        recovery_email=data.recovery_email,
        secret_key=data.secret_key,
        status=data.status.value if data.status else None,
        message=data.message
    )

    return DBManager.get_account_by_email(email)


@router.delete("/{email}")
async def delete_account(email: str):
    """删除账号"""
    existing = DBManager.get_account_by_email(email)
    if not existing:
        raise HTTPException(status_code=404, detail="账号不存在")

    # 使用数据库连接删除
    from database import lock
    import sqlite3

    with lock:
        conn = DBManager.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM accounts WHERE email = ?", (email,))
        conn.commit()
        conn.close()

    return {"message": "删除成功"}


@router.post("/batch/delete")
async def delete_accounts_batch(emails: List[str]):
    """批量删除账号"""
    if not emails:
        raise HTTPException(status_code=400, detail="请提供要删除的账号列表")

    from database import lock

    deleted = 0
    errors = []

    with lock:
        conn = DBManager.get_connection()
        cursor = conn.cursor()
        for email in emails:
            try:
                cursor.execute("DELETE FROM accounts WHERE email = ?", (email,))
                if cursor.rowcount > 0:
                    deleted += 1
                else:
                    errors.append(f"{email}: 账号不存在")
            except Exception as e:
                errors.append(f"{email}: {str(e)}")
        conn.commit()
        conn.close()

    return {"deleted": deleted, "errors": errors}


@router.delete("/batch/wrong")
async def delete_wrong_accounts():
    """删除所有密码错误(wrong)状态的账号"""
    from database import lock

    with lock:
        conn = DBManager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM accounts WHERE status = 'wrong'")
        count = cursor.fetchone()[0]
        cursor.execute("DELETE FROM accounts WHERE status = 'wrong'")
        conn.commit()
        conn.close()

    return {"deleted": count, "message": f"已删除 {count} 个密码错误的账号"}


@router.delete("/batch/all")
async def delete_all_accounts():
    """删除所有账号"""
    from database import lock

    with lock:
        conn = DBManager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM accounts")
        count = cursor.fetchone()[0]
        cursor.execute("DELETE FROM accounts")
        conn.commit()
        conn.close()

    return {"deleted": count, "message": f"已删除所有 {count} 个账号"}


@router.post("/import")
async def import_accounts(data: ImportRequest):
    """
    批量导入账号

    支持格式：
    - 4字段: 邮箱----密码----辅助邮箱----2FA密钥
    - 3字段: 邮箱----密码----2FA密钥 (自动识别)
    - 2字段: 邮箱----密码
    - 1字段: 邮箱
    """
    lines = data.content.strip().split("\n")
    imported = 0
    errors = []

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # 使用智能解析
        parsed = _parse_account_line(line, data.separator)

        if not parsed.get("email"):
            continue

        try:
            DBManager.upsert_account(
                email=parsed["email"],
                password=parsed["password"],
                recovery_email=parsed["recovery_email"],
                secret_key=parsed["secret_key"],
                status="pending"
            )
            imported += 1
        except Exception as e:
            errors.append(f"{parsed['email']}: {str(e)}")

    return {"imported": imported, "errors": errors}

    return {"imported": imported, "errors": errors}


@router.get("/export/all", response_model=ExportResponse)
async def export_accounts(status: Optional[AccountStatus] = None):
    """导出账号"""
    if status:
        accounts = DBManager.get_accounts_by_status(status.value)
    else:
        accounts = DBManager.get_all_accounts()

    lines = []
    for acc in accounts:
        parts = [acc.get("email", "")]
        if acc.get("password"):
            parts.append(acc["password"])
        if acc.get("recovery_email"):
            parts.append(acc["recovery_email"])
        if acc.get("secret_key"):
            parts.append(acc["secret_key"])
        lines.append("----".join(parts))

    return ExportResponse(content="\n".join(lines), count=len(lines))


@router.get("/export/2fa", response_model=ExportResponse)
async def export_2fa():
    """导出 2FA 为 otpauth URI 格式"""
    from urllib.parse import quote

    accounts = DBManager.get_all_accounts()
    lines = []

    for acc in accounts:
        secret_key = acc.get("secret_key", "").strip()
        if not secret_key:
            continue

        email = acc.get("email", "")
        password = acc.get("password", "")

        # 提取邮箱前缀
        email_prefix = email.split("@")[0] if "@" in email else email

        # 构建 otpauth URI
        # 格式: otpauth://totp/aaaaa:bbbbb%40gmail.com?secret=ccccc&issuer=aaaaa
        # aaaaa = 密码, bbbbb = 邮箱前缀, ccccc = 2FA密钥
        encoded_email = quote(email, safe='')
        line = f"otpauth://totp/{password}:{encoded_email}?secret={secret_key}&issuer={password}"
        lines.append(line)

    return ExportResponse(content="\n".join(lines), count=len(lines))
