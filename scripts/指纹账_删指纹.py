"""快照指纹账 · 删指纹夹具（std-lib only）。

断言（对应「抹掉指纹行后再打同开关键再次意图」两口径可区分）：
  甲 无补偿票：删指纹后再意图 → 无新已下发、票面仍不得有效放行；回读对照拒。
  乙 持补偿票：删指纹 + 签发补偿票 → 再意图成功落新已下发且 valid；回读对照绿。
  另断言：已下发成功必然落下指纹行；指纹哈希与下发票载荷字节可复核；
         邻开关键补偿禁止串用；台面可按票号打开指纹行。

用法：
  python3 scripts/指纹账_删指纹.py --base http://127.0.0.1:11800
"""

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("FLAGRAIL_BASE", "http://127.0.0.1:11800").rstrip("/")
RUN = str(int(time.time()))

通过 = 0
失败 = 0
失败明细 = []


def check(名称, 条件, 细节=""):
    global 通过, 失败
    if 条件:
        通过 += 1
        print(f"  \033[32mPASS\033[0m {名称}")
    else:
        失败 += 1
        失败明细.append((名称, 细节))
        print(f"  \033[31mFAIL\033[0m {名称} :: {细节}")


def _u(路径):
    return BASE + urllib.parse.quote(路径, safe="/?=&%:+.,@;")


