"""下发回读计划同票（本题空桩已落地）。

不变量：
  已下发 与 回读计划 同成败。禁止「有票无计划」假成功。

两种合法正确性口径（计划写抛错当下票态分叉）：
  回退（默认）：票随计划回退——整事务回滚，票不得停留在已下发，落「下发失败」态，计划行不存在。
  悬挂        ：票可保持已下发，但必须打「缺计划」标记；补建计划前，确认回读与全量晋升一律拒绝。

核证接口统一输出：票号 / 计划有无 / 缺计划标记 / 可否晋升 / valid，
使两口径在失败瞬间都能由 GET 区分（甲：非已下发；乙：已下发但缺计划、不可晋升）。
"""

import json
import os
from datetime import datetime, timezone

from fastapi import HTTPException

口径回退 = "回退"
口径悬挂 = "悬挂"
合法口径 = {口径回退, 口径悬挂, "rollback", "abort", "fail", "A", "甲", "mark", "dangling", "B", "乙"}

_回退别名 = {"回退", "rollback", "abort", "fail", "a", "甲"}
_悬挂别名 = {"悬挂", "mark", "dangling", "b", "乙"}

故障键 = "计划写失败"
_故障词 = ("计划写失败", "计划写错误", "fail_plan", "plan_write", "planwrite", "missing_plan")


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def 规范口径(v: str) -> str:
    s = str(v or "").strip().lower()
    if s in _回退别名:
        return 口径回退
    if s in _悬挂别名:
        return 口径悬挂
    return ""


def 取站规(conn, 键: str, 默认: str = "") -> str:
    r = conn.execute("SELECT 值 FROM 站规 WHERE 键=?", (键,)).fetchone()
    return r["值"] if r else 默认


def 解析显式口径(体: dict | None = None, 查询=None, 头=None) -> str:
    """只从请求体/查询/头取「显式」口径；取不到返回 ''（不回落站规/默认）。"""
    体 = 体 or {}
    for k in ("口径", "计划失败口径", "失败口径", "计划写失败口径", "plan_failure_mode", "on_plan_error", "posture", "mode"):
        p = 规范口径(体.get(k, ""))
        if p:
            return p
    if 查询 is not None:
        for k in ("口径", "计划失败口径", "mode", "posture"):
            try:
                p = 规范口径(查询.get(k, ""))
            except Exception:
                p = ""
            if p:
                return p
    if 头 is not None:
        p = 规范口径(头.get("x-plan-failure-mode", ""))
        if p:
            return p
    return ""


def 解析口径(conn, 体: dict | None = None, 查询=None, 头=None, 开关口径: str = "") -> str:
    """请求显式口径 > 故障开关口径 > 环境变量 > 站规默认 > 内置回退（回退）。

    注意站规「计划失败口径」恒有值（默认回退），因此故障开关自带口径必须在
    站规之前插入，否则会被非空站规值短路。
    """
    显式 = 解析显式口径(体, 查询, 头)
    if 显式:
        return 显式
    sp = 规范口径(开关口径 or "")
    if sp:
        return sp
    env = 规范口径(os.environ.get("FLAGRAIL_PLAN_FAILURE_MODE", "") or os.environ.get("计划失败口径", ""))
    if env:
        return env
    return 规范口径(取站规(conn, "计划失败口径", 口径回退)) or 口径回退


def _去重保序(项) -> list[str]:
    out = []
    for x in 项 or []:
        s = str(x).strip()
        if s and s not in out:
            out.append(s)
    return out


def 解析边缘们(conn, 体: dict | None = None, bucket=None) -> list[str]:
    """计划边缘名册：请求显式 > 分桶规则 > 站规默认 > edge-a/edge-b（与回读样例对齐）。"""
    体 = 体 or {}
    for k in ("边缘们", "计划边缘", "边缘列表", "边缘键们", "edges", "edge_keys", "roster"):
        v = 体.get(k)
        if isinstance(v, list) and v:
            return _去重保序(v)
        if isinstance(v, str) and v.strip():
            return _去重保序(v.split(","))

    规则 = None
    if bucket is not None:
        try:
            规则 = json.loads(bucket["规则"]) if isinstance(bucket["规则"], str) else bucket["规则"]
        except Exception:
            规则 = None
    if isinstance(规则, dict):
        for k in ("边缘们", "edges", "边缘", "edge_keys", "名册"):
            v = 规则.get(k)
            if isinstance(v, list) and v:
                return _去重保序(v)
            if isinstance(v, str) and v.strip():
                return _去重保序(v.split(","))
        for k in ("边缘数", "edge_count", "edges_count"):
            try:
                n = int(规则.get(k))
            except (TypeError, ValueError):
                n = 0
            if n > 0:
                return [f"edge-{i}" for i in range(1, n + 1)]

    默认 = 取站规(conn, "计划默认边缘", "edge-a,edge-b")
    edges = _去重保序(默认.split(","))
    return edges or ["edge-a", "edge-b"]


