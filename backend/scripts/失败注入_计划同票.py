

"""下发回读计划同票 · 失败注入自动化（零三方依赖，标准库即可）。

断言目标（对应题单）：
  1. 下发末步注入「回读计划写失败」：
     - 甲票走「票随计划回退」口径 -> 甲票非已下发（下发失败/待下发/不存在均可），计划行不存在；
     - 乙票走「缺计划悬挂」口径   -> 乙票已下发，但缺计划标记=true，确认回读与全量晋升一律拒绝；
     - 两口径在失败瞬间由 GET /api/计划核证 可区分（已下发? / 可否晋升? / valid）。
  2. 甲重发、乙补计划（随后补齐回读）后，两端都能走到全量晋升。
  3. 原始「裸孤儿」假已下发（有票无计划且无标记）必须被核证/回读/晋升/贯验抓住——断言假已下发。
  4. 并发第二次下发（同 版本+桶、不同票号）失败闭：不得双有效已下发；
     同票号并发重发不得产生重复计划行。

用法：
  python3 scripts/失败注入_计划同票.py                 # 默认 http://127.0.0.1:11800
  FLAGRAIL_BASE=http://127.0.0.1:6800 python3 scripts/失败注入_计划同票.py
  python3 scripts/失败注入_计划同票.py --base http://127.0.0.1:11800

退出码 0 全绿；1 有断言失败；2 连不上服务。
"""