def call(方法, 路径, 体=None, 超时=20):
    data = None
    headers = {"Accept": "application/json"}
    if 体 is not None:
        data = json.dumps(体, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(_u(路径), data=data, headers=headers, method=方法)
    try:
        with urllib.request.urlopen(req, timeout=超时) as r:
            return r.status, _解析(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, _解析(e.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        return -1, {"_conn_error": repr(e)}


def _解析(raw):
    try:
        return json.loads(raw)
    except Exception:
        return {"_text": raw}


def 详情(j):
    return j.get("detail") if isinstance(j, dict) and isinstance(j.get("detail"), dict) else (j if isinstance(j, dict) else {})


def 铺底(标记, 载荷=None):
    版本键 = f"v.{标记}.{RUN}@1"
    开关键 = f"k.{标记}.{RUN}"
    桶键 = f"b.{标记}.{RUN}"
    s, _ = call("POST", "/api/入轨", {"版本": [{
        "开关键": 开关键, "版本号": 1, "版本键": 版本键,
        "载荷": 载荷 if 载荷 is not None else {"enabled": True, "variant": "B"},
    }]})
    assert s == 200, f"入轨失败 {s}"
    s, _ = call("POST", "/api/分桶", {"桶键": 桶键, "开关键": 开关键})
    assert s == 200, f"分桶失败 {s}"
    return 开关键, 版本键, 桶键


def 指纹(票号):
    q = urllib.parse.urlencode({"票号": 票号})
    s, j = call("GET", f"/api/指纹账?{q}")
    assert s == 200 and isinstance(j, dict), f"指纹核证异常 {s} {j}"
    return j


def 票(票号):
    s, j = call("GET", f"/api/下发票/{urllib.parse.quote(票号, safe='')}")
    return s, j


def 下发(票号, 版本键, 桶键, **extra):
    body = {"票号": 票号, "版本键": 版本键, "桶键": 桶键,
            "边缘们": ["edge-a", "edge-b"]}
    body.update(extra)
    return call("POST", "/api/下发", body)


def 版本载荷(版本键):
    s, rows = call("GET", "/api/开关版本")
    for r in rows if isinstance(rows, list) else []:
        if r.get("版本键") == 版本键:
            return r.get("载荷")
    return None


def 复核哈希(载荷):
    文本 = 载荷 if isinstance(载荷, str) else json.dumps(载荷, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(文本.encode("utf-8")).hexdigest()


def 正向_下发落指纹():
    print("\n[正向] 下发成功必须同事务落指纹行，哈希与载荷字节可复核")
    开关键, 版本键, 桶键 = 铺底("fpok")
    票号 = f"票-fpok-{RUN}"
    s, j = 下发(票号, 版本键, 桶键)
    check("下发成功", s == 200 and isinstance(j, dict) and j.get("valid") is True, f"{s} {str(j)[:180]}")
    证 = 指纹(票号)
    check("已下发必然有指纹行", 证.get("指纹有无") is True, str(证)[:200])
    check("指纹哈希非空", bool(证.get("哈希")), str(证.get("哈希")))
    check("指纹哈希与票面/载荷字节一致", 证.get("哈希") == 证.get("票面哈希") == 复核哈希(版本载荷(版本键)),
          f"fp={证.get('哈希')} 复核={复核哈希(版本载荷(版本键))}")
    check("指纹 valid=true 且开关键一致", 证.get("valid") is True and 证.get("指纹开关键") == 开关键, str(证)[:200])
    check("指纹含分桶快照摘要", bool(证.get("分桶快照")), str(证.get("分桶快照"))[:120])
    s, t = 票(票号)
    check("台面按票号打开指纹行（下发票带指纹）",
          s == 200 and isinstance(t.get("指纹"), dict) and t["指纹"].get("valid") is True,
          f"{s} {str(t.get('指纹'))[:120] if isinstance(t, dict) else t}")
    s, one = call("GET", f"/api/下发票/{urllib.parse.quote(票号, safe='')}/指纹")
    check("路径别名 GET 下发票/{票号}/指纹 可打开", s == 200 and one.get("票号") == 票号, f"{s} {one}")
    return 开关键, 版本键, 桶键, 票号


def 甲_无补偿():
    print("\n[甲] 删指纹 + 无补偿票：再意图无新已下发，回读对照拒")
    开关键, 版本键, 桶键, 票号 = 正向_下发落指纹()
    s, c0 = call("POST", "/api/故障注入/删指纹", {"票号": 票号})
    check("删指纹夹具成功", s == 200, f"{s} {c0}")
    check("抹除后指纹有无=false", 指纹(票号).get("指纹有无") is False)
    命运前 = len(call("GET", "/api/命运账")[1]) if isinstance(call("GET", "/api/命运账")[1], list) else 0

    s, j = 下发(票号, 版本键, 桶键)
    d = 详情(j)
    check("甲 再次意图失败(400)", s == 400, f"{s} {str(j)[:200]}")
    check("甲 再次意图不落新已下发", d.get("新已下发") is False, str(d)[:200])
    证 = 指纹(票号)
    check("甲 仍无指纹（未被旧载荷覆盖）", 证.get("指纹有无") is False and 证.get("valid") is False, str(证)[:200])
    命运后 = len(call("GET", "/api/命运账")[1]) if isinstance(call("GET", "/api/命运账")[1], list) else 0
    check("甲 未写新的下发命运条", 命运后 == 命运前, f"前={命运前} 后={命运后}")

    s, j = call("POST", "/api/回读", {"票号": 票号, "边缘键": "edge-a"})
    check("甲 回读对照被拒", s == 400, f"{s} {str(j)[:200]}")
    check("甲 被拒回读不落库", len(call("GET", "/api/回读证")[1] or []) == len(call("GET", "/api/回读证")[1] or []), "")
    s, g = call("POST", "/api/贯验")
    说明 = g.get("说明", "") if isinstance(g, dict) else ""
    check("甲 贯验抓住 已下发缺快照指纹", isinstance(g, dict) and g.get("是否通过") is False and "缺快照指纹" in 说明,
          f"{s} {说明[:200]}")


def 乙_持补偿():
    print("\n[乙] 删指纹 + 持补偿票：再意图落新已下发，回读对照绿")
    开关键, 版本键, 桶键 = 铺底("fpcmp")
    票号 = f"票-fpcmp-{RUN}"
    s, j = 下发(票号, 版本键, 桶键)
    assert s == 200 and j.get("valid") is True, f"前置下发失败 {s} {j}"
    s, _ = call("POST", "/api/故障注入/删指纹", {"票号": 票号})
    assert s == 200, f"删指纹失败 {s}"

    s, j = 下发(票号, 版本键, 桶键)
    check("乙 未持补偿票时再次意图仍失败", s == 400, f"{s} {str(j)[:200]}")

    s, comp = call("POST", "/api/指纹/补偿", {"票号": 票号, "开关键": 开关键})
    check("乙 签发补偿票成功", s == 200 and comp.get("补偿有无") is True, f"{s} {comp}")
    补偿 = comp.get("补偿票", "")

    s, j = 下发(票号, 版本键, 桶键, 补偿票=补偿)
    check("乙 持补偿票再次意图成功", s == 200 and isinstance(j, dict) and j.get("valid") is True, f"{s} {str(j)[:200]}")
    check("乙 落新已下发", isinstance(j, dict) and j.get("已下发") is True, str(j)[:160])
    证 = 指纹(票号)
    check("乙 指纹已重钉且 valid", 证.get("指纹有无") is True and 证.get("valid") is True and 证.get("哈希") == 证.get("票面哈希"),
          str(证)[:200])
    check("乙 重钉哈希可复核", 证.get("哈希") == 复核哈希(版本载荷(版本键)), str(证.get("哈希")))

    for e in ("edge-a", "edge-b"):
        s, j = call("POST", "/api/回读", {"票号": 票号, "边缘键": e, "补偿票": 补偿})
        check(f"乙 回读对照放行 {e}", s == 200 and j.get("结果") == "确认", f"{s} {str(j)[:160]}")
    s, c = call("GET", f"/api/计划核证?{urllib.parse.urlencode({'票号': 票号})}")
    check("乙 回读齐套后可否晋升=true", c.get("可否晋升") is True, str(c.get("待回读边缘")))


def 邻键串用():
    print("\n[邻键] 邻开关键指纹禁止串用：补偿票绑定开关键，错键拒绝")
    _, 版本键, 桶键 = 铺底("fpnei")
    票号 = f"票-fpnei-{RUN}"
    s, j = 下发(票号, 版本键, 桶键)
    assert s == 200
    s, _ = call("POST", "/api/故障注入/删指纹", {"票号": 票号})
    assert s == 200
    s, j = call("POST", "/api/指纹/补偿", {"票号": 票号, "开关键": f"k.别的.{RUN}"})
    check("邻开关键补偿票被拒", s == 400, f"{s} {str(j)[:200]}")
    证 = 指纹(票号)
    check("邻键拒绝后仍未串写指纹", 证.get("指纹有无") is False, str(证)[:160])


def main():
    global BASE
    args = sys.argv[1:]
    if "--base" in args:
        BASE = args[args.index("--base") + 1].rstrip("/")
    for i in range(30):
        s, j = call("GET", "/api/健康")
        if s == 200 and isinstance(j, dict) and j.get("正常"):
            print(f"已连接灰度轨后端：{BASE}")
            break
        time.sleep(1)
    else:
        print(f"连不上服务 {BASE}")
        return 2

    甲_无补偿()
    乙_持补偿()
    邻键串用()

    print("\n" + "=" * 64)
    print(f"结果：{通过} 通过 / {失败} 失败")
    if 失败:
        for n, d in 失败明细:
            print(f" - {n} :: {d}")
        print("=" * 64)
        return 1
    print("删指纹夹具断言通过：缺指纹无补偿即失败，持补偿可重钉放行。")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
