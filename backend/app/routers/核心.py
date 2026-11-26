import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.db import 夹具目录, 连接
from app.services import 入轨, 分桶, 下发, 回读, 命运, 贯验, 目录, 晋升
from app.modules.下发回读计划同票 import 核证, 列核证, 补建计划, 故障键, 环境故障武装

路由 = APIRouter(prefix="/api")


class 入轨请求(BaseModel):
    批次编号: str = ""
    版本: list = Field(default_factory=list)


class 分桶请求(BaseModel):
    桶键: str
    开关键: str
    桶类型: str = "百分比"
    规则: dict = Field(default_factory=dict)
    状态: str = "生效"


class 下发请求(BaseModel):
    model_config = ConfigDict(extra="allow")

    票号: str = ""
    版本键: str
    桶键: str
    说明: str = ""
    
    边缘们: list | None = None
    计划边缘: list | None = None
    edges: list | None = None
    口径: str = ""
    计划失败口径: str = ""
    注入故障: str = ""
    计划写失败: bool | None = None


class 回读请求(BaseModel):
    票号: str
    证号: str = ""
    边缘键: str
    所见版本键: str = ""
    结果: str = "确认"
    说明: str = ""


class 回滚请求(BaseModel):
    票号: str
    说明: str = ""


class 失效请求(BaseModel):
    版本键: str
    说明: str = ""


class 票号请求(BaseModel):
    model_config = ConfigDict(extra="allow")
    票号: str = ""
    ticket: str = ""

    def 取票号(self) -> str:
        return self.票号 or self.ticket


class 补计划请求(BaseModel):
    model_config = ConfigDict(extra="allow")
    票号: str = ""
    ticket: str = ""
    边缘们: list | None = None
    计划边缘: list | None = None
    edges: list | None = None

    def 取票号(self) -> str:
        return self.票号 or self.ticket


class 故障请求(BaseModel):
    model_config = ConfigDict(extra="allow")
    故障: str = 故障键
    名: str = ""
    键: str = ""
    启用: bool = True
    口径: str = ""
    
    
    剩余次数: int = 1


def _取票参数(票号: str, ticket: str, id: str, no: str, 票: str = "") -> str:
    return 票号 or ticket or id or no or 票


@路由.get("/健康")
def 健康():
    return {
        "正常": True,
        "项目": "灰度轨",
        "领域": "基础设施",
        "子方向": "中间件",
        "骨架": "开关版本入轨→分桶灰度下发→回读确认→失效/回滚互证",
    }


@路由.get("/总览")
def 取总览():
    return 目录.总览()


