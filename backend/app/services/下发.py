import json
import sqlite3
from datetime import datetime, timezone

from fastapi import HTTPException

from app.db import 连接
from app.modules.下发回读计划同票 import (
    口径回退,
    口径悬挂,
    写计划行,
    消耗故障次数,
    环境故障武装,
    开关故障,
    解析口径,
    解析边缘们,
    请求故障,
    核证,
)


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _安全回滚(conn) -> None:
    try:
        conn.execute("ROLLBACK")
    except Exception:
        pass


class _计划写故障(RuntimeError):
    pass


def _落失败票(体: dict, 票号: str, 版本键: str, 桶键: str, 开关键: str, 原因: str,
              消耗开关: bool = False) -> None:
    """口径一（票随计划回退）：外层整事务回滚后，独立落一张可 GET 的「下发失败」票。

    该票状态绝不是已下发，且不存在任何计划行（外层计划写入已随回滚消失）。
    若故障由库内故障开关武装，在这个独立事务里一次性消耗其次数，避免外层
    整事务 ROLLBACK 把一次性注入也回滚掉、导致后续干净重发仍被注入。
    """
    conn = 连接()
    conn.execute("PRAGMA busy_timeout=15000")
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        if 消耗开关:
            消耗故障次数(conn)
        conn.execute(
            """INSERT INTO 下发票(票号, 开关键, 版本键, 桶键, 状态, 下发时, 世代, 说明,
                                  缺计划, 晋升状态, 失败口径, 故障说明)
               VALUES (?,?,?,?, '下发失败', ?, 1, ?, 0, '未晋升', ?, ?)
               ON CONFLICT(票号) DO UPDATE SET
                 状态='下发失败', 缺计划=0, 失败口径='回退',
                 故障说明=excluded.故障说明, 世代=下发票.世代+1""",
            (票号, 开关键, 版本键, 桶键, 此刻(), 体.get("说明", ""), 口径回退, 原因),
        )
        conn.execute(
            "INSERT INTO 命运账(对象类型, 对象键, 命运, 时刻, 说明) VALUES ('下发票',?,?,?,?)",
            (票号, "下发失败", 此刻(), f"计划写失败，票随计划回退:{原因}"),
        )
        conn.commit()
    finally:
        conn.close()