import json
import os
import sys
import threading
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
    """返回 (status, json_or_text)。HTTP 4xx/5xx 不抛，交给断言。"""
    data = None
    headers = {"Accept": "application/json"}
    if 体 is not None:
        data = json.dumps(体, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(_u(路径), data=data, headers=headers, method=方法)
    try:
        with urllib.request.urlopen(req, timeout=超时) as r:
            raw = r.read().decode("utf-8")
            return r.status, _解析(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        return e.code, _解析(raw)
    except Exception as e:  
        return -1, {"_conn_error": repr(e)}


def _解析(raw):
    try:
        return json.loads(raw)
    except Exception:
        return {"_text": raw}


def 取票号(名称):
    return f"票-{名称}-{RUN}"


def 铺底(标记):
    vk = f"v-{标记}-{RUN}@1"
    kk = f"k.{标记}.{RUN}"
    bk = f"bkt-{标记}-{RUN}"
    s, _ = call("POST", "/api/入轨", {"版本": [{"开关键": kk, "版本号": 1, "版本键": vk}]})
    assert s == 200, f"入轨失败 {s}"
    s, _ = call("POST", "/api/分桶", {"桶键": bk, "开关键": kk})
    assert s == 200, f"分桶失败 {s}"
    return vk, bk


def 核证(t):
    q = urllib.parse.urlencode({"票号": t})
    s, j = call("GET", f"/api/计划核证?{q}")
    assert s == 200 and isinstance(j, dict), f"核证接口异常 {s} {j}"
    return j


def 票(t):
    return call("GET", f"/api/下发票/{urllib.parse.quote(t, safe='')}")


def 计划行(t):
    q = urllib.parse.urlencode({"票号": t})
    s, j = call("GET", f"/api/回读计划?{q}")
    return j if isinstance(j, list) else []


def 回读两端(t, edges=("edge-a", "edge-b")):
    for e in edges:
        s, j = call("POST", "/api/回读", {"票号": t, "边缘键": e})
        if s >= 400:
            return False, f"回读 {e} 被拒 {s} {j}"
    return True, ""


def 场景甲_回退():
    print("\n[甲] 口径一：票随计划回退（甲票非已下发，重发后走通）")
    vk, bk = 铺底("jia")
    t = 取票号("甲")
    s, j = call("POST", "/api/下发", {
        "票号": t, "版本键": vk, "桶键": bk, "边缘们": ["edge-a", "edge-b"],
        "注入故障": "计划写失败", "口径": "回退",
    })
    print(f"  · 注入下发响应 HTTP {s}")
    check("甲 注入请求未返回健康成功", s >= 400 or (isinstance(j, dict) and j.get("状态") == "下发失败"), f"{s} {j}")

    gs, gt = 票(t)
    甲已下发 = gs == 200 and isinstance(gt, dict) and gt.get("状态") == "已下发"
    check("甲票非已下发（GET 票）", not 甲已下发, f"status={gs} body={str(gt)[:160]}")

    c = 核证(t)
    check("甲 核证.已下发=false", c.get("已下发") is False, str(c.get("已下发")))
    check("甲 核证.计划有无=false", c.get("计划有无") is False)
    check("甲 核证.可否晋升=false", c.get("可否晋升") is False)
    check("甲 核证.valid=false", c.get("valid") is False)
    check("甲 计划行不存在", len(计划行(t)) == 0, f"{len(计划行(t))} 行")

    vs, versions = call("GET", "/api/开关版本")
    vstate = next((x.get("状态") for x in versions if x.get("版本键") == vk), None) if isinstance(versions, list) else None
    check("甲 版本灰度态随事务回退（非灰度中）", vstate not in ("灰度中",), f"版本状态={vstate}")

    s, _ = call("POST", "/api/晋升", {"票号": t})
    check("甲 失败态晋升被拒", s >= 400, f"HTTP {s}")

    
    s, j = call("POST", "/api/下发", {"票号": t, "版本键": vk, "桶键": bk, "边缘们": ["edge-a", "edge-b"]})
    check("甲 重发成功", s == 200 and isinstance(j, dict) and j.get("valid") is True, f"{s} {str(j)[:160]}")
    c = 核证(t)
    check("甲 重发后计划有、valid=true", c.get("计划有无") and c.get("valid"), str({k: c.get(k) for k in ('计划有无', 'valid')}))
    ok, why = 回读两端(t)
    check("甲 重发后两端回读可落", ok, why)
    c = 核证(t)
    check("甲 回读齐套后可否晋升=true", c.get("可否晋升") is True, str(c.get("待回读边缘")))
    s, j = call("POST", "/api/晋升", {"票号": t})
    check("甲 全量晋升放行", s == 200 and isinstance(j, dict) and j.get("放行") is True, f"{s} {str(j)[:160]}")


def 场景乙_悬挂():
    print("\n[乙] 口径二：缺计划悬挂（乙票已下发但晋升拒，补计划后走通）")
    vk, bk = 铺底("yi")
    t = 取票号("乙")
    s, j = call("POST", "/api/下发", {
        "票号": t, "版本键": vk, "桶键": bk, "边缘们": ["edge-a", "edge-b"],
        "计划写失败": True, "计划失败口径": "悬挂",
    })
    print(f"  · 注入下发响应 HTTP {s}")
    check("乙 注入请求已受理为悬挂态", s == 200, f"{s} {str(j)[:200]}")

    gs, gt = 票(t)
    check("乙票 GET 为已下发", gs == 200 and gt.get("状态") == "已下发", f"{gs} {str(gt)[:160]}")
    check("乙票行内可见缺计划标记(缺计划=1)", gs == 200 and gt.get("缺计划") == 1, str(gt.get("缺计划") if isinstance(gt, dict) else None))

    c = 核证(t)
    check("乙 核证.已下发=true（与甲可区分）", c.get("已下发") is True)
    check("乙 核证.计划有无=false", c.get("计划有无") is False)
    check("乙 核证.缺计划标记=true", c.get("缺计划标记") is True)
    check("乙 核证.可否晋升=false", c.get("可否晋升") is False)
    check("乙 核证.valid=false", c.get("valid") is False)

    before = len(call("GET", "/api/回读证")[1]) if isinstance(call("GET", "/api/回读证")[1], list) else 0
    s, j = call("POST", "/api/回读", {"票号": t, "边缘键": "edge-a"})
    check("乙 缺计划时确认回读一律拒绝", s >= 400, f"HTTP {s}")
    after_rows = call("GET", "/api/回读证")[1]
    after = len(after_rows) if isinstance(after_rows, list) else before
    check("乙 被拒回读不落库（确认入口不空转）", after == before, f"before={before} after={after}")

    s, j = call("POST", "/api/晋升", {"票号": t})
    check("乙 缺计划时全量晋升一律拒绝", s >= 400, f"HTTP {s}")
    vs, versions = call("GET", "/api/开关版本")
    vstate = next((x.get("状态") for x in versions if x.get("版本键") == vk), None) if isinstance(versions, list) else None
    check("乙 被拒后版本未全量", vstate != "已全量", f"版本状态={vstate}")

    s, j = call("POST", "/api/补计划", {"票号": t, "边缘们": ["edge-a", "edge-b"]})
    check("乙 补建计划成功且标记清除", s == 200 and j.get("计划有无") and not j.get("缺计划标记") and j.get("valid"),
          f"{s} {str(j)[:180]}")
    ok, why = 回读两端(t)
    check("乙 补计划后回读可落", ok, why)
    c = 核证(t)
    check("乙 齐套后可否晋升=true", c.get("可否晋升") is True, str(c.get("待回读边缘")))
    s, j = call("POST", "/api/全量晋升", {"票号": t})
    check("乙 补计划+回读后全量晋升放行", s == 200 and j.get("放行") is True, f"{s} {str(j)[:160]}")


def 场景开关一次性():
    print("\n[开关注入] POST /api/故障注入 武装：默认一次性，口径须随开关，耗尽后干净重发成功")
    
    vk, bk = 铺底("swjia")
    t = 取票号("开关甲")
    s, j = call("POST", "/api/故障注入", {"口径": "回退"})
    check("开关注入默认一次性(剩余次数=1)", s == 200 and isinstance(j, dict) and j.get("剩余次数") == 1, f"{s} {j}")
    s, j = call("POST", "/api/下发", {"票号": t, "版本键": vk, "桶键": bk})  
    d = (j or {}).get("detail") if isinstance(j, dict) else None
    check("开关武装 首次干净请求仍注入为甲(400/非已下发)",
          s >= 400 and isinstance(d, dict) and d.get("已下发") is False, f"{s} {str(j)[:180]}")
    s, j = call("GET", "/api/故障注入")
    sw = next((x for x in (j or {}).get("开关", []) if x.get("键") == "计划写失败"), None)
    check("一次性次数已被消耗到 0（不被回滚撤销）", bool(sw) and sw.get("剩余次数") == 0, str(sw))
    s, j = call("POST", "/api/下发", {"票号": t, "版本键": vk, "桶键": bk, "边缘们": ["edge-a", "edge-b"]})
    check("开关耗尽后同票干净重发成功 valid=true",
          s == 200 and isinstance(j, dict) and j.get("valid") is True, f"{s} {str(j)[:160]}")
    call("POST", "/api/故障注入/复位")

    
    vk2, bk2 = 铺底("swyi")
    t2 = 取票号("开关乙")
    s, _ = call("POST", "/api/故障注入", {"口径": "悬挂"})
    check("悬挂开关武装成功", s == 200, f"HTTP {s}")
    s, j = call("POST", "/api/下发", {"票号": t2, "版本键": vk2, "桶键": bk2})
    check("开关口径=悬挂 时票保持已下发且打缺计划标记",
          s == 200 and isinstance(j, dict) and j.get("已下发") is True and j.get("缺计划标记") is True,
          f"{s} {str(j)[:200]}")
    check("悬挂开关票 晋升/valid 闸止",
          isinstance(j, dict) and j.get("可否晋升") is False and j.get("valid") is False, str(j)[:200])
    
    s, j = call("POST", "/api/补计划", {"票号": t2, "边缘们": ["edge-a", "edge-b"]})
    check("悬挂开关票补计划后标记清除 valid=true",
          s == 200 and isinstance(j, dict) and j.get("缺计划标记") is False and j.get("valid") is True, f"{s} {str(j)[:160]}")
    call("POST", "/api/故障注入/复位")


def 场景裸孤儿():
    print("\n[裸孤儿] 断言假已下发：有票无计划且无标记，必须被抓住")
    vk, bk = 铺底("orph")
    t = 取票号("裸")
    s, _ = call("POST", "/api/下发", {"票号": t, "版本键": vk, "桶键": bk, "边缘们": ["edge-a", "edge-b"]})
    assert s == 200
    s, c0 = call("POST", "/api/故障注入/裸孤儿", {"票号": t})
    check("裸孤儿造数成功", s == 200 and isinstance(c0, dict), f"{s} {c0}")

    c = 核证(t)
    check("假已下发 票仍是已下发", c.get("已下发") is True)
    check("假已下发 计划有无=false", c.get("计划有无") is False)
    check("假已下发 valid=false", c.get("valid") is False)
    check("假已下发 核证缺计划标记=true(有效) 或 暗缺计划=true",
          c.get("缺计划标记") is True or c.get("暗缺计划") is True,
          f"标记={c.get('缺计划标记')} 暗={c.get('暗缺计划')} 存储={c.get('存储缺计划标记')}")
    s, _ = call("POST", "/api/回读", {"票号": t, "边缘键": "edge-a"})
    check("假已下发 回读被拒", s >= 400, f"HTTP {s}")
    s, _ = call("POST", "/api/晋升", {"票号": t})
    check("假已下发 晋升被拒", s >= 400, f"HTTP {s}")
    s, g = call("POST", "/api/贯验")
    说明 = g.get("说明", "") if isinstance(g, dict) else ""
    check("贯验判不通过并点名 有票无计划假已下发", isinstance(g, dict) and g.get("是否通过") is False and "假已下发" in 说明,
          f"{s} {说明[:200]}")

    s, j = call("POST", "/api/补计划", {"票号": t, "边缘们": ["edge-a", "edge-b"]})
    check("裸孤儿 补计划后 valid=true", s == 200 and j.get("valid") is True, f"{s}")
    call("POST", "/api/回读", {"票号": t, "边缘键": "edge-a"})
    call("POST", "/api/回读", {"票号": t, "边缘键": "edge-b"})
    s, g = call("POST", "/api/贯验")
    check("治愈后贯验重新通过", isinstance(g, dict) and g.get("是否通过") is True, str(g.get("说明") if isinstance(g, dict) else g))


def 场景并发不同票号():
    print("\n[并发一] 同 版本+桶 八票号同时第二次下发交错：只能有一张有效已下发")
    vk, bk = 铺底("par")
    K = 8
    base = 取票号("并")  
    names = [f"{base}-{i}" for i in range(K)]
    barrier = threading.Barrier(K)
    results = [None] * K

    def worker(i):
        body = {"票号": names[i], "版本键": vk, "桶键": bk, "边缘们": ["edge-a", "edge-b"]}
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        results[i] = call("POST", "/api/下发", body, 超时=30)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(K)]
    t0 = time.time()
    for x in ts:
        x.start()
    for x in ts:
        x.join()
    print(f"  · {K} 并发完成，用时 {time.time()-t0:.2f}s，状态码={[r[0] for r in results]}")

    成功 = sum(1 for s, j in results if s == 200 and isinstance(j, dict) and j.get("状态") == "已下发")
    check("并发恰有 1 张下发成功", 成功 == 1, f"成功数={成功} codes={[r[0] for r in results]}")

    
    s, rows = call("GET", "/api/下发票")
    有效 = [r for r in rows if isinstance(r, dict) and r.get("版本键") == vk and r.get("桶键") == bk
            and r.get("状态") == "已下发" and not r.get("缺计划")]
    check("不得双有效已下发（库内有效计数=1）", len(有效) == 1, f"有效={len(有效)} 票={[r.get('票号') for r in 有效]}")

    
    if 有效:
        n = len(计划行(有效[0]["票号"]))
        check("成功票计划行恰为 2（无重复计划）", n == 2, f"计划行={n}")


def 场景并发同票号():
    print("\n[并发二] 同票号六并发重发：一行一票、计划不重复、幂等或成功")
    vk, bk = 铺底("same")
    t = 取票号("同")
    K = 6
    barrier = threading.Barrier(K)
    results = [None] * K

    def worker(i):
        body = {"票号": t, "版本键": vk, "桶键": bk, "边缘们": ["edge-a", "edge-b"]}
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        results[i] = call("POST", "/api/下发", body, 超时=30)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(K)]
    for x in ts:
        x.start()
    for x in ts:
        x.join()
    ok_codes = [s for s, _ in results if s == 200]
    check("同票号并发全部 200（成功或幂等）", len(ok_codes) == K, f"codes={[r[0] for r in results]}")
    gs, gt = 票(t)
    check("同票号只有一行且已下发", gs == 200 and gt.get("状态") == "已下发", f"{gs}")
    check("同票号计划行恰为 2（并发未造重复计划）", len(计划行(t)) == 2, f"{len(计划行(t))}")
    c = 核证(t)
    check("同票号 valid=true", c.get("valid") is True)


def 等健康():
    for i in range(30):
        s, j = call("GET", "/api/健康")
        if s == 200 and isinstance(j, dict) and j.get("正常"):
            print(f"已连接灰度轨后端：{BASE}")
            return True
        time.sleep(1)
    print(f"连不上服务 {BASE}/api/健康 最后响应：{s} {j}")
    return False


def main():
    global BASE
    args = sys.argv[1:]
    if "--base" in args:
        BASE = args[args.index("--base") + 1].rstrip("/")
    if not 等健康():
        return 2
    try:
        场景甲_回退()
        场景乙_悬挂()
        场景开关一次性()
        场景裸孤儿()
        场景并发不同票号()
        场景并发同票号()
    finally:
        call("POST", "/api/故障注入/复位")

    print("\n" + "=" * 64)
    print(f"结果：{通过} 通过 / {失败} 失败")
    if 失败:
        print("失败项：")
        for n, d in 失败明细:
            print(f" - {n} :: {d}")
        print("=" * 64)
        return 1
    print("全部断言通过：无「有票无计划」假成功，并发无双有效已下发。")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
