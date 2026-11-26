from datetime import datetime, timezone

from fastapi import HTTPException

from app.db import 连接
from app.modules.下发回读计划同票 import 核证


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def 全量晋升(体: dict) -> dict:
    """全量晋升闸：缺计划（明标记或暗孤儿）或回读不齐套/有偏差，一律拒绝。"""
    票号 = 体["票号"]
    conn = 连接()
    conn.execute("PRAGMA busy_timeout=15000")
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        t = conn.execute("SELECT * FROM 下发票 WHERE 票号=?", (票号,)).fetchone()
        if not t:
            raise HTTPException(404, f"下发票不存在:{票号}")

        证 = 核证(conn, 票号)
        if t["晋升状态"] == "已全量":
            conn.commit()
            证.update({"放行": True, "幂等": True, "状态": "已全量"})
            return 证

        if not 证["可否晋升"]:
            
            raise HTTPException(
                400,
                {
                    "票号": 票号,
                    "放行": False,
                    "拒绝": True,
                    "可否晋升": False,
                    "valid": 证["valid"],
                    "计划有无": 证["计划有无"],
                    "缺计划标记": 证["缺计划标记"],
                    "待回读边缘": 证["待回读边缘"],
                    "偏差边缘": 证["偏差边缘"],
                    "原因": (
                        "缺回读计划，全量晋升拒绝；请先补建计划"
                        if 证["缺计划标记"] or not 证["计划有无"]
                        else f"回读未齐套/有偏差：待回读 {证['待回读边缘']} 偏差 {证['偏差边缘']}"
                    ),
                },
            )

        conn.execute(
            "UPDATE 下发票 SET 晋升状态='已全量' WHERE 票号=?", (票号,)
        )
        conn.execute(
            "UPDATE 开关版本 SET 状态='已全量' WHERE 版本键=?", (t["版本键"],))
        conn.execute(
            "INSERT INTO 命运账(对象类型, 对象键, 命运, 时刻, 说明) VALUES ('下发票',?,?,?,?)",
            (票号, "全量晋升", 此刻(), "同票计划齐套且全边缘确认，闸放全量"),
        )
        conn.execute(
            "INSERT INTO 命运账(对象类型, 对象键, 命运, 时刻, 说明) VALUES ('开关版本',?,?,?,?)",
            (t["版本键"], "全量晋升", 此刻(), "随票全量晋升"),
        )
        conn.commit()
        out = 核证(conn, 票号)
        out.update({"放行": True, "幂等": False, "状态": "已全量"})
        return out
    except HTTPException:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise HTTPException(500, f"晋升异常，已失败闭:{e}")
    finally:
        conn.close()
