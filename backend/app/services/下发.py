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
from app.modules import 下发快照指纹账 as 指纹账


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _安全回滚(conn) -> None:
    try:
        conn.execute("ROLLBACK")
    except Exception:
        pass


class _计划写故障(RuntimeError):
    pass


class _指纹写故障(RuntimeError):
    pass


def _落失败票(体: dict, 票号: str, 版本键: str, 桶键: str, 开关键: str, 原因: str,
              消耗开关: bool = False, 载荷: str = "{}", 消耗指纹: bool = False) -> None:
    """口径一（票随计划/指纹回退）：外层整事务回滚后，独立落一张可 GET 的「下发失败」票。

    失败票绝不是已下发，指纹行不存在；补偿票随失败票一并保留（可在补登后重钉）。
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
        if 消耗指纹:
            指纹账.消耗指纹故障(conn)
        conn.execute(
            """INSERT INTO 下发票(票号, 开关键, 版本键, 桶键, 状态, 下发时, 世代, 说明,
                                  缺计划, 晋升状态, 失败口径, 故障说明, 载荷)
               VALUES (?,?,?,?, '下发失败', ?, 1, ?, 0, '未晋升', ?, ?, ?)
               ON CONFLICT(票号) DO UPDATE SET
                 状态='下发失败', 缺计划=0, 失败口径='回退',
                 故障说明=excluded.故障说明, 世代=下发票.世代+1,
                 载荷=excluded.载荷""",
            (票号, 开关键, 版本键, 桶键, 此刻(), 体.get("说明", ""), 口径回退,
             原因, 载荷),
        )
        指纹账.作废指纹(conn, 票号, 指纹账.失效状态)
        conn.execute(
            "INSERT INTO 命运账(对象类型, 对象键, 命运, 时刻, 说明) VALUES ('下发票',?,?,?,?)",
            (票号, "下发失败", 此刻(), f"末步写失败，票随事务回退，指纹不得空行:{原因}"),
        )
        conn.commit()
    finally:
        conn.close()


def _失败响应(票号: str, 原因: str, 口径: str = 口径回退, 指纹: dict | None = None) -> dict:
    out = {
        "票号": 票号,
        "状态": "下发失败",
        "已下发": False,
        "口径": 口径,
        "valid": False,
        "可否晋升": False,
        "计划有无": False,
        "缺计划标记": False,
        "指纹有无": False,
        "说明": 原因,
    }
    if 指纹:
        out["指纹"] = 指纹
    return out


def 下一票(体: dict, 查询=None, 头=None) -> dict:
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

        载荷文本 = 指纹账.载荷字节文本(ver["载荷"])

        req_armed, _ = 请求故障(体, 查询, 头)
        sw_armed, sw_posture, _剩余 = 开关故障(conn)
        env_armed, _env_posture = 环境故障武装()
        武装 = req_armed or sw_armed or env_armed

        指纹武装 = 指纹账.请求指纹故障(体, 查询, 头)
        指纹开关武装, _指纹剩余 = 指纹账.开关指纹故障(conn)
        指纹武装 = 指纹武装 or 指纹开关武装

        口径 = 解析口径(conn, 体, 查询, 头, 开关口径=sw_posture)
        if 口径 not in (口径回退, 口径悬挂):
            口径 = 口径回退
        edges = 解析边缘们(conn, 体, bucket)
        补偿票 = 指纹账.取补偿票(体, 查询, 头)

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

        已有指纹 = 指纹账.取指纹(conn, 票号)
        指纹证 = 指纹账.核证(conn, 票号) if 已 else None

        # —— 再次意图闸：同开关键 / 同票号重打时按架构消化指纹行 ——
        # 不论是否带故障注入，「无指纹且未持补偿票」都不得落新已下发。
        if 已 and 已["状态"] == "已下发":
            n = conn.execute(
                "SELECT COUNT(*) AS c FROM 回读计划行 WHERE 票号=?", (票号,)
            ).fetchone()["c"]
            指纹有效 = bool(指纹证 and 指纹证["valid"])
            if 指纹有效 and not 已["缺计划"] and n > 0 and not 武装 and not 指纹武装:
                out = 核证(conn, 票号)
                out.update({"幂等": True, "状态": "已下发", "指纹": 指纹证})
                conn.commit()
                已了结 = True
                return out
            # 指纹缺失 / 空哈希 / 哈希对不上：无补偿票不得落新已下发。
            if not 指纹有效 and not 指纹账.补偿有效(dict(已), 补偿票):
                conn.execute("ROLLBACK")
                已了结 = True
                raise HTTPException(
                    400,
                    {
                        "票号": 票号,
                        "拒绝": True,
                        "已下发": True,
                        "新已下发": False,
                        "指纹有无": bool(已有指纹),
                        "指纹": 指纹证,
                        "补偿有无": bool(dict(已).get("补偿票")),
                        "原因": "缺指纹或哈希对不上且未持补偿票：同开关键再次意图失败，不落新已下发",
                        "valid": False,
                        "可否晋升": False,
                    },
                )

        if 已 is None:
            conn.execute(
                """INSERT INTO 下发票(票号, 开关键, 版本键, 桶键, 状态, 下发时, 世代, 说明,
                                      缺计划, 晋升状态, 失败口径, 故障说明, 载荷)
                   VALUES (?,?,?,?, '已下发', ?, 1, ?, 0, '未晋升', '', '', ?)""",
                (票号, ver["开关键"], 版本键, 桶键, 此刻(), 体.get("说明", ""), 载荷文本),
            )
        else:
            conn.execute(
                """UPDATE 下发票 SET 状态='已下发', 下发时=?, 世代=世代+1,
                     缺计划=0, 晋升状态='未晋升', 失败口径='', 故障说明='', 载荷=?
                   WHERE 票号=?""",
                (此刻(), 载荷文本, 票号),
            )

        conn.execute("UPDATE 开关版本 SET 状态='灰度中' WHERE 版本键=?", (版本键,))
        conn.execute(
            "INSERT INTO 命运账(对象类型, 对象键, 命运, 时刻, 说明) VALUES ('下发票',?,?,?,?)",
            (票号, "下发", 此刻(), 体.get("说明", "灰度下发，计划与快照指纹同票")),
        )

        # —— 末步一：回读计划（甲回退 / 乙悬挂），沿用既有口径 ——
        原因 = "注入：下发末步回读计划写失败"
        悬挂 = False
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
                悬挂 = True
            else:
                conn.execute("ROLLBACK")
                _落失败票(体, 票号, 版本键, 桶键, ver["开关键"], 原因,
                          消耗开关=sw_armed, 载荷=载荷文本)
                已了结 = True
                raise HTTPException(
                    400,
                    _失败响应(票号, "计划写失败，票随计划整事务回退，不得停留已下发",
                              口径=口径回退, 指纹=指纹账.核证(conn, 票号)),
                )

        # —— 末步二：快照指纹行，与下发/回读/命运同事务 ——
        try:
            if 指纹武装:
                raise _指纹写故障("注入：下发末步快照指纹写失败")
            conn.execute("SAVEPOINT 指纹步")
            新指纹 = 指纹账.写指纹(
                conn, 票号=票号, 开关键=ver["开关键"], 版本键=版本键, 桶键=桶键,
                载荷文本=载荷文本,
                分桶快照=指纹账.分桶快照摘要(dict(bucket), edges),
                补偿=补偿票 or (dict(已).get("补偿票", "") if 已 else ""),
            )
            conn.execute("RELEASE SAVEPOINT 指纹步")
        except Exception as e:
            try:
                conn.execute("ROLLBACK TO SAVEPOINT 指纹步")
            except Exception:
                pass
            conn.execute("ROLLBACK")
            _落失败票(
                体, 票号, 版本键, 桶键, ver["开关键"],
                f"快照指纹写失败，失败闭:{e}", 载荷=载荷文本,
                消耗指纹=指纹开关武装,
            )
            已了结 = True
            raise HTTPException(
                400,
                _失败响应(
                    票号,
                    "快照指纹写失败：不得票已发而指纹空，整事务回退（失败闭）",
                    口径=口径回退, 指纹=指纹账.核证(conn, 票号),
                ),
            )

        conn.commit()
        已了结 = True
        out = 核证(conn, 票号)
        指纹证 = 指纹账.核证(conn, 票号)
        out.update({
            "幂等": False,
            "注入故障": bool(武装),
            "口径": 口径,
            "缺计划悬挂": 悬挂,
            "指纹": 指纹证,
            "指纹有无": 指纹证["指纹有无"],
            "哈希": 指纹证["哈希"],
            "补偿有无": 指纹证["补偿有无"],
        })
        return out

    except HTTPException:
        if not 已了结:
            _安全回滚(conn)
        raise
    except sqlite3.IntegrityError as e:
        if not 已了结:
            _安全回滚(conn)
        raise HTTPException(400, f"并发下发/指纹唯一槽冲突，失败闭:{e}")
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