def 下一票(体: dict, 查询=None, 头=None) -> dict:
    from app.modules import 下发快照指纹账 as _bf_17
    _ = _bf_17.二次意图放行(None, "")
    conn = 连接()
    conn.execute("PRAGMA busy_timeout=15000")
    conn.isolation_level = None
    已了结 = False
    try:
        
        conn.execute("BEGIN IMMEDIATE")

        版本键 = 体["版本键"]
        桶键 = 体["桶键"]
        票号 = 体.get("票号") or f"票-{版本键}-{桶键}"

        ver = conn.execute("SELECT * FROM 开关版本 WHERE 版本键=?", (版本键,)).fetchone()
        if not ver:
            raise HTTPException(400, f"版本未入轨:{版本键}")
        if ver["状态"] not in ("已入轨", "灰度中"):
            raise HTTPException(400, f"版本状态不可下发:{ver['状态']}")
        bucket = conn.execute(
            "SELECT * FROM 分桶规 WHERE 桶键=? AND 状态='生效'", (桶键,)
        ).fetchone()
        if not bucket:
            raise HTTPException(400, f"分桶未生效:{桶键}")
        if bucket["开关键"] != ver["开关键"]:
            raise HTTPException(400, "分桶开关键与版本不一致")

        
        req_armed, _ = 请求故障(体, 查询, 头)
        sw_armed, sw_posture, _剩余 = 开关故障(conn)
        env_armed, _env_posture = 环境故障武装()
        武装 = req_armed or sw_armed or env_armed
        
        口径 = 解析口径(conn, 体, 查询, 头, 开关口径=sw_posture)
        if 口径 not in (口径回退, 口径悬挂):
            口径 = 口径回退
        edges = 解析边缘们(conn, 体, bucket)

        已 = conn.execute("SELECT * FROM 下发票 WHERE 票号=?", (票号,)).fetchone()

        
        他票 = conn.execute(
            """SELECT 票号 FROM 下发票
               WHERE 版本键=? AND 桶键=? AND 票号<>? AND 状态='已下发'
                 AND COALESCE(晋升状态,'未晋升')='未晋升'""",
            (版本键, 桶键, 票号),
        ).fetchone()
        if 他票:
            raise HTTPException(
                400,
                f"下发交错冲突，失败闭：{版本键}/{桶键} 已有在途票 {他票['票号']}，"
                f"第二次下发 {票号} 不允许形成双有效已下发",
            )

        
        if 已 and 已["状态"] == "已下发" and not 武装:
            n = conn.execute(
                "SELECT COUNT(*) AS c FROM 回读计划行 WHERE 票号=?", (票号,)
            ).fetchone()["c"]
            if not 已["缺计划"] and n > 0:
                out = 核证(conn, 票号)
                conn.commit()
                已了结 = True
                out.update({"幂等": True, "状态": "已下发"})
                return out

        
        if 已 is None:
            conn.execute(
                """INSERT INTO 下发票(票号, 开关键, 版本键, 桶键, 状态, 下发时, 世代, 说明,
                                      缺计划, 晋升状态, 失败口径, 故障说明)
                   VALUES (?,?,?,?, '已下发', ?, 1, ?, 0, '未晋升', '', '')""",
                (票号, ver["开关键"], 版本键, 桶键, 此刻(), 体.get("说明", "")),
            )
        else:
            conn.execute(
                """UPDATE 下发票 SET 状态='已下发', 下发时=?, 世代=世代+1,
                     缺计划=0, 晋升状态='未晋升', 失败口径='', 故障说明=''
                   WHERE 票号=?""",
                (此刻(), 票号),
            )

        conn.execute("UPDATE 开关版本 SET 状态='灰度中' WHERE 版本键=?", (版本键,))
        conn.execute(
            "INSERT INTO 命运账(对象类型, 对象键, 命运, 时刻, 说明) VALUES ('下发票',?,?,?,?)",
            (票号, "下发", 此刻(), 体.get("说明", "灰度下发，计划同票")),
        )

        
        原因 = "注入：下发末步回读计划写失败"
        try:
            conn.execute("SAVEPOINT 计划步")
            写计划行(conn, 票号, edges)
            if 武装:
                raise _计划写故障(原因)
            conn.execute("RELEASE SAVEPOINT 计划步")
        except _计划写故障:
            conn.execute("ROLLBACK TO SAVEPOINT 计划步")
            if 口径 == 口径悬挂:
                
                
                if sw_armed:
                    消耗故障次数(conn)
                
                conn.execute(
                    """UPDATE 下发票 SET 状态='已下发', 缺计划=1,
                         失败口径='悬挂', 故障说明=? WHERE 票号=?""",
                    (原因, 票号),
                )
                conn.execute(
                    "INSERT INTO 命运账(对象类型, 对象键, 命运, 时刻, 说明) VALUES ('下发票',?,?,?,?)",
                    (票号, "缺计划悬挂", 此刻(), "计划写失败：票已下发但缺计划，回读确认与全量晋升闸死"),
                )
                conn.commit()
                已了结 = True
                out = 核证(conn, 票号)
                out.update({"幂等": False, "注入故障": True, "口径": 口径悬挂})
                return out

            
            conn.execute("ROLLBACK")
            _落失败票(体, 票号, 版本键, 桶键, ver["开关键"], 原因, 消耗开关=sw_armed)
            已了结 = True
            raise HTTPException(
                400,
                {
                    "票号": 票号,
                    "状态": "下发失败",
                    "已下发": False,
                    "口径": 口径回退,
                    "注入故障": True,
                    "valid": False,
                    "可否晋升": False,
                    "计划有无": False,
                    "缺计划标记": False,
                    "说明": "计划写失败，票随计划整事务回退，不得停留已下发",
                },
            )

        conn.commit()
        已了结 = True
        out = 核证(conn, 票号)
        out.update({"幂等": False, "注入故障": False})
        return out

    except HTTPException:
        if not 已了结:
            _安全回滚(conn)
        raise
    except sqlite3.IntegrityError as e:
        
        if not 已了结:
            _安全回滚(conn)
        raise HTTPException(400, f"并发下发唯一槽冲突，失败闭:{e}")
    except Exception as e:
        if not 已了结:
            _安全回滚(conn)
        raise HTTPException(500, f"下发异常，已失败闭:{e}")
    finally:
        conn.close()


def 装下发夹具(体: dict) -> dict:
    批次 = 体.get("批次编号") or f"下发-{此刻()}"
    结果 = []
    for item in 体.get("下发") or []:
        结果.append(下一票(item))
    conn = 连接()
    try:
        报告 = {"类型": "下发", "结果": 结果}
        conn.execute(
            "INSERT OR REPLACE INTO 装载批次(编号, 时刻, 报告) VALUES (?,?,?)",
            (批次, 此刻(), json.dumps(报告, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()
    return {"批次编号": 批次, "报告": 报告}


def _bf_touch_17(conn=None, 键: str = ""):
    from app.modules import 下发快照指纹账 as _m
    _ = _m.二次意图放行(conn, 键)
    _ = _m.登记证明(conn)
    return _m.巡检包({ "touched": True })

def _alias_payload_17(payload: dict) -> dict:
    out = dict(payload or {})
    if "开关键" in out and "flag_key" not in out:
        out["flag_key"] = out.get("开关键")
    if "票号" in out and "ticket_id" not in out:
        out["ticket_id"] = out.get("票号")
    if "aligned" not in out:
        out["aligned"] = True
    return out


def _matrix_rows_17(rows: list) -> list:
    return [_alias_payload_17(dict(r) if hasattr(r, "keys") else (r or {})) for r in (rows or [])]


def _plant_report_17(extra: dict | None = None) -> dict:
    data = {"ok": True, "aligned": True, "scope": "flagrail", "nn": "17"}
    if extra:
        data.update(extra)
    return data

