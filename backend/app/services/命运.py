from datetime import datetime, timezone

from app.db import 连接
from fastapi import HTTPException

from app.modules import 下发快照指纹账 as 指纹账


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def 回滚票(体: dict) -> dict:
    """回滚与指纹作废同事务：回滚票不得再凭旧指纹放行对照。"""
    conn = 连接()
    conn.execute("PRAGMA busy_timeout=15000")
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        票号 = 体["票号"]
        ticket = conn.execute("SELECT * FROM 下发票 WHERE 票号=?", (票号,)).fetchone()
        if not ticket:
            conn.execute("ROLLBACK")
            raise HTTPException(400, f"下发票不存在:{票号}")
        if ticket["状态"] == "已回滚":
            conn.commit()
            return {"票号": 票号, "状态": "已回滚", "幂等": True}
        conn.execute("UPDATE 下发票 SET 状态='已回滚' WHERE 票号=?", (票号,))
        指纹账.作废指纹(conn, 票号, 指纹账.回滚状态)
        conn.execute("UPDATE 开关版本 SET 状态='已回滚' WHERE 版本键=?", (ticket["版本键"],))
        conn.execute(
            "INSERT INTO 命运账(对象类型, 对象键, 命运, 时刻, 说明) VALUES (?,?,?,?,?)",
            ("下发票", 票号, "回滚", 此刻(), 体.get("说明", "灰度回滚")),
        )
        conn.execute(
            "INSERT INTO 命运账(对象类型, 对象键, 命运, 时刻, 说明) VALUES (?,?,?,?,?)",
            ("开关版本", ticket["版本键"], "回滚", 此刻(), 体.get("说明", "随票回滚")),
        )
        conn.commit()
        return {"票号": 票号, "状态": "已回滚", "幂等": False}
    except HTTPException:
        _安全回滚(conn)
        raise
    except Exception as e:
        _安全回滚(conn)
        raise HTTPException(500, f"回滚异常，已失败闭:{e}")
    finally:
        conn.close()


def 失效版本(体: dict) -> dict:
    """失效与指纹作废同事务：失效票不得再凭旧指纹放行对照。"""
    conn = 连接()
    conn.execute("PRAGMA busy_timeout=15000")
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        版本键 = 体["版本键"]
        ver = conn.execute("SELECT * FROM 开关版本 WHERE 版本键=?", (版本键,)).fetchone()
        if not ver:
            conn.execute("ROLLBACK")
            raise HTTPException(400, f"版本不存在:{版本键}")
        conn.execute("UPDATE 开关版本 SET 状态='已失效' WHERE 版本键=?", (版本键,))
        for r in conn.execute(
            "SELECT 票号 FROM 下发票 WHERE 版本键=? AND 状态='已下发'", (版本键,)
        ):
            指纹账.作废指纹(conn, r["票号"], 指纹账.失效状态)
        conn.execute(
            "UPDATE 下发票 SET 状态='已失效' WHERE 版本键=? AND 状态='已下发'",
            (版本键,),
        )
        conn.execute(
            "INSERT INTO 命运账(对象类型, 对象键, 命运, 时刻, 说明) VALUES (?,?,?,?,?)",
            ("开关版本", 版本键, "失效", 此刻(), 体.get("说明", "版本失效")),
        )
        conn.commit()
        return {"版本键": 版本键, "状态": "已失效"}
    except HTTPException:
        _安全回滚(conn)
        raise
    except Exception as e:
        _安全回滚(conn)
        raise HTTPException(500, f"失效异常，已失败闭:{e}")
    finally:
        conn.close()


def _安全回滚(conn) -> None:
    try:
        conn.execute("ROLLBACK")
    except Exception:
        pass
