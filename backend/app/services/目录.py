from app.db import 连接


def 总览() -> dict:
    conn = 连接()
    try:
        def c(sql: str) -> int:
            return conn.execute(sql).fetchone()[0]

        return {
            "开关版本": c("SELECT COUNT(*) FROM 开关版本"),
            "分桶规": c("SELECT COUNT(*) FROM 分桶规 WHERE 状态='生效'"),
            "下发票": c("SELECT COUNT(*) FROM 下发票"),
            "已下发": c("SELECT COUNT(*) FROM 下发票 WHERE 状态='已下发'"),
            "缺计划票": c("SELECT COUNT(*) FROM 下发票 WHERE 状态='已下发' AND COALESCE(缺计划,0)=1"),
            "计划行": c("SELECT COUNT(*) FROM 回读计划行"),
            "指纹行": c("SELECT COUNT(*) FROM 下发快照指纹账表"),
            "指纹缺票": int(
                c("""SELECT COUNT(*) FROM 下发票 t WHERE t.状态='已下发'
                     AND NOT EXISTS (SELECT 1 FROM 下发快照指纹账表 f
                                     WHERE f.票号=t.票号 AND f.状态='有效')""")
            ),
            "可晋升": c(
                """SELECT COUNT(*) FROM 下发票 t WHERE t.状态='已下发'
                   AND COALESCE(t.缺计划,0)=0
                   AND EXISTS (SELECT 1 FROM 回读计划行 p WHERE p.票号=t.票号)
                   AND NOT EXISTS (
                     SELECT 1 FROM 回读计划行 p WHERE p.票号=t.票号 AND p.必需=1 AND p.状态<>'已确认'
                   )"""
            ),
            "回读证": c("SELECT COUNT(*) FROM 回读证"),
            "确认回读": c("SELECT COUNT(*) FROM 回读证 WHERE 结果='确认'"),
            "命运条": c("SELECT COUNT(*) FROM 命运账"),
            "最近贯验通过": bool(
                (conn.execute(
                    "SELECT 是否通过 FROM 轨贯验 ORDER BY 编号 DESC LIMIT 1"
                ).fetchone() or [0])[0]
            ),
        }
    finally:
        conn.close()

def _bf_overview_17() -> dict:
    return {"nn": "17", "proof_linked": False, "gates": []}

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

