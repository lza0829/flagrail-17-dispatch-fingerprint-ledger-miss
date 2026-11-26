import React, { useEffect, useState } from "react";
import { get, post, postFixture } from "../api.js";

function 状态徽章(s) {
  const cls = s === "已下发" ? "通" : s === "下发失败" ? "败" : s === "已全量" ? "信" : "灰";
  return <span className={`徽章 ${cls}`}>{s}</span>;
}

export default function 下发票() {
  const [rows, setRows] = useState([]);
  const [讯, set讯] = useState("");
  const [坏, set坏] = useState(false);
  const [cert, setCert] = useState(null);
  const [忙, set忙] = useState(false);
  const [form, setForm] = useState({
    票号: "", 版本键: "", 桶键: "", 边缘: "edge-a,edge-b", 注入: false, 口径: "回退",
    指纹注入: false, 补偿票: "",
  });

  const 刷 = async () => setRows(await get("/下发票"));
  useEffect(() => { 刷().catch((e) => { set坏(true); set讯(String(e.message || e)); }); }, []);

  const 报 = (ok, msg) => { set坏(!ok); set讯(msg); };
  const 包 = async (fn, okmsg) => {
    set忙(true);
    try {
      const out = await fn();
      await 刷();
      if (cert?.票号) { try { setCert(await get(`/计划核证?票号=${encodeURIComponent(cert.票号)}`)); } catch {  } }
      报(true, okmsg || "完成");
      return out;
    } catch (e) {
      报(false, `被拒/失败：${e.message || e}`);
      return null;
    } finally {
      set忙(false);
    }
  };

  const 下发 = () => 包(async () => {
    const body = {
      版本键: form.版本键.trim(), 桶键: form.桶键.trim(),
      票号: form.票号.trim(),
      边缘们: form.边缘.split(",").map((s) => s.trim()).filter(Boolean),
    };
    if (form.注入) { body.计划写失败 = true; body.计划失败口径 = form.口径; }
    if (form.指纹注入) { body.指纹写失败 = true; }
    if (form.补偿票.trim()) { body.补偿票 = form.补偿票.trim(); }
    const out = await post("/下发", body);
    if (out?.票号) setCert(out);
    return out;
  }, form.注入 ? `已注入计划写失败（口径=${form.口径}），请核证票态` : "下发完成，计划同票落库");

  const 重发 = (r) => 包(async () => {
    const edges = r.计划边缘?.length ? r.计划边缘 : ["edge-a", "edge-b"];
    const body = { 票号: r.票号, 版本键: r.版本键, 桶键: r.桶键, 边缘们: edges };
    if (form.补偿票.trim()) body.补偿票 = form.补偿票.trim();
    const out = await post("/下发", body);
    setCert(out);
    return out;
  }, "已重发：票 / 计划 / 快照指纹同事务落库（缺指纹且未持补偿票将被拒）");

  const 补计划 = (r) => 包(async () => {
    const out = await post("/补计划", { 票号: r.票号, 边缘们: r.计划边缘?.length ? r.计划边缘 : ["edge-a", "edge-b"] });
    setCert(out);
    return out;
  }, "计划已补建，缺计划标记清除");

  const 晋升 = (r) => 包(async () => {
    const out = await post("/全量晋升", { 票号: r.票号 });
    setCert(out);
    return out;
  }, "闸放成功，已全量晋升");

  const 核证 = async (r) => {
    try { setCert(await get(`/下发票/${encodeURIComponent(r.票号)}/核证`)); set坏(false); set讯(""); }
    catch (e) { 报(false, e.message || String(e)); }
  };

  const 删指纹 = (r) => 包(async () => {
    const out = await post("/故障注入/删指纹", { 票号: r.票号 });
    setCert(out);
    return out;
  }, "已抹掉该票快照指纹行：再次意图/回读对照应按缺指纹拒绝");

  const 签补偿 = (r) => 包(async () => {
    const out = await post("/指纹/补偿", { 票号: r.票号 });
    setForm((f) => ({ ...f, 票号: r.票号, 补偿票: out.补偿票 }));
    return out;
  }, "已签发补偿票：持票可再次意图落新已下发并重钉指纹");

  const 补登 = (r) => 包(async () => {
    if (!form.补偿票.trim()) throw new Error("需先签发/填入补偿票");
    const out = await post("/指纹/补登", { 票号: r.票号, 补偿票: form.补偿票.trim() });
    setCert(out);
    return out;
  }, "已持补偿票补登/重钉快照指纹");

  const 造裸孤儿 = (r) => 包(async () => {
    const out = await post("/故障注入/裸孤儿", { 票号: r.票号 });
    setCert(out);
    return out;
  }, "已模拟修复前裸孤儿（有票无计划无标记），核证应判假");

  return (
    <div>
      <h1 className="题">下发票 · 下发回读计划同票</h1>
      <p className="述">
        票 / 边缘回读计划 / 快照指纹必须同成败、同事务可见。计划写失败时：<b>回退口径</b>票不得停留已下发；
        <b>悬挂口径</b>票保持已下发但打<b>缺计划</b>标记，补建前确认回读与全量晋升一律拒绝。
        快照指纹缺失或哈希对不上时，同开关键再次意图与回读对照失败；仅持<b>补偿票</b>可重钉放行。
      </p>

      <div className="行">
        <button onClick={() => 包(() => postFixture("下发样例"), "已灌下发样例（含 edge-a/edge-b 计划）")}>灌下发样例</button>
        <button className="次" onClick={() => 刷().then(() => 报(true, "已刷新")).catch((e) => 报(false, e.message))}>刷新</button>
      </div>

      <div className="核证格" style={{ marginBottom: "0.8rem" }}>
        <input placeholder="版本键 如 checkout.new_tax@3" value={form.版本键}
          onChange={(e) => setForm({ ...form, 版本键: e.target.value })} style={{ minWidth: 220 }} />
        <input placeholder="桶键 如 checkout.new_tax-gray10" value={form.桶键}
          onChange={(e) => setForm({ ...form, 桶键: e.target.value })} style={{ minWidth: 220 }} />
        <input placeholder="票号（可空=自动）" value={form.票号}
          onChange={(e) => setForm({ ...form, 票号: e.target.value })} style={{ minWidth: 200 }} />
        <input placeholder="计划边缘，逗号分隔" value={form.边缘}
          onChange={(e) => setForm({ ...form, 边缘: e.target.value })} style={{ minWidth: 180 }} />
        <label className="勾选">
          <input type="checkbox" checked={form.注入}
            onChange={(e) => setForm({ ...form, 注入: e.target.checked })} />
          末步注入计划写失败
        </label>
        <label className="勾选">
          <input type="checkbox" checked={form.指纹注入}
            onChange={(e) => setForm({ ...form, 指纹注入: e.target.checked })} />
          注入快照指纹写失败
        </label>
        <input placeholder="补偿票（可空）" value={form.补偿票}
          onChange={(e) => setForm({ ...form, 补偿票: e.target.value })} style={{ minWidth: 240 }} />
        <select value={form.口径} onChange={(e) => setForm({ ...form, 口径: e.target.value })}
          title="计划写失败口径" disabled={!form.注入}>
          <option value="回退">口径一·票随计划回退（甲）</option>
          <option value="悬挂">口径二·缺计划悬挂（乙）</option>
        </select>
        <button className="信" disabled={忙 || !form.版本键 || !form.桶键} onClick={下发}>下发</button>
      </div>

      {讯 && <p className={坏 ? "警示条" : "讯"}>{坏 ? "⚠ " : ""}{讯}</p>}

      {cert && (
        <div className={"核证卡 " + (cert.valid ? "" : "坏")}>
          <b>计划核证</b> · <span className="票号cell">{cert.票号}</span>
          <div className="核证格">
            <span>计划有无：<b style={{ color: cert.计划有无 ? "var(--通)" : "var(--败)" }}>{String(cert.计划有无)}</b>（{cert.计划行数 ?? 0} 行）</span>
            <span>缺计划标记：<b style={{ color: cert.缺计划标记 ? "var(--警)" : "var(--通)" }}>{String(cert.缺计划标记)}</b></span>
            <span>可否晋升：<b style={{ color: cert.可否晋升 ? "var(--通)" : "var(--败)" }}>{String(cert.可否晋升)}</b></span>
            <span>valid：<b style={{ color: cert.valid ? "var(--通)" : "var(--败)" }}>{String(cert.valid)}</b></span>
            <span>已下发：<b>{String(cert.已下发)}</b></span>
            <span>齐套：<b>{String(cert.齐套)}</b></span>
          </div>
          <div className="核证格">
            <span>计划边缘：{(cert.计划边缘 || []).join(", ") || "—"}</span>
            <span style={{ color: "var(--通)" }}>已确认：{(cert.已确认边缘 || []).join(", ") || "—"}</span>
            <span style={{ color: "var(--警)" }}>待回读：{(cert.待回读边缘 || []).join(", ") || "—"}</span>
            <span style={{ color: "var(--败)" }}>偏差：{(cert.偏差边缘 || []).join(", ") || "—"}</span>
          </div>
          {cert.指纹 && (
            <div className="核证格" style={{ marginTop: "0.3rem", borderTop: "1px dashed var(--线弱)", paddingTop: "0.35rem" }}>
              <span>指纹有无：<b style={{ color: cert.指纹.指纹有无 ? "var(--通)" : "var(--败)" }}>{String(cert.指纹.指纹有无)}</b></span>
              <span>哈希一致：<b style={{ color: cert.指纹.哈希一致 ? "var(--通)" : "var(--败)" }}>{String(cert.指纹.哈希一致)}</b></span>
              <span>补偿有无：<b style={{ color: cert.指纹.补偿有无 ? "var(--警)" : "var(--灰, var(--淡))" }}>{String(cert.指纹.补偿有无)}</b></span>
              <span>指纹 valid：<b style={{ color: cert.指纹.valid ? "var(--通)" : "var(--败)" }}>{String(cert.指纹.valid)}</b></span>
              {cert.指纹.哈希 ? <span className="票号cell" style={{ fontSize: "0.7rem" }}>sha256:{cert.指纹.哈希.slice(0, 20)}…</span> : null}
            </div>
          )}
          {cert.故障说明 ? <div className="讯">故障说明：{cert.故障说明}</div> : null}
        </div>
      )}

      {!rows.length ? <div className="空态">尚无下发票（需先入轨 + 分桶）</div> : (
        <table>
          <thead><tr>
            <th>票号</th><th>版本键</th><th>桶键</th><th>状态</th><th>计划</th>
            <th>快照指纹</th><th>缺计划标记</th><th>核证 valid</th><th>晋升</th><th>操作</th><th>下发时</th>
          </tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.票号}>
              <td className="票号cell">{r.票号}</td>
              <td>{r.版本键}</td>
              <td>{r.桶键}</td>
              <td>{状态徽章(r.状态)}</td>
              <td>{r.计划有无 ? <span className="徽章 通">{r.计划行数} 行</span> : <span className="徽章 灰">无计划</span>}</td>
              <td>{(r.指纹 && r.指纹.指纹有无)
                ? (r.指纹.valid
                  ? <span className="徽章 通" title={r.指纹.哈希}>指纹✓ {String(r.指纹.哈希 || "").slice(0, 8)}</span>
                  : <span className="徽章 败" title={r.指纹.原因}>指纹✗</span>)
                : <span className="徽章 败 脉">缺指纹</span>}</td>
              <td>
                {r.暗缺计划
                  ? <span className="徽章 败 脉">假已下发·暗缺计划</span>
                  : (r.缺计划 === 1 || r.存储缺计划标记)
                    ? <span className="徽章 警">缺计划</span>
                    : <span className="徽章 通">正常</span>}
              </td>
              <td><span className={"徽章 " + (r.valid ? "通" : "败")}>{String(!!r.valid)}</span></td>
              <td>
                {r.已全量 ? <span className="徽章 信">已全量</span>
                  : r.可否晋升 ? <span className="徽章 通">可晋升</span>
                  : <span className="徽章 灰">闸止</span>}
              </td>
              <td className="操作cell">
                <button className="小钮 次" onClick={() => 核证(r)}>核证</button>
                <button className="小钮 次" disabled={忙} onClick={() => 重发(r)}>重发</button>
                <button className="小钮 信" disabled={忙 || r.计划有无} onClick={() => 补计划(r)}>补计划</button>
                <button className="小钮" disabled={忙 || !r.可否晋升} onClick={() => 晋升(r)}>全量晋升</button>
                <button className="小钮 警" disabled={忙} title="清空该票计划行并把缺计划标记置0，模拟历史裸孤儿" onClick={() => 造裸孤儿(r)}>造裸孤儿</button>
                <button className="小钮 败" disabled={忙} title="抹掉该票快照指纹行，再现缺行故障面" onClick={() => 删指纹(r)}>删指纹</button>
                <button className="小钮 警" disabled={忙} title="签发该票补偿票（绑定开关键）" onClick={() => 签补偿(r)}>签补偿</button>
                <button className="小钮 信" disabled={忙} title="持补偿票补登/重钉快照指纹" onClick={() => 补登(r)}>重钉指纹</button>
              </td>
              <td>{r.下发时}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}