@路由.get("/站规")
def 站规():
    conn = 连接()
    try:
        return {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 站规")}
    finally:
        conn.close()


@路由.get("/开关版本")
def 列版本(状态: str = ""):
    conn = 连接()
    try:
        if 状态:
            rows = conn.execute(
                "SELECT * FROM 开关版本 WHERE 状态=? ORDER BY 入轨时 DESC", (状态,)
            )
        else:
            rows = conn.execute("SELECT * FROM 开关版本 ORDER BY 入轨时 DESC")
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["载荷"] = json.loads(d["载荷"])
            except Exception:
                pass
            out.append(d)
        return out
    finally:
        conn.close()


@路由.get("/分桶规")
def 列分桶():
    conn = 连接()
    try:
        out = []
        for r in conn.execute("SELECT * FROM 分桶规 ORDER BY 更新时 DESC"):
            d = dict(r)
            try:
                d["规则"] = json.loads(d["规则"])
            except Exception:
                pass
            out.append(d)
        return out
    finally:
        conn.close()


def _票带核证(conn, r) -> dict:
    d = dict(r)
    try:
        d.update(核证(conn, r["票号"]))
        
    except Exception:
        pass
    return d


@路由.get("/下发票")
def 列下发(状态: str = ""):
    conn = 连接()
    try:
        if 状态:
            rows = conn.execute(
                "SELECT * FROM 下发票 WHERE 状态=? ORDER BY 下发时 DESC", (状态,)
            )
        else:
            rows = conn.execute("SELECT * FROM 下发票 ORDER BY 下发时 DESC")
        return [_票带核证(conn, r) for r in rows]
    finally:
        conn.close()


@路由.get("/下发票/{ticket}")
def 取下发单票(ticket: str):
    conn = 连接()
    try:
        r = conn.execute("SELECT * FROM 下发票 WHERE 票号=?", (ticket,)).fetchone()
        if not r:
            raise HTTPException(404, f"下发票不存在:{ticket}")
        return _票带核证(conn, r)
    finally:
        conn.close()


@路由.get("/回读计划")
@路由.get("/回读计划行")
@路由.get("/计划")
def 列回读计划(票号: str = "", ticket: str = ""):
    conn = 连接()
    try:
        no = 票号 or ticket
        if no:
            rows = conn.execute(
                "SELECT * FROM 回读计划行 WHERE 票号=? ORDER BY 边缘键", (no,)
            )
        else:
            rows = conn.execute(
                "SELECT * FROM 回读计划行 ORDER BY 票号, 边缘键 LIMIT 500"
            )
        return [dict(r) for r in rows]
    finally:
        conn.close()


@路由.get("/计划核证")
@路由.get("/计划/核证")
@路由.get("/核证")
@路由.get("/certify")
@路由.get("/verify")
@路由.get("/plan-cert")
@路由.get("/plan/verify")
@路由.get("/回读计划核证")
@路由.get("/回读计划/核证")
@路由.get("/下发回读计划同票/核证")
def 计划核证路由(
    票号: str = "", ticket: str = "", id: str = "", no: str = "", 票: str = ""
):
    目标 = _取票参数(票号, ticket, id, no, 票)
    conn = 连接()
    try:
        if not 目标:
            return 列核证(conn)
        return 核证(conn, 目标)
    finally:
        conn.close()


@路由.get("/下发票/{ticket}/核证")
def 票核证路径(ticket: str):
    conn = 连接()
    try:
        return 核证(conn, ticket)
    finally:
        conn.close()



@路由.post("/计划核证")
@路由.post("/计划/核证")
@路由.post("/核证")
@路由.post("/certify")
@路由.post("/verify")
@路由.post("/plan-cert")
@路由.post("/plan/verify")
@路由.post("/回读计划核证")
@路由.post("/回读计划/核证")
@路由.post("/下发回读计划同票/核证")
def 计划核证POST(体: 票号请求 | None = None):
    目标 = 体.取票号() if 体 is not None else ""
    conn = 连接()
    try:
        if not 目标:
            return 列核证(conn)
        return 核证(conn, 目标)
    finally:
        conn.close()


@路由.get("/回读证")
def 列回读():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 回读证 ORDER BY 回读时 DESC LIMIT 200")]
    finally:
        conn.close()


@路由.get("/命运账")
def 列命运():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 命运账 ORDER BY 编号 DESC LIMIT 100")]
    finally:
        conn.close()


@路由.get("/批次")
def 列批次():
    conn = 连接()
    try:
        out = []
        for r in conn.execute("SELECT * FROM 装载批次 ORDER BY 时刻 DESC LIMIT 30"):
            d = dict(r)
            try:
                d["报告"] = json.loads(d["报告"])
            except Exception:
                pass
            out.append(d)
        return out
    finally:
        conn.close()


@路由.get("/空桩")
def 列空桩():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 空桩 ORDER BY 名")]
    finally:
        conn.close()


@路由.post("/入轨")
def 做入轨(体: 入轨请求):
    return 入轨.入一批(体.model_dump())


@路由.post("/分桶")
def 做分桶(体: 分桶请求):
    return 分桶.写桶(体.model_dump())


@路由.post("/下发")
def 做下发(request: Request, 体: 下发请求):
    return 下发.下一票(体.model_dump(), request.query_params, request.headers)


@路由.post("/回读")
def 做回读(体: 回读请求):
    return 回读.记回读(体.model_dump())


@路由.post("/补计划")
@路由.post("/补建计划")
@路由.post("/回读计划/补建")
def 做补计划(体: 补计划请求):
    d = 体.model_dump()
    d["票号"] = 体.取票号()
    if not d["票号"]:
        raise HTTPException(400, "缺少票号")
    return 补建计划(d)


@路由.post("/下发票/{ticket}/补计划")
@路由.post("/下发票/{ticket}/补建计划")
def 做票补计划路径(ticket: str, 体: 补计划请求 | None = None):
    d = 体.model_dump() if 体 is not None else {}
    d["票号"] = ticket  
    return 补建计划(d)


@路由.post("/晋升")
@路由.post("/全量晋升")
def 做晋升(体: 票号请求):
    no = 体.取票号()
    if not no:
        raise HTTPException(400, "缺少票号")
    return 晋升.全量晋升({"票号": no})


@路由.post("/下发票/{ticket}/晋升")
def 做票晋升路径(ticket: str):
    return 晋升.全量晋升({"票号": ticket})


@路由.post("/回滚")
def 做回滚(体: 回滚请求):
    return 命运.回滚票(体.model_dump())


@路由.post("/失效")
def 做失效(体: 失效请求):
    return 命运.失效版本(体.model_dump())




@路由.get("/故障注入")
def 取故障():
    conn = 连接()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM 故障开关 ORDER BY 键")]
        env_armed, env_mode = 环境故障武装()
        return {"开关": rows, "环境武装": env_armed, "环境口径": env_mode}
    finally:
        conn.close()


@路由.post("/故障注入")
def 置故障(体: 故障请求):
    键 = 体.键 or 体.名 or 体.故障 or 故障键
    from app.seed import 此刻

    conn = 连接()
    try:
        conn.execute(
            """INSERT INTO 故障开关(键, 启用, 口径, 剩余次数, 更新时)
               VALUES (?,?,?,?,?)
               ON CONFLICT(键) DO UPDATE SET
                 启用=excluded.启用, 口径=excluded.口径,
                 剩余次数=excluded.剩余次数, 更新时=excluded.更新时""",
            (键, 1 if 体.启用 else 0, 体.口径, 体.剩余次数, 此刻()),
        )
        conn.commit()
        return {"键": 键, "启用": 体.启用, "口径": 体.口径, "剩余次数": 体.剩余次数}
    finally:
        conn.close()


@路由.post("/故障注入/复位")
def 复位故障():
    conn = 连接()
    try:
        conn.execute("UPDATE 故障开关 SET 启用=0, 剩余次数=0 WHERE 键=?", (故障键,))
        conn.commit()
        return {"复位": True}
    finally:
        conn.close()


@路由.post("/故障注入/裸孤儿")
def 造裸孤儿(体: 票号请求):
    """模拟修复前的历史脏数据：票已下发、无同票计划行、且没有缺计划标记。

    核证必须 valid=false / 暗缺计划=true，回读与晋升必须拒，贯验必须抓「假已下发」。
    随后可通过 /补计划 治愈。
    """
    no = 体.取票号()
    if not no:
        raise HTTPException(400, "缺少票号")
    conn = 连接()
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        t = conn.execute("SELECT * FROM 下发票 WHERE 票号=?", (no,)).fetchone()
        if not t:
            raise HTTPException(404, f"下发票不存在，请先入轨+分桶:{no}")
        conn.execute("DELETE FROM 回读计划行 WHERE 票号=?", (no,))
        conn.execute(
            "UPDATE 下发票 SET 状态='已下发', 缺计划=0, 晋升状态='未晋升' WHERE 票号=?",
            (no,),
        )
        conn.execute("COMMIT")
        return 核证(conn, no)
    except HTTPException:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


@路由.post("/装载/夹具")
def 装夹具(名: str = "入轨样例"):
    路径 = 夹具目录 / f"{名}.json"
    if not 路径.exists():
        raise HTTPException(404, f"夹具不存在:{名}")
    体 = json.loads(路径.read_text(encoding="utf-8"))
    类型 = 体.get("类型", "入轨")
    if 类型 == "入轨":
        return 入轨.入一批(体)
    if 类型 == "分桶":
        outs = [分桶.写桶(x) for x in 体.get("分桶") or []]
        return {"类型": "分桶", "结果": outs}
    if 类型 == "下发":
        return 下发.装下发夹具(体)
    if 类型 == "回读":
        return 回读.装回读夹具(体)
    if 类型 == "回滚":
        return 命运.回滚票(体)
    raise HTTPException(400, f"未知夹具类型:{类型}")


@路由.post("/贯验")
def 做贯验():
    return 贯验.跑贯验()


@路由.get("/贯验")
def 列贯验():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 轨贯验 ORDER BY 编号 DESC LIMIT 20")]
    finally:
        conn.close()

from app.modules import 下发快照指纹账 as _bf_mod_17


@路由.get("/核证/指纹账")
def 取核证_17(键: str | None = None):
    conn = 连接()
    try:
        return _bf_mod_17.查现场(conn, 键)
    finally:
        conn.close()


@路由.post("/核证/指纹账/巡检")
def 巡检核证_17(payload: dict | None = None):
    return _bf_mod_17.巡检包(payload or {})

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

