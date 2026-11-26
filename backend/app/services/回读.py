import json
from datetime import datetime, timezone

from app.db import 连接
from fastapi import HTTPException

from app.modules import 下发快照指纹账 as 指纹账


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def 记回读(体: dict, 查询=None, 头=None) -> dict:
    """边缘回读对照：必须先按同票快照指纹行对上哈希，缺指纹/哈希不符一律失败。

    只有持有同票补偿票时才允许在同一事务内重钉指纹再放行对照。
    """
    conn = 连接()
    conn.execute("PRAGMA busy_timeout=15000")
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        票号 = 体["票号"]
        ticket = conn.execute("SELECT * FROM 下发票 WHERE 票号=?", (票号,)).fetchone()
        if not ticket:
            conn.execute("ROLLBACK")
            raise HTTPException(404, f"下发票不存在:{票号}")
        ticket = dict(ticket)
        if ticket["状态"] not in ("已下发", "回滚中"):
            conn.execute("ROLLBACK")
            raise HTTPException(400, f"票状态不可回读:{ticket['状态']}")

        计划数 = conn.execute(
            "SELECT COUNT(*) AS c FROM 回读计划行 WHERE 票号=?", (票号,)
        ).fetchone()["c"]
        if 计划数 <= 0 or ticket["缺计划"]:
            conn.execute("ROLLBACK")
            raise HTTPException(
                400,
                {
                    "票号": 票号,
                    "拒绝": True,
                    "原因": "缺回读计划：确认回读拒绝；请先补建计划或重发票",
                    "计划有无": 计划数 > 0,
                    "缺计划标记": bool(ticket["缺计划"]) or 计划数 <= 0,
                    "可否晋升": False,
                    "valid": False,
                },
            )

        # —— 回读对照闸：指纹行必须存在且哈希对上票面载荷字节 ——
        补偿票 = 指纹账.取补偿票(体, 查询, 头)
        指纹证 = 指纹账.核证(conn, 票号)
        if not 指纹证["valid"]:
            if 指纹账.补偿有效(ticket, 补偿票):
                指纹账.票指纹(conn, ticket)
                指纹证 = 指纹账.核证(conn, 票号)
                conn.execute(
                    "INSERT INTO 命运账(对象类型, 对象键, 命运, 时刻, 说明) VALUES ('下发票',?,?,?,?)",
                    (票号, "指纹补偿重钉", 此刻(), "回读对照前持补偿票重钉快照指纹"),
                )
                if not 指纹证["valid"]:
                    conn.execute("ROLLBACK")
                    raise HTTPException(
                        400,
                        {"票号": 票号, "拒绝": True, "原因": "补偿重钉后指纹仍无效",
                         "指纹": 指纹证, "valid": False},
                    )
            else:
                conn.execute("ROLLBACK")
                raise HTTPException(
                    400,
                    {
                        "票号": 票号,
                        "拒绝": True,
                        "原因": "缺指纹或哈希对不上且未持补偿票：回读对照失败，不得以旧载荷放行",
                        "指纹有无": 指纹证["指纹有无"],
                        "补偿有无": 指纹证["补偿有无"],
                        "指纹": 指纹证,
                        "valid": False,
                        "可否晋升": False,
                    },
                )

        证号 = 体.get("证号") or f"证-{票号}-{体['边缘键']}"
        所见 = 体.get("所见版本键") or ticket["版本键"]
        结果 = 体.get("结果", "确认")
        if 结果 == "确认" and 所见 != ticket["版本键"]:
            结果 = "偏差"
        conn.execute(
            """INSERT INTO 回读证(证号, 票号, 边缘键, 所见版本键, 结果, 回读时, 说明)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(证号) DO UPDATE SET
                 所见版本键=excluded.所见版本键, 结果=excluded.结果,
                 回读时=excluded.回读时, 说明=excluded.说明""",
            (证号, 票号, 体["边缘键"], 所见, 结果, 此刻(), 体.get("说明", "")),
        )
        if 结果 == "确认":
            conn.execute(
                """UPDATE 回读计划行 SET 状态='已确认', 所见版本键=?, 回读证号=?, 更新时=?
                   WHERE 票号=? AND 边缘键=?""",
                (所见, 证号, 此刻(), 票号, 体["边缘键"]),
            )
        else:
            conn.execute(
                """UPDATE 回读计划行 SET 状态='偏差', 所见版本键=?, 回读证号=?, 更新时=?, 说明=?
                   WHERE 票号=? AND 边缘键=?""",
                (所见, 证号, 此刻(), 体.get("说明", "回读偏差"), 票号, 体["边缘键"]),
            )
        conn.commit()
        齐 = conn.execute(
            """SELECT COUNT(*) AS c FROM 回读计划行
               WHERE 票号=? AND 必需=1 AND 状态<>'已确认'""",
            (票号,),
        ).fetchone()["c"]
        return {
            "证号": 证号, "结果": 结果, "未齐套边缘数": 齐,
            "可否晋升": 齐 == 0 and 结果 == "确认",
            "指纹": 指纹证, "哈希": 指纹证["哈希"],
        }
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
        raise HTTPException(500, f"回读异常，已失败闭:{e}")
    finally:
        conn.close()


def 装回读夹具(体: dict) -> dict:
    批次 = 体.get("批次编号") or f"回读-{此刻()}"
    结果 = []
    for item in 体.get("回读") or []:
        结果.append(记回读(item))
    conn = 连接()
    try:
        报告 = {"类型": "回读", "结果": 结果}
        conn.execute(
            "INSERT OR REPLACE INTO 装载批次(编号, 时刻, 报告) VALUES (?,?,?)",
            (批次, 此刻(), json.dumps(报告, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()
    return {"批次编号": 批次, "报告": 报告}
