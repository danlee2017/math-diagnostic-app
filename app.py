import csv, io, re, random, requests
from datetime import datetime
import streamlit as st
import graphviz

# ==========================================
# 1. 初始化与算法
# ==========================================
st.set_page_config(page_title="微积分加速站", layout="centered")

if "stage" not in st.session_state: st.session_state.stage = "home"
if "result_data" not in st.session_state: st.session_state.result_data = {}
if "strategies" not in st.session_state: st.session_state.strategies = {}
if "graph_data" not in st.session_state: st.session_state.graph_data = []
if "encouragements" not in st.session_state: st.session_state.encouragements = []
if "history_count" not in st.session_state: st.session_state.history_count = 1

BKT_PARAMS = {"default": {"L0": 0.15, "T": 0.28, "G": 0.18, "S": 0.12}}

def update_bkt(current_L, is_correct, node_uid):
    params = BKT_PARAMS.get(node_uid, BKT_PARAMS["default"])
    if is_correct == 1:
        num = current_L * (1 - params["S"]); den = num + (1 - current_L) * params["G"]
    else:
        num = current_L * params["S"]; den = num + (1 - current_L) * (1 - params["G"])
    posterior = num / den if den > 0 else current_L
    return round(posterior + (1 - posterior) * params["T"], 3)

def render_text(text):
    if not text: return ""
    parts = re.split(r'(\$.*?\$)', text)
    return "".join([p if p.startswith("$") else p.replace("_", r"\_").replace("*", r"\*") for p in parts])

def get_coach_message(trigger_type, target_node="", dimension=""):
    encs = [e for e in st.session_state.encouragements if e["trigger_type"] == trigger_type and (e["target_id"] == target_node or e["target_id"] == "ALL") and (dimension == "" or e["psych_dimension"] == dimension)]
    return random.choice(encs)["message"] if encs else "每一次挑战，都是一次自我重塑的机会。"

def render_graph(mastery_data):
    dot = graphviz.Digraph(); dot.attr(rankdir='LR'); dot.attr('node', shape='box', style='rounded,filled', fontname='Microsoft YaHei')
    broken = {uid for uid, p in mastery_data.items() if p < 0.60}
    targets = set(broken)
    for n in st.session_state.graph_data:
        if n["node_uid"] in broken and n["prereq_uids"]:
            for p in [x.strip() for x in n["prereq_uids"].split(",") if x.strip()]: targets.add(p)
            
    nodes = [n for n in st.session_state.graph_data if n["node_uid"] in targets] if broken else st.session_state.graph_data
    dot.attr(label="※ 局部认知聚焦" if broken else "※ 全盘掌握", labelloc="t", fontcolor="#666")
    
    for n in nodes:
        uid, name, prob = n["node_uid"], n["node_name"] or n["node_uid"], mastery_data.get(n["node_uid"], 0.15)
        color, fc = ("#4CAF50", "white") if prob>=0.8 else (("#FFC107", "black") if prob>=0.6 else ("#F44336", "white"))
        dot.node(uid, f"{name}\n{int(prob*100)}%", fillcolor=color, fontcolor=fc)
        if n["prereq_uids"]:
            for p in [x.strip() for x in n["prereq_uids"].split(",") if x.strip()]:
                if p in targets: dot.edge(p, uid)
    return dot

def gen_verify_q(mis_code):
    conf = st.session_state.strategies.get(mis_code)
    if not conf: return {"stem": "请重算错题。", "options": ["A. 完成", "B. 未完成"], "correct": "A", "check_point": "验证完。"}
    vars = {}
    if conf.get("var_range"):
        for pair in conf["var_range"].split(","):
            if ":" in pair:
                v, r = pair.split(":"); mn, mx = map(int, r.strip().split("-")); vars[v.strip()] = random.randint(mn, mx)
    def r_tpl(t): 
        try: return t.format(**vars)
        except: return t
    correct = r_tpl(conf.get("correct_tpl",""))
    opts = [correct, r_tpl(conf.get("wrong1_tpl","")), r_tpl(conf.get("wrong2_tpl","")), "$0$"]
    random.shuffle(opts)
    return {"stem": r_tpl(conf.get("stem_template","")), "options": [f"{'ABCD'[i]}. {o}" for i,o in enumerate(opts)], "correct": "ABCD"[opts.index(correct)], "check_point": f"验证 {mis_code}。"}

# ==========================================
# 2. 数据拉取
# ==========================================
@st.cache_data(ttl=600)
def fetch_data():
    resp = requests.post(st.secrets["WPS_WEBHOOK_URL"], headers={"AirScript-Token": st.secrets["WPS_SCRIPT_TOKEN"]}, json={"Context": {"argv": {}}}, timeout=30)
    data = resp.json().get("data", {}).get("result", {})
    return data.get("questions", []), data.get("strategies", {}), data.get("graph_data", []), data.get("encouragements", [])

try:
    Q, S, G, E = fetch_data()
    st.session_state.update({"strategies": S, "graph_data": G, "encouragements": E})
except Exception as e:
    st.error(f"数据读取失败：{e}"); st.stop()

# ==========================================
# 3. 路由分发
# ==========================================
if st.session_state.stage != "home":
    if st.sidebar.button("🏠 返回主界面"):
        st.session_state.stage = "home"; st.rerun()

if st.session_state.stage == "home":
    st.title("⚡️ 欢迎来到微积分加速站")
    st.write("我是你的专属 AI 认知教练。今天你想做什么？")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("🎯 知识诊断", use_container_width=True): st.session_state.stage = "diagnostic"; st.rerun()
        st.caption("扫描断点，生成学情图谱。")
    with c2:
        if st.button("📝 错题分析", use_container_width=True): st.session_state.stage = "error_analysis"; st.rerun()
        st.caption("🚧 开发中...")
    with c3:
        if st.button("🧑‍🏫 伴学对话", use_container_width=True): st.session_state.stage = "companion"; st.rerun()
        st.caption("🚧 开发中...")

