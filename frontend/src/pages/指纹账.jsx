import React, { useEffect, useState } from "react";
import { get, post } from "../api.js";

function 徽(v, 真 = "通", 假 = "败") {
  return <span className={"徽章 " + (v ? 真 : 假)}>{String(!!v)}</span>;
}

export default function 核证指纹账() {
  const [账, set账] = useState([]);
  const [讯, set讯] = useState("");
  const [坏, set坏] = useState(false);
  const [忙, set忙] = useState(false);
  const [form, setForm] = useState({ 票号: "", 补偿票: "" });

  const 刷 = async () => {
    const out = await get("/核证/指纹账");
    set账(Array.isArray(out?.指纹账) ? out.指纹账 : []);
  };
  useEffect(() => { 刷().catch((e) => { set坏(true); set讯(String(e.message || e)); }); }, []);

  const 补偿 = async () => {
    if (!form.票号) { set坏(true); set讯("请填票号"); return; }
    set忙(true);
    try {
      const out = await post("/指纹/补偿", { 票号: form.票号 });
      setForm({ ...form, 补偿票: out.补偿票 });
      await 刷();
      set坏(false); set讯(`已签发补偿票：${out.补偿票}（开关键 ${out.开关键}）`);
    } catch (e) { set坏(true); set讯(`签补偿票被拒：${e.message || e}`); }
    finally { set忙(false); }
  };

  const 补登 = async () => {
    if (!form.票号 || !form.补偿票) { set坏(true); set讯("请填票号与补偿票"); return; }
    set忙(true);
    try {
      await post("/指纹/补登", { 票号: form.票号, 补偿票: form.补偿票 });
      await 刷();
      set坏(false); set讯("已持补偿票补登/重钉快照指纹");
    } catch (e) { set坏(true); set讯(`补登被拒：${e.message || e}`); }
    finally { set忙(false); }
  };

  return (
    <div>
      <h1 className="题">指纹账核证</h1>
      <p className="述">
        每一次成功下发都在同事务落下快照指纹行（开关键 · 票号 · 载荷哈希 · 分桶快照摘要）。
        缺指纹或哈希对不上时，同开关键再次意图与回读对照一律失败；仅持补偿票可重钉。
      </p>

      <div className="核证格" style={{ marginBottom: "0.6rem" }}>
        <input placeholder="票号" value={form.票号} style={{ minWidth: 260 }}
          onChange={(e) => setForm({ ...form, 票号: e.target.value })} />
        <input placeholder="补偿票（签发后自动填入）" value={form.补偿票} style={{ minWidth: 260 }}
          onChange={(e) => setForm({ ...form, 补偿票: e.target.value })} />
        <button className="小钮 警" disabled={忙} onClick={补偿}>签发补偿票</button>
        <button className="小钮 信" disabled={忙} onClick={补登}>持票补登重钉</button>
        <button className="次" onClick={() => 刷().catch((e) => { set坏(true); set讯(e.message); })}>刷新</button>
      </div>
      {讯 && <p className={坏 ? "警示条" : "讯"}>{坏 ? "⚠ " : ""}{讯}</p>}

      {!账.length ? <div className="空态">尚无下发票可核证指纹</div> : (
        <table>
          <thead><tr>
            <th>票号</th><th>开关键</th><th>已下发</th><th>指纹有无</th>
            <th>哈希</th><th>哈希一致</th><th>补偿有无</th><th>valid</th><th>原因</th>
          </tr></thead>
          <tbody>{账.map((c) => (
            <tr key={c.票号}>
              <td className="票号cell">{c.票号}</td>
              <td>{c.开关键}</td>
              <td>{徽(c.已下发)}</td>
              <td>{徽(c.指纹有无, "通", "败")}</td>
              <td className="票号cell" style={{ fontSize: "0.7rem" }}>
                {c.哈希 ? c.哈希.slice(0, 16) + "…" : "—"}
              </td>
              <td>{徽(c.哈希一致)}</td>
              <td>{徽(c.补偿有无, "警", "灰")}</td>
              <td>{徽(c.valid)}</td>
              <td style={{ fontSize: "0.74rem", color: c.valid ? "var(--淡)" : "var(--败)" }}>{c.原因 || "—"}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}
