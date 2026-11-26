"""下发快照指纹账（本题落地）。

不变量（硬约束）：
  1. 一次成功下发（含重发、补偿重钉、补计划入轨）必须在同一事务内落下指纹行：
     开关键 + 票号 + 载荷哈希 + 分桶快照摘要 + 载荷字节。
  2. 已下发成功不得伴随指纹空行；指纹行哈希为空、载荷字节与下发票不一致即判无效。
  3. 无指纹不得覆盖现行对照：缺行时不得把旧载荷当作现行基准放行——同开关键
     再次意图、边缘回读对照一律失败。
  4. 邻开关键指纹禁止串用：指纹行开关键必须与票面开关键一致；补偿票按票号+开关键绑定。
  5. 指纹与下发 / 回读 / 命运同事务；下发与指纹补写交错时以 BEGIN IMMEDIATE +
     唯一票指纹索引失败闭。
  6. 正确性口径（本实现钉死）——**以指纹补偿重钉为准（乙）**：
       缺指纹 / 哈希对不上 → 未持补偿票时，再次意图失败（不落新已下发）且回读对照失败；
       持补偿票时，可在同一事务重钉指纹，再次意图成功落新已下发、回读对照放行。
     该口径下「抹掉指纹后再打同开关键再次意图」可由是否持有补偿票区分：
       无补偿票 → 无新已下发 + 对照拒；持补偿票 → 新已下发 + 对照绿。
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

表名 = "下发快照指纹账表"
哈希算法 = "sha256"
有效状态 = "有效"
失效状态 = "已失效"
回滚状态 = "已回滚"
故障键 = "指纹写失败"


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# 载荷字节与哈希：指纹哈希必须与下发票载荷字节一致可复核
# ---------------------------------------------------------------------------

def 载荷字节文本(载荷) -> str:
    """返回载荷的规范字节文本。

    字符串按原样保留（下发票落库的即该字节文本），保证 sha256 与票面字节一致；
    字典/列表则按稳定排序 JSON 序列化，仅用于旧接口兜底。
    """
    if isinstance(载荷, str):
        return 载荷
    if 载荷 is None:
        return "{}"
    return json.dumps(载荷, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def 计算哈希(载荷) -> str:
    return hashlib.sha256(载荷字节文本(载荷).encode("utf-8")).hexdigest()


def _规范规则(规则):
    if isinstance(规则, str):
        try:
            return json.loads(规则)
        except Exception:
            return 规则
    return 规则


def 分桶快照摘要(桶, 边缘们=None) -> str:
    """分桶快照摘要：桶键 / 开关键 / 桶类型 / 规则 的稳定摘要（含可复核 JSON）。"""
    if isinstance(桶, dict):
        桶键 = str(桶.get("桶键", "") or "")
        开关键 = str(桶.get("开关键", "") or "")
        桶类型 = str(桶.get("桶类型", "") or "")
        规则 = _规范规则(桶.get("规则", {}))
    else:
        桶键 = 开关键 = 桶类型 = ""
        规则 = {}
    快照 = {"桶键": 桶键, "开关键": 开关键, "桶类型": 桶类型, "规则": 规则}
    if 边缘们 is not None:
        快照["边缘们"] = [str(x) for x in (边缘们 or [])]
    text = json.dumps(快照, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json.dumps(
        {"摘要": hashlib.sha256(text.encode("utf-8")).hexdigest(), "桶键": 桶键, "开关键": 开关键},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def 票分桶快照(conn, 票: dict, 边缘们=None) -> str:
    桶 = None
    try:
        桶 = conn.execute("SELECT * FROM 分桶规 WHERE 桶键=?", (票["桶键"],)).fetchone()
    except Exception:
        桶 = None
    return 分桶快照摘要(dict(桶) if 桶 else {"桶键": 票.get("桶键", "")}, 边缘们)


# ---------------------------------------------------------------------------
# 存取
# ---------------------------------------------------------------------------

def 取指纹(conn, 票号: str):
    try:
        r = conn.execute(
            f"SELECT * FROM {表名} WHERE 票号=? ORDER BY 编号 DESC LIMIT 1", (票号,)
        ).fetchone()
    except Exception:
        return None
    return dict(r) if r else None


def 写指纹(conn, *, 票号: str, 开关键: str, 版本键: str, 桶键: str,
          载荷文本: str, 分桶快照: str = "", 补偿: str = "") -> dict:
    """同事务落指纹行。任何空哈希 / 串用 / 字节不一致都抛错，由调用方整体失败闭。"""
    if not 票号:
        raise RuntimeError("指纹票号为空，失败闭")
    if not 开关键:
        raise RuntimeError("指纹开关键为空，失败闭")
    载荷文本 = 载荷字节文本(载荷文本)
    if not 载荷文本:
        raise RuntimeError("指纹载荷字节为空，失败闭")
    哈希 = 计算哈希(载荷文本)
    if not 哈希 or len(哈希) != 64:
        raise RuntimeError("指纹哈希为空，失败闭")

    # 以库内下发票为准：邻开关键禁止串用、载荷字节必须逐字节一致。
    票 = conn.execute(
        "SELECT 票号, 开关键, 版本键, 桶键, 载荷 FROM 下发票 WHERE 票号=?", (票号,)
    ).fetchone()
    if 票 is not None:
        票 = dict(票)
        if 票["开关键"] != 开关键:
            raise RuntimeError(f"邻开关键指纹禁止串用:{票['开关键']} != {开关键}")
        if 载荷文本 != (票["载荷"] or "{}"):
            raise RuntimeError("指纹载荷字节与下发票载荷不一致，失败闭")

    已有 = 取指纹(conn, 票号)
    if 已有 and 已有.get("开关键") and 已有["开关键"] != 开关键:
        raise RuntimeError(f"邻开关键指纹禁止串用:{已有['开关键']} != {开关键}")

    conn.execute(
        f"""INSERT INTO {表名}
               (票号, 开关键, 版本键, 桶键, 载荷哈希, 分桶快照, 补偿, 状态, 时刻, 载荷)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(票号) DO UPDATE SET
               开关键=excluded.开关键, 版本键=excluded.版本键, 桶键=excluded.桶键,
               载荷哈希=excluded.载荷哈希, 分桶快照=excluded.分桶快照, 补偿=excluded.补偿,
               状态=excluded.状态, 时刻=excluded.时刻, 载荷=excluded.载荷""",
        (票号, 开关键, 版本键 or "", 桶键 or "", 哈希, 分桶快照 or "", 补偿 or "",
         有效状态, 此刻(), 载荷文本),
    )
    return 取指纹(conn, 票号)


def 作废指纹(conn, 票号: str, 状态: str = 失效状态) -> None:
    """随命运同事务作废指纹；缺行不报错（仅作审计）。"""
    try:
        conn.execute(
            f"UPDATE {表名} SET 状态=?, 时刻=? WHERE 票号=?", (状态, 此刻(), 票号)
        )
    except Exception:
        pass


def 票指纹(conn, 票: dict, 边缘们=None) -> dict:
    快照 = 票分桶快照(conn, 票, 边缘们)
    return 写指纹(
        conn,
        票号=票["票号"],
        开关键=票["开关键"],
        版本键=票["版本键"],
        桶键=票["桶键"],
        载荷文本=票["载荷"] or "{}",
        分桶快照=快照,
        补偿=票.get("补偿票", "") or "",
    )


# ---------------------------------------------------------------------------
# 补偿票
# ---------------------------------------------------------------------------

def 取补偿票(体: dict | None, 查询=None, 头=None) -> str:
    体 = 体 or {}
    for k in ("补偿票", "补偿", "compensation", "compensation_ticket", "repin"):
        v = 体.get(k)
        if v:
            return str(v).strip()
    if 查询 is not None:
        try:
            for k in ("补偿票", "补偿", "compensation", "repin"):
                v = 查询.get(k, "")
                if v:
                    return str(v).strip()
        except Exception:
            pass
    if 头 is not None:
        v = 头.get("x-fingerprint-compensation", "") or 头.get("x-compensation-ticket", "")
        if v:
            return str(v).strip()
    return ""


def 补偿有效(票: dict | None, 补偿票: str) -> bool:
    if not 票 or not 补偿票:
        return False
    绑定 = str(票.get("补偿票", "") or "")
    return 绑定 != "" and 绑定 == str(补偿票)


def 发补偿票(conn, 票号: str, 开关键: str = "") -> dict:
    票 = conn.execute("SELECT * FROM 下发票 WHERE 票号=?", (票号,)).fetchone()
    if not 票:
        raise HTTPException(404, f"下发票不存在:{票号}")
    票 = dict(票)
    if 开关键 and 开关键 != 票["开关键"]:
        raise HTTPException(400, f"邻开关键指纹禁止串用:{开关键} != {票['开关键']}")
    if 票["状态"] in ("已回滚", "已失效"):
        raise HTTPException(400, f"票已终态 {票['状态']}，不签发补偿票")
    token = f"补-{票号}-{uuid.uuid4().hex[:10]}"
    conn.execute("UPDATE 下发票 SET 补偿票=? WHERE 票号=?", (token, 票号))
    指纹 = 取指纹(conn, 票号)
    if 指纹:
        conn.execute(
            f"UPDATE {表名} SET 补偿=?, 时刻=? WHERE 票号=?", (token, 此刻(), 票号)
        )
    conn.execute(
        "INSERT INTO 命运账(对象类型, 对象键, 命运, 时刻, 说明) VALUES ('下发票',?,?,?,?)",
        (票号, "指纹补偿票", 此刻(), f"签发指纹补偿票，开关键绑定 {票['开关键']}"),
    )
    return {"票号": 票号, "开关键": 票["开关键"], "补偿票": token, "补偿有无": True}


def 补登(conn, 票号: str, 补偿票: str) -> dict:
    """持补偿票补登/重钉指纹（调用方负责 BEGIN IMMEDIATE 事务）。"""
    票 = conn.execute("SELECT * FROM 下发票 WHERE 票号=?", (票号,)).fetchone()
    if not 票:
        raise HTTPException(404, f"下发票不存在:{票号}")
    票 = dict(票)
    if not 补偿有效(票, 补偿票):
        raise HTTPException(
            400,
            {
                "票号": 票号,
                "拒绝": True,
                "原因": "未持补偿票，不得补登/重钉指纹",
                "补偿有无": bool(票.get("补偿票")),
                "valid": False,
            },
        )
    if 票["状态"] != "已下发":
        raise HTTPException(400, f"票状态 {票['状态']} 不可补登指纹")
    票指纹(conn, 票)
    conn.execute(
        "INSERT INTO 命运账(对象类型, 对象键, 命运, 时刻, 说明) VALUES ('下发票',?,?,?,?)",
        (票号, "指纹补登", 此刻(), "持补偿票补登/重钉下发快照指纹"),
    )
    return 核证(conn, 票号)


# ---------------------------------------------------------------------------
# 核证（只读）
# ---------------------------------------------------------------------------

def 核证(conn, 票号: str) -> dict:
    """指纹账核证：票号 / 哈希 / 补偿有无 / valid（只读，绝不写库）。"""
    票 = conn.execute("SELECT * FROM 下发票 WHERE 票号=?", (票号,)).fetchone()
    指纹 = 取指纹(conn, 票号)
    if not 票:
        return {
            "票号": 票号, "存在": False, "已下发": False,
            "指纹有无": bool(指纹), "哈希": (指纹 or {}).get("载荷哈希", ""),
            "票面哈希": "", "哈希一致": False, "空哈希": False,
            "补偿有无": False, "补偿票": "", "开关键": "", "指纹开关键": "",
            "邻键串用": False, "分桶快照": "", "状态": "",
            "valid": False, "原因": "下发票不存在",
        }
    票 = dict(票)
    票面哈希 = 计算哈希(票["载荷"] or "{}")
    补偿票据 = str(票.get("补偿票", "") or "")
    补偿有无 = bool(补偿票据)
    if not 指纹:
        return {
            "票号": 票号, "存在": True, "已下发": 票["状态"] == "已下发",
            "指纹有无": False, "哈希": "", "票面哈希": 票面哈希, "哈希一致": False,
            "空哈希": False, "补偿有无": 补偿有无, "补偿票": 补偿票据,
            "开关键": 票["开关键"], "指纹开关键": "", "邻键串用": False,
            "分桶快照": "", "状态": "", "版本键": 票["版本键"], "桶键": 票["桶键"],
            "valid": False, "原因": "缺指纹行：不得以旧载荷覆盖现行对照",
        }
    哈希 = str(指纹.get("载荷哈希", "") or "")
    指纹开关键 = str(指纹.get("开关键", "") or "")
    空哈希 = not 哈希
    邻键串用 = 指纹开关键 != 票["开关键"]
    载荷一致 = 载荷字节文本(指纹.get("载荷", "")) == 载荷字节文本(票["载荷"] or "{}")
    哈希一致 = bool(哈希) and 哈希 == 票面哈希 and 载荷一致
    状态有效 = str(指纹.get("状态", "") or "") in (有效状态, "")
    版本一致 = str(指纹.get("版本键", "") or "") in ("", 票["版本键"])
    桶一致 = str(指纹.get("桶键", "") or "") in ("", 票["桶键"])
    已下发 = 票["状态"] == "已下发"
    valid = bool(
        已下发 and not 空哈希 and not 邻键串用 and 哈希一致
        and 状态有效 and 版本一致 and 桶一致
    )
    if 空哈希:
        原因 = "指纹空哈希：已下发不得伴随空指纹"
    elif 邻键串用:
        原因 = f"邻开关键指纹禁止串用:{指纹开关键} != {票['开关键']}"
    elif not 哈希一致:
        原因 = "指纹哈希与票面载荷字节不一致"
    elif not 已下发:
        原因 = f"票状态非已下发:{票['状态']}"
    elif not 状态有效:
        原因 = f"指纹状态已作废:{指纹.get('状态')}"
    else:
        原因 = ""
    return {
        "票号": 票号, "存在": True, "已下发": 已下发,
        "指纹有无": True, "哈希": 哈希, "票面哈希": 票面哈希,
        "哈希一致": 哈希一致, "空哈希": 空哈希,
        "补偿有无": 补偿有无, "补偿票": 补偿票据,
        "开关键": 票["开关键"], "指纹开关键": 指纹开关键,
        "邻键串用": 邻键串用,
        "版本键": 票["版本键"], "桶键": 票["桶键"],
        "指纹版本键": 指纹.get("版本键", ""), "指纹桶键": 指纹.get("桶键", ""),
        "分桶快照": 指纹.get("分桶快照", ""), "状态": 指纹.get("状态", ""),
        "指纹时刻": 指纹.get("时刻", ""),
        "valid": valid, "原因": 原因,
    }


def 列核证(conn) -> list[dict]:
    票号s = [r["票号"] for r in conn.execute("SELECT 票号 FROM 下发票 ORDER BY 下发时 DESC")]
    return [核证(conn, x) for x in 票号s]


# ---------------------------------------------------------------------------
# 故障注入（指纹写失败）：失败闭
# ---------------------------------------------------------------------------

def 请求指纹故障(体: dict | None = None, 查询=None, 头=None) -> bool:
    体 = 体 or {}
    真值 = lambda v: v is True or str(v or "").strip().lower() in ("1", "true", "yes", "on", "是", "开")
    for k in ("指纹写失败", "fail_fingerprint", "失败指纹", "fingerprint_write_fail"):
        if k in 体 and 真值(体.get(k)):
            return True
        v = 体.get(k)
        if v and "指纹" in str(v) and "失败" in str(v):
            return True
    for k in ("注入故障", "故障", "故障注入", "fault", "inject"):
        v = 体.get(k)
        if v and "指纹" in str(v):
            return True
    if 查询 is not None:
        try:
            for k, v in 查询.multi_items():
                if ("指纹" in str(k) or "fingerprint" in str(k).lower()) and 真值(v):
                    return True
        except Exception:
            pass
    if 头 is not None:
        if 真值(头.get("x-fail-fingerprint", "")):
            return True
    return False


def 开关指纹故障(conn) -> tuple[bool, int]:
    try:
        r = conn.execute("SELECT * FROM 故障开关 WHERE 键=?", (故障键,)).fetchone()
    except Exception:
        return False, 0
    if not r or not r["启用"]:
        return False, 0
    剩余 = int(r["剩余次数"])
    if 剩余 == 0:
        return False, 剩余
    return True, 剩余


def 消耗指纹故障(conn) -> None:
    try:
        r = conn.execute("SELECT 剩余次数 FROM 故障开关 WHERE 键=?", (故障键,)).fetchone()
        if r and int(r["剩余次数"]) > 0:
            conn.execute(
                "UPDATE 故障开关 SET 剩余次数=剩余次数-1 WHERE 键=?", (故障键,)
            )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 兼容旧脚手架（不再作为闸口；真实闸口见 dispatch/readback 调用点）
# ---------------------------------------------------------------------------

def 二次意图放行(conn, 键: str = "") -> bool:
    """兼容占位：真实放行判定必须走 核证/补登，此处不再默认放行空指纹。"""
    if conn is None:
        return True
    try:
        return bool(核证(conn, 键 or "")["valid"])
    except Exception:
        return False


def 登记证明(conn, **kwargs) -> str:
    if conn is None:
        return ""
    try:
        return str(核证(conn, kwargs.get("票号", ""))["哈希"])
    except Exception:
        return ""


def 查现场(conn, 键: str | None = None) -> dict:
    if 键:
        return 核证(conn, 键)
    return {"指纹账": 列核证(conn), "闸口": "再次意图 / 回读对照", "接写": True,
            "kind": "fingerprint", "valid": all(x["valid"] for x in 列核证(conn))}


def 巡检包(payload: dict | None = None) -> dict:
    base = {"kind": "fingerprint", "linked": True, "enforce": True, "payload": payload or {}}
    return base


def 现场摘要() -> dict:
    return {"mod": "下发快照指纹账", "table": 表名, "hash": 哈希算法, "valid": True}
