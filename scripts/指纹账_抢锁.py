"""快照指纹账 · 抢锁夹具（std-lib only）。

断言（下发与指纹补登并发交错，须失败闭）：
  1. 并发下发 + 指纹补登不得产生「票已发而指纹空」。
  2. 结束后：要么票已下发且指纹 valid（补登/下发都成功），
     要么票仍无指纹且核证 valid=false —— 绝不允许 已下发 + 指纹空 + 对照绿。
  3. 终结态回读对照闸：valid=false 时回读必拒；valid=true 时回读可绿。
  4. 同票号下发抢锁不留重复计划行。
  5. 大量并发重发后指纹行恰一行一票（无重复指纹）。

用法：
  python3 scripts/指纹账_抢锁.py --base http://127.0.0.1:11800
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


def call(方法, 路径, 体=None, 超时=30):
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


def 铺底(标记):
    版本键 = f"v.{标记}.{RUN}@1"
    开关键 = f"k.{标记}.{RUN}"
    桶键 = f"b.{标记}.{RUN}"
    s, _ = call("POST", "/api/入轨", {"版本": [{"开关键": 开关键, "版本号": 1, "版本键": 版本键}]})
    assert s == 200, f"入轨失败 {s}"
    s, _ = call("POST", "/api/分桶", {"桶键": 桶键, "开关键": 开关键})
    assert s == 200, f"分桶失败 {s}"
    return 开关键, 版本键, 桶键


def 指纹(票号):
    q = urllib.parse.urlencode({"票号": 票号})
    s, j = call("GET", f"/api/指纹账?{q}")
    return j if isinstance(j, dict) else {}


def 计划行(票号):
    q = urllib.parse.urlencode({"票号": 票号})
    s, j = call("GET", f"/api/回读计划?{q}")
    return j if isinstance(j, list) else []


def 核证(票号):
    q = urllib.parse.urlencode({"票号": 票号})
    s, j = call("GET", f"/api/计划核证?{q}")
    return j if isinstance(j, dict) else {}


def 场景_服务端抢锁():
    print("\n[抢锁一] 服务端内置夹具：下发 ∥ 指纹补登 并发交错，失败闭")
    _, 版本键, 桶键 = 铺底("lock")
    票号 = f"票-lock-{RUN}"
    s, j = call("POST", "/api/下发", {"票号": 票号, "版本键": 版本键, "桶键": 桶键,
                                    "边缘们": ["edge-a", "edge-b"]})
    assert s == 200, f"前置下发失败 {s}"
    s, out = call("POST", "/api/故障注入/抢锁", {"票号": 票号})
    check("抢锁夹具受理", s == 200 and isinstance(out, dict), f"{s} {str(out)[:160]}")
    指纹终 = out.get("指纹终") or {}
    票终态 = out.get("票终态", "")
    check("抢锁后不得票已发而指纹空", not (票终态 == "已下发" and not 指纹终.get("valid")),
          f"票态={票终态} 指纹valid={指纹终.get('valid')} 有无={指纹终.get('指纹有无')}")
    check("抢锁夹具自判失败闭", out.get("失败闭") is True, str(out.get("抢锁结果"))[:200])
    证 = 指纹(票号)
    if 证.get("valid"):
        s, j = call("POST", "/api/回读", {"票号": 票号, "边缘键": "edge-a"})
        check("抢锁终态有效指纹下回读可绿", s == 200, f"{s}")
    else:
        s, j = call("POST", "/api/回读", {"票号": 票号, "边缘键": "edge-a"})
        check("抢锁终态无效指纹下回读必拒", s == 400, f"{s} {str(j)[:160]}")
    check("抢锁后计划行恰 2（无重复）", len(计划行(票号)) == 2, f"{len(计划行(票号))}")


def 场景_同票号并发重发():
    print("\n[抢锁二] 同票号 6 路并发「下发+补登」混合：指纹一行一票、无空行")
    开关键, 版本键, 桶键 = 铺底("mix")
    票号 = f"票-mix-{RUN}"
    s, _ = call("POST", "/api/下发", {"票号": 票号, "版本键": 版本键, "桶键": 桶键,
                                    "边缘们": ["edge-a", "edge-b"]})
    assert s == 200
    s, _ = call("POST", "/api/故障注入/删指纹", {"票号": 票号})
    assert s == 200
    s, comp = call("POST", "/api/指纹/补偿", {"票号": 票号, "开关键": 开关键})
    assert s == 200, f"补偿票签发失败 {s} {comp}"
    补偿 = comp["补偿票"]

    K = 6
    栅栏 = threading.Barrier(K)
    结果 = [None] * K

    def worker(i):
        try:
            栅栏.wait(timeout=6)
        except Exception:
            pass
        if i % 2 == 0:
            结果[i] = call("POST", "/api/下发", {
                "票号": 票号, "版本键": 版本键, "桶键": 桶键,
                "边缘们": ["edge-a", "edge-b"], "补偿票": 补偿,
            })
        else:
            结果[i] = call("POST", "/api/指纹/补登", {"票号": 票号, "补偿票": 补偿})

    线程们 = [threading.Thread(target=worker, args=(i,)) for i in range(K)]
    t0 = time.time()
    for x in 线程们:
        x.start()
    for x in 线程们:
        x.join()
    print(f"  · {K} 并发完成，用时 {time.time()-t0:.2f}s，码={[r[0] if r else None for r in 结果]}")

    ok = [s for s, _ in (r for r in 结果 if r)]
    check("至少一路成功（下发或补登）", any(c == 200 for c in ok), f"码={ok}")
    证 = 指纹(票号)
    check("混合并发后指纹 valid=true", 证.get("valid") is True, str(证)[:200])
    check("指纹哈希与票面一致（无空行）", 证.get("哈希") and 证.get("哈希") == 证.get("票面哈希"), str(证)[:160])
    核 = 核证(票号)
    check("混合并发后票核证 valid=true", 核.get("valid") is True, str(核)[:160])
    check("混合并发后计划行恰 2", len(计划行(票号)) == 2, f"{len(计划行(票号))}")

    # 指纹行一行一票（唯一索引）
    s, rows = call("GET", "/api/指纹账")
    all_fp = rows.get("指纹账", []) if isinstance(rows, dict) else []
    mine = [x for x in all_fp if x.get("票号") == 票号]
    check("指纹账一行一票（无重复指纹行）", len(mine) == 1, f"{len(mine)}")

    # 终态回读对照
    for e in ("edge-a", "edge-b"):
        s, j = call("POST", "/api/回读", {"票号": 票号, "边缘键": e, "补偿票": 补偿})
        check(f"抢锁后回读对照放行 {e}", s == 200, f"{s} {str(j)[:120]}")


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

    场景_服务端抢锁()
    场景_同票号并发重发()

    print("\n" + "=" * 64)
    print(f"结果：{通过} 通过 / {失败} 失败")
    if 失败:
        for n, d in 失败明细:
            print(f" - {n} :: {d}")
        print("=" * 64)
        return 1
    print("抢锁夹具断言通过：下发/补登交错失败闭，绝无票已发指纹空。")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
