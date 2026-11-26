import React, { useEffect, useState } from "react";
import { get, post, postFixture } from "../api.js";

export default function 回读台() {
  const [rows, setRows] = useState([]);
  const [plans, setPlans] = useState([]);
  const [certs, setCerts] = useState([]);
  const [讯, set讯] = useState("");
  const [坏, set坏] = useState(false);
  const [忙, set忙] = useState(false);
  const [form, setForm] = useState({ 票号: "", 边缘键: "edge-a", 结果: "确认", 所见版本键: "" });

  const 刷 = async () => {
    const [z, p, c] = await Promise.all([get("/回读证"), get("/回读计划"), get("/计划核证")]);
    setRows(z); setPlans(p); setCerts(Array.isArray(c) ? c : []);
  };
  useEffect(() => { 刷().catch((e) => { set坏(true); set讯(String(e.message || e)); }); }, []);

  const 提交回读 = async () => {
    if (!form.票号 || !form.边缘键) { set坏(true); set讯("请填票号与边缘键"); return; }
    set忙(true);
    try {
      const out = await post("/回读", {
        票号: form.票号, 边缘键: form.边缘键, 结果: form.结果,
        所见版本键: form.所见版本键 || undefined,
      });
      set坏(false);
      set讯(`已记回读：${out.证号} → ${out.结果}${out.未齐套边缘数 ? `，未齐 ${out.未齐套边缘数} 边缘` : "，已齐套"}`);
      await 刷();
    } catch (e) {
      set坏(true);
      set讯(`确认入口拒绝（未空转）：${e.message || e}`);
    } finally {
      set忙(false);
    }
  };

  const 补计划 = async (票号) => {
    set忙(true);
    try {
      await post("/补计划", { 票号 });
      await 刷();
      set坏(false); set讯(`已为 ${票号} 补建计划并清除缺计划标记`);
    } catch (e) {
      set坏(true); set讯(e.message || String(e));
    } finally {
      set忙(false);
    }
  };

  const 缺计划票 = certs.filter((c) => c.已下发 && (c.缺计划标记 || !c.计划有无));

  return (
    <div>
      <h1 className="题">回读台 · 计划核证</h1>
      <p className="述">
        回读必须锚定同票计划行。票缺计划（明标记或有票无计划）时，确认回读一律拒绝；
        全边缘确认齐套且无偏差，核证「可否晋升」才为真。
      </p>

      <div className="行">
        <button onClick={async () => { await postFixture("回读样例"); await 刷(); set坏(false); set讯("已灌回读样例（edge-a/edge-b）"); }}>灌回读样例</button>
        <button className="次" onClick={() => 刷().catch((e) => { set坏(true); set讯(e.message); })}>刷新</button>
      </div>

      <div className="核证格" style={{ marginBottom: "0.6rem" }}>
        <input placeholder="票号" value={form.票号} style={{ minWidth: 260 }}
          onChange={(e) => setForm({ ...form, 票号: e.target.value })} />
        <input placeholder="边缘键" value={form.边缘键} style={{ minWidth: 140 }}
          onChange={(e) => setForm({ ...form, 边缘键: e.target.value })} />
        <select value={form.结果} onChange={(e) => setForm({ ...form, 结果: e.target.value })}>
          <option value="确认">确认</option>
          <option value="偏差">偏差</option>
        </select>
        <input placeholder="所见版本键（可空=票面版本）" value={form.所见版本键} style={{ minWidth: 220 }}
          onChange={(e) => setForm({ ...form, 所见版本键: e.target.value })} />
        <button className="信" disabled={忙} onClick={提交回读}>提交回读</button>
      </div>
      {讯 && <p className={坏 ? "警示条" : "讯"}>{坏 ? "⚠ " : ""}{讯}</p>}

      {缺计划票.length > 0 && (
        <div className="警示条">
          检测到 {缺计划票.length} 张「已下发却缺计划」票（含暗缺计划假已下发）：
          {缺计划票.map((c) => (
            <span key={c.票号} style={{ marginRight: "0.8rem" }}>
              <code>{c.票号}</code>
              {c.暗缺计划 ? "（暗缺计划·假已下发）" : "（缺计划标记）"}
              <button className="小钮 信" style={{ marginLeft: 6 }} disabled={忙} onClick={() => 补计划(c.票号)}>补建计划</button>
            </span>
          ))}
        </div>
      )}

      <h2 className="段题">计划核证总览（票号 · 计划有无 · 缺计划标记 · 可否晋升 · valid）</h2>
      {!certs.length ? <div className="空态">尚无票可核证</div> : (
        <table>
          <thead><tr>
            <th>票号</th><th>已下发</th><th>计划有无</th><th>缺计划标记</th>
            <th>可否晋升</th><th>valid</th><th>齐套</th><th>待回读 / 偏差</th><th>补建</th>
          </tr></thead>
          <tbody>{certs.map((c) => (
            <tr key={c.票号}>
              <td className="票号cell">{c.票号}</td>
              <td>{String(c.已下发)}</td>
              <td><span className={"徽章 " + (c.计划有无 ? "通" : "败")}>{String(c.计划有无)}（{c.计划行数 ?? 0}）</span></td>
              <td>
                {c.暗缺计划 ? <span className="徽章 败 脉">true·暗</span>
                  : <span className={"徽章 " + (c.缺计划标记 ? "警" : "通")}>{String(c.缺计划标记)}</span>}
              </td>
              <td><span className={"徽章 " + (c.可否晋升 ? "通" : "灰")}>{String(c.可否晋升)}</span></td>
              <td><span className={"徽章 " + (c.valid ? "通" : "败")}>{String(c.valid)}</span></td>
              <td>{String(c.齐套)}</td>
              <td style={{ fontSize: "0.76rem" }}>
                {(c.待回读边缘 || []).join(",") || "—"}{(c.偏差边缘 || []).length ? ` / 偏差:${c.偏差边缘.join(",")}` : ""}
              </td>
              <td>{(!c.计划有无 || c.缺计划标记)
                ? <button className="小钮 信" disabled={忙} onClick={() => 补计划(c.票号)}>补建计划</button>
                : <span className="徽章 通">已齐</span>}</td>
            </tr>
          ))}</tbody>
        </table>
      )}

      <h2 className="段题">回读计划表（边缘计划行）</h2>
      {!plans.length ? <div className="空态">尚无回读计划行——已下发票应在下发同事务落计划；缺计划票请补建</div> : (
        <table>
          <thead><tr><th>票号</th><th>计划边缘</th><th>行状态</th><th>所见版本</th><th>回读证号</th><th>更新时</th></tr></thead>
          <tbody>{plans.map((p) => (
            <tr key={`${p.票号}-${p.边缘键}`}>
              <td className="票号cell">{p.票号}</td>
              <td>{p.边缘键}</td>
              <td><span className={"徽章 " + (p.状态 === "已确认" ? "通" : p.状态 === "偏差" ? "败" : "灰")}>{p.状态}</span></td>
              <td>{p.所见版本键 || "—"}</td>
              <td className="票号cell">{p.回读证号 || "—"}</td>
              <td>{p.更新时}</td>
            </tr>
          ))}</tbody>
        </table>
      )}

      <h2 className="段题">回读证</h2>
      {!rows.length ? <div className="空态">尚无回读证</div> : (
        <table>
          <thead><tr><th>证号</th><th>票号</th><th>边缘</th><th>所见版本</th><th>结果</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.证号}><td className="票号cell">{r.证号}</td><td className="票号cell">{r.票号}</td><td>{r.边缘键}</td>
              <td>{r.所见版本键}</td>
              <td><span className={"徽章 " + (r.结果 === "确认" ? "通" : "败")}>{r.结果}</span></td></tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}