def _真值(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("1", "true", "yes", "on", "是", "开")


def 请求故障(体: dict | None, 查询=None, 头=None) -> tuple[bool, str]:
    """从请求体/查询/头识别「计划末步注入写失败」。返回 (是否武装, 口径覆盖)。"""
    体 = 体 or {}
    armed = False
    for k in ("注入故障", "故障", "故障注入", "inject_fault", "fault", "inject"):
        v = 体.get(k)
        if v and any(w in str(v).lower() for w in _故障词):
            armed = True
        if isinstance(v, dict) and any(w in json.dumps(v, ensure_ascii=False).lower() for w in _故障词):
            armed = True
    for k in ("计划写失败", "fail_plan_write", "plan_write_fail", "_fail_plan", "fail_plan"):
        if k in 体 and _真值(体.get(k)):
            armed = True
    
    
    for k, v in 体.items():
        kl = str(k).lower()
        if ("fail" in kl and "plan" in kl) or ("计划" in str(k) and "失败" in str(k)):
            if v is True or _真值(v):
                armed = True
        if ("注入" in str(k) and "故障" in str(k)) or kl in ("fault", "inject_fault"):
            if v is True or _真值(v):
                armed = True
    if 查询 is not None:
        try:
            for k, v in 查询.multi_items():
                kl = str(k).lower()
                if ("fail" in kl and "plan" in kl) or "注入故障" in str(k) or "计划写失败" in str(k):
                    if _真值(v) or any(w in str(v).lower() for w in _故障词) or v == "":
                        armed = True
        except Exception:
            pass
    if 头 is not None:
        
        hv = 头.get("x-fault", "") or 头.get("x-inject-fault", "")
        if hv and any(w in hv.lower() for w in _故障词):
            armed = True
        if _真值(头.get("x-fail-plan-write", "")):
            armed = True
    return armed, ""


def 环境故障武装() -> tuple[bool, str]:
    for k in ("FLAGRAIL_FAULT_PLAN_WRITE", "FAIL_PLAN_WRITE", "PLAN_WRITE_FAIL", "计划写失败注入"):
        if _真值(os.environ.get(k, "")):
            return True, 规范口径(os.environ.get("FLAGRAIL_PLAN_FAILURE_MODE", ""))
    return False, ""


def 开关故障(conn) -> tuple[bool, str, int]:
    r = conn.execute("SELECT * FROM 故障开关 WHERE 键=?", (故障键,)).fetchone()
    if not r or not r["启用"]:
        return False, "", 0
    剩余 = int(r["剩余次数"])
    if 剩余 == 0:
        return False, r["口径"], 剩余
    return True, r["口径"], 剩余


def 消耗故障次数(conn) -> None:
    r = conn.execute("SELECT 剩余次数 FROM 故障开关 WHERE 键=?", (故障键,)).fetchone()
    if r and int(r["剩余次数"]) > 0:
        conn.execute("UPDATE 故障开关 SET 剩余次数=剩余次数-1 WHERE 键=?", (故障键,))


def 写计划行(conn, 票号: str, 边缘们: list[str]) -> int:
    n = 0
    for e in 边缘们:
        conn.execute(
            """INSERT INTO 回读计划行(票号, 边缘键, 必需, 状态, 更新时)
               VALUES (?,?,1,'待回读',?)
               ON CONFLICT(票号, 边缘键) DO NOTHING""",
            (票号, e, 此刻()),
        )
        n += 1
    return n


def 计划行数(conn, 票号: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM 回读计划行 WHERE 票号=?", (票号,)).fetchone()[0]


def 核证(conn, 票号: str) -> dict:
    """计划核证：本任务的权威正确性契约。任何 GET 方都据此判断有无假已下发。"""
    t = conn.execute("SELECT * FROM 下发票 WHERE 票号=?", (票号,)).fetchone()
    if not t:
        return {
            "票号": 票号, "存在": False, "计划有无": False, "计划行数": 0,
            "缺计划标记": False, "存储缺计划标记": False, "暗缺计划": False,
            "可否晋升": False, "valid": False,
            "已下发": False, "已全量": False, "状态": "不存在",
            "齐套": False, "计划边缘": [], "已确认边缘": [], "待回读边缘": [], "偏差边缘": [],
            "失败口径": "", "故障说明": "下发票不存在",
        }
    t = dict(t)
    n = 计划行数(conn, 票号)
    有计划 = n > 0
    存储标记 = bool(t.get("缺计划", 0))
    状态 = t["状态"]
    已下发 = 状态 == "已下发"
    已全量 = t.get("晋升状态") == "已全量"
    实际缺计划 = 已下发 and not 有计划
    有效缺标记 = 存储标记 or 实际缺计划

    plan_rows = conn.execute(
        "SELECT 边缘键 FROM 回读计划行 WHERE 票号=? AND 必需=1 ORDER BY 边缘键", (票号,)
    ).fetchall()
    计划边缘 = [r["边缘键"] for r in plan_rows]

    已确认, 偏差边缘 = [], []
    for e in 计划边缘:
        cert = conn.execute(
            """SELECT 结果, 所见版本键 FROM 回读证
               WHERE 票号=? AND 边缘键=? ORDER BY 回读时 DESC LIMIT 1""",
            (票号, e),
        ).fetchone()
        if not cert:
            continue
        if cert["结果"] == "确认" and cert["所见版本键"] == t["版本键"]:
            已确认.append(e)
        elif cert["结果"] == "偏差":
            偏差边缘.append(e)

    待回读 = [e for e in 计划边缘 if e not in 已确认]
    齐套 = 有计划 and bool(计划边缘) and not 待回读 and not 偏差边缘

    
    valid = bool(已下发 and 有计划 and not 存储标记)
    
    可否晋升 = bool(valid and 齐套)

    return {
        "票号": 票号,
        "存在": True,
        "计划有无": 有计划,
        "计划行数": n,
        
        "缺计划标记": 有效缺标记,
        "存储缺计划标记": 存储标记,
        "暗缺计划": 实际缺计划 and not 存储标记,
        "可否晋升": 可否晋升,
        "valid": valid,
        "已下发": 已下发,
        "已全量": 已全量,
        "状态": 状态,
        "齐套": 齐套,
        "计划边缘": 计划边缘,
        "已确认边缘": 已确认,
        "待回读边缘": 待回读,
        "偏差边缘": 偏差边缘,
        "版本键": t["版本键"],
        "桶键": t["桶键"],
        "失败口径": t.get("失败口径", ""),
        "故障说明": t.get("故障说明", ""),
        "晋升状态": t.get("晋升状态", "未晋升"),
    }


def 列核证(conn) -> list[dict]:
    票s = [r["票号"] for r in conn.execute("SELECT 票号 FROM 下发票 ORDER BY 下发时 DESC")]
    return [核证(conn, x) for x in 票s]


def 补建计划(体: dict) -> dict:
    """为缺计划票补建同票计划行；成功后清缺计划标记。失败态票可借此重新在轨。"""
    from app.db import 连接

    票号 = 体["票号"]
    conn = 连接()
    conn.execute("PRAGMA busy_timeout=15000")
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        t = conn.execute("SELECT * FROM 下发票 WHERE 票号=?", (票号,)).fetchone()
        if not t:
            raise HTTPException(404, f"下发票不存在:{票号}")
        if t["状态"] in ("已回滚", "已失效"):
            raise HTTPException(400, f"票已终态 {t['状态']}，不可补计划；请重发新票")
        bucket = conn.execute("SELECT * FROM 分桶规 WHERE 桶键=?", (t["桶键"],)).fetchone()
        edges = 解析边缘们(conn, 体, bucket)
        if not edges:
            raise HTTPException(400, "计划边缘为空，无法补建")
        写计划行(conn, 票号, edges)
        if t["状态"] in ("下发失败", "待下发"):
            conn.execute(
                """UPDATE 下发票 SET 状态='已下发', 缺计划=0, 失败口径='', 故障说明='',
                   下发时=?, 世代=世代+1 WHERE 票号=?""",
                (此刻(), 票号),
            )
            conn.execute("UPDATE 开关版本 SET 状态='灰度中' WHERE 版本键=?", (t["版本键"],))
            命运 = "补计划重下发"
        else:
            conn.execute(
                "UPDATE 下发票 SET 缺计划=0, 失败口径='', 故障说明='' WHERE 票号=?", (票号,)
            )
            命运 = "补建计划"
        conn.execute(
            "INSERT INTO 命运账(对象类型, 对象键, 命运, 时刻, 说明) VALUES ('下发票',?,?,?,?)",
            (票号, 命运, 此刻(), "补建同票回读计划并清除缺计划标记"),
        )
        conn.commit()
        return 核证(conn, 票号)
    except HTTPException:
        _安全回滚(conn)
        raise
    except Exception as e:
        _安全回滚(conn)
        raise HTTPException(500, f"补建计划失败闭:{e}")
    finally:
        conn.close()


def _安全回滚(conn) -> None:
    try:
        conn.execute("ROLLBACK")
    except Exception:
        pass