elif st.session_state.stage in ["error_analysis", "companion"]:
    st.title("🚧 功能正在开发中")
    st.info("请先使用「知识诊断」模块体验完整闭环。")

elif st.session_state.stage == "diagnostic":
    st.title("🎯 知识诊断")
    st.info(f"👋 **教练寄语**：欢迎回来。这是你的第 `{st.session_state.history_count}` 次认知扫描。大胆暴露问题，我在这里帮你兜底。")
    lid = st.text_input("你的学生代号", placeholder="例如：STU-01")
    with st.form("diag"):
        ans = {}
        for q in Q:
            st.subheader(f"题目 {q['item_id']}"); st.markdown(render_text(q["stem_latex"]))
            ans[q['item_id']] = st.radio("选择答案", options=list(q["options"].keys()), format_func=lambda x, o=q["options"]: f"{x}. {render_text(o[x])}", key=f"c_{q['item_id']}")
        sub = st.form_submit_button("提交全部答案")
    if sub and lid.strip():
        rows, now = [], datetime.now().isoformat(timespec="seconds")
        mastery = {q["node_uid"]: BKT_PARAMS["default"]["L0"] for q in Q}
        for q in Q:
            sel = ans[q['item_id']]; cor = 1 if sel == q["correct_option"] else 0
            mis = q["mis_codes"].get(sel, "") if cor == 0 else ""
            mastery[q["node_uid"]] = update_bkt(mastery[q["node_uid"]], cor, q["node_uid"])
            rows.append({"learner_id": lid, "item_id": q["item_id"], "node_uid": q["node_uid"], "selected_option": sel, "correct": cor, "misconception_code": mis, "event_time": now, "node_mastery_prob": mastery[q["node_uid"]]})
        invs = [{"node": n, "original_L": L, "mis_code": [r for r in rows if r["node_uid"] == n and r["correct"] == 0][0]["misconception_code"]} for n, L in mastery.items() if L < 0.6 and any(r["node_uid"] == n and r["correct"] == 0 for r in rows)]
        st.session_state.result_data = {"lid": lid, "rows": rows, "mastery": mastery, "invs": invs}
        st.session_state.stage = "result"; st.rerun()

elif st.session_state.stage == "result":
    d = st.session_state.result_data
    st.success("提交成功！以下为你当前的认知图谱：")
    st.graphviz_chart(render_graph(d["mastery"]), use_container_width=True)
    if d["invs"]:
        st.info(f"💡 **教练解读**：{get_coach_message('DIAGNOSTIC', 'ALL')}\n\n看到红色断点不要怕，这是大脑升级的前兆。")
        if st.button("🔧 开始修补与验证", type="primary"): st.session_state.stage = "intervention"; st.rerun()
    else:
        st.success("✅ 全盘掌握！"); st.button("生成最终报告", on_click=lambda: st.session_state.update(stage="final"))

elif st.session_state.stage == "intervention":
    st.title("🧠 认知重构与干预")
    for inv in st.session_state.result_data["invs"]:
        st.write(f"**节点: {inv['node']}**")
        conf = st.session_state.strategies.get(inv["mis_code"])
        st.warning(f"🔍 **解析**：{conf['content'] if conf else '请回顾步骤。'}")
        st.markdown(f"> *\"{get_coach_message('INTERVENTION', inv['node'])}\"*")
        st.write("---")
    if st.button("✅ 我已理解，进入验证"): st.session_state.stage = "verification"; st.rerun()

elif st.session_state.stage == "verification":
    st.title("📝 平行验证测试")
    vqs = []
    with st.form("verify"):
        ua = {}
        for i, inv in enumerate(st.session_state.result_data["invs"]):
            vq = gen_verify_q(inv["mis_code"]); vqs.append(vq)
            st.subheader(f"验证题 {i+1}")
            st.markdown(render_text(vq["stem"]))
            ua[i] = st.radio("选择答案", vq["options"], key=f"vq_{i}")[0]
        if st.form_submit_button("提交验证"):
            for i, vq in enumerate(vqs):
                inv = st.session_state.result_data["invs"][i]
                vq.update({"node": inv["node"], "original_L": inv["original_L"], "new_L": update_bkt(inv["original_L"], 1 if ua[i]==vq["correct"] else 0, inv["node"])})
            st.session_state.result_data["vqs"] = vqs
            st.session_state.stage = "final"; st.rerun()

elif st.session_state.stage == "final":
    d = st.session_state.result_data
    st.title("🎉 修补闭环完成")
    new_m = d["mastery"].copy()
    ctx = ""
    for vq in d.get("vqs", []):
        new_m[vq["node"]] = vq["new_L"]
        ctx += f"- {vq['node']}: {vq['original_L']} -> {vq['new_L']}\n"
    
    st.write("### 🗺️ 修补后的图谱")
    st.graphviz_chart(render_graph(new_m), use_container_width=True)
    
    st.success(f"🏆 **教练嘉奖**：{get_coach_message('VERIFICATION', 'ALL')}")
    st.write(f"这是你的第 **{st.session_state.history_count}** 次认知跃迁。面对困难，你展现了选择跨越的自由。")
    st.session_state.history_count += 1
    
    st.code(f"诊断专家指令：\n学生:{d['lid']}\n干预轨迹:\n{ctx}", language="markdown")
    st.download_button("下载作答记录", "data", file_name="data.csv")
    if st.button("结束体验，返回首页"): st.session_state.clear(); st.rerun()
