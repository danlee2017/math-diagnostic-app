import csv, io, re, random, requests
from datetime import datetime
import streamlit as st
import graphviz
from supabase import create_client, Client
import streamlit as st

@st.cache_resource
def init_supabase() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_supabase()

# ==========================================
# 0. 页面配置与全局状态机
# ==========================================
st.set_page_config(page_title="私人数学认知系统", layout="centered")

if "stage" not in st.session_state: st.session_state.stage = "home"
if "result_data" not in st.session_state: st.session_state.result_data = {}
if "strategies" not in st.session_state: st.session_state.strategies = {}
if "graph_data" not in st.session_state: st.session_state.graph_data = []
if "encouragements" not in st.session_state: st.session_state.encouragements = []
if "history_count" not in st.session_state: st.session_state.history_count = 1

# ==========================================
# 1. 核心算法与扩展接口预留
# ==========================================
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

def get_psychological_anchor(trigger_type, target_node="", dimension=""):
    encs = [e for e in st.session_state.encouragements if e["trigger_type"] == trigger_type and (e["target_id"] == target_node or e["target_id"] == "ALL") and (dimension == "" or e["psych_dimension"] == dimension)]
    return random.choice(encs)["message"] if encs else "每一次挑战，都是你重塑大脑回路的契机。"

def load_student_history(learner_id):
    try:
        resp = supabase.table('student_mastery').select('node_uid', 'mastery_prob').eq('learner_id', learner_id).execute()
        return {row['node_uid']: row['mastery_prob'] for row in resp.data}
    except Exception as e:
        st.warning(f"历史记录读取失败，将按新生处理: {e}")
        return {}

def save_student_history(learner_id, mastery_dict):
    try:
        data = [{"learner_id": learner_id, "node_uid": n, "mastery_prob": p} for n, p in mastery_dict.items()]
        supabase.table('student_mastery').upsert(data).execute()
    except Exception as e:
        st.error(f"学情保存失败: {e}")


def adaptive_question_selection(filtered_questions):
    """【扩展接口】自适应题库：目前每个节点盲抽1题，未来可做动态难度"""
    random.shuffle(filtered_questions)
    sampled, seen = [], set()
    for q in filtered_questions:
        if q["node_uid"] not in seen:
            sampled.append(q); seen.add(q["node_uid"])
    return sampled

# ==========================================
# 2. 星河图谱渲染引擎（支持跨学科与星云模块）
# ==========================================
def render_graph(mastery_data):
    dot = graphviz.Digraph()
    dot.attr(rankdir='LR')
    dot.attr('node', shape='box', style='rounded,filled', fontname='Microsoft YaHei')
    dot.attr('graph', overlap='false', splines='true') # 优化排布
    
    # 1. 收集已测试的知识点集合
    tested_uids = set(mastery_data.keys())
    
    # 2. 找出与这些点相关的邻接节点（包括测过的、没测过的，以及大模块）
    nearby_nodes = set(tested_uids)
    for n in st.session_state.graph_data:
        # 如果这个节点是测过的，把它的前置加进来
        if n["node_uid"] in tested_uids and n.get("prereq_uids"):
            for p in [x.strip() for x in n["prereq_uids"].split(",") if x.strip()]:
                nearby_nodes.add(p)
        # 如果这个节点的前置里有测过的，把它也加进来
        if n.get("prereq_uids"):
            for p in [x.strip() for x in n["prereq_uids"].split(",") if x.strip()]:
                if p in tested_uids:
                    nearby_nodes.add(n["node_uid"])
    
    # 3. 找出所有属于大模块的节点（纯字母没数字的）
    all_modules = set()
    for n in st.session_state.graph_data:
        if n.get("module"): all_modules.add(n["module"])
    
    # 4. 先画所有的宏观大模块（星云）
    for mod in all_modules:
        # 判断这个模块下有没有测过的具体节点。如果有，星云点亮一点；没有，就灰色
        has_tested = any(q["node_uid"] in tested_uids and q.get("module") == mod for q in st.session_state.graph_data)
        bg_color = "#fff3e0" if has_tested else "#f0f0f0"
        fc_color = "#ff9800" if has_tested else "#999999"
        dot.node(mod, f"🌌 {mod}\n(模块星云)", shape="folder", style="dashed,filled", fillcolor=bg_color, fontcolor=fc_color, penwidth="2")

    # 5. 画相关的微观节点（彩色或灰色小点）
    for n in st.session_state.graph_data:
        uid = n["node_uid"]
        if uid not in nearby_nodes: 
            continue # 不在附近，直接不画，保持干净！
            
        # 如果本身是纯字母编码（作为星云已经画过了），跳过
        if not re.search(r'\d', uid): continue
            
        name = n["node_name"]
        if uid in tested_uids:
            prob = mastery_data[uid]
            color, fc = ("#4CAF50", "white") if prob>=0.8 else (("#FFC107", "black") if prob>=0.6 else ("#F44336", "white"))
            dot.node(uid, f"{name}\n{int(prob*100)}%", fillcolor=color, fontcolor=fc)
        else:
            # 未测试但在附近的点，用浅灰色，表示“待探索”
            dot.node(uid, f"{name}\n(待探索)", fillcolor="#e0e0e0", fontcolor="#666", style="dashed,filled")
            
        # 画连线
        if n.get("prereq_uids"):
            for p in [x.strip() for x in n["prereq_uids"].split(",") if x.strip()]:
                # 只有当两端都在图里时才连线
                if p in nearby_nodes or p in all_modules:
                    dot.edge(p, uid)
                    
    return dot
# ==========================================
# 3. 动态验证题生成器
# ==========================================
def gen_verify_q(mis_code):
    conf = st.session_state.strategies.get(mis_code)
    # 如果没配置策略，或者模板字段为空，直接返回 None 跳过
    if not conf or not conf.get("stem_template") or not conf.get("correct_tpl"):
        return None
    
    vars = {}
    var_range_str = conf.get("var_range", "")
    if var_range_str:
        var_range_str = var_range_str.replace("，", ",").replace("–", "-").replace("—", "-")
        for pair in var_range_str.split(","):
            if ":" in pair:
                try:
                    v, r = pair.split(":")
                    mn, mx = map(int, r.strip().split("-"))
                    vars[v.strip()] = random.randint(mn, mx)
                except Exception:
                    continue
                    
    def r_tpl(t): 
        if not t: return None
        try: return t.format(**vars)
        except: return t
            
    correct = r_tpl(conf.get("correct_tpl",""))
    wrong1 = r_tpl(conf.get("wrong1_tpl",""))
    wrong2 = r_tpl(conf.get("wrong2_tpl",""))
    wrong3 = r_tpl(conf.get("wrong3_tpl","")) # 🌟 依赖你在 WPS 里补充这第四个选项
    
    # 🌟 严格要求：必须 4 个选项齐备才能生成题目
    opts = [correct, wrong1, wrong2, wrong3]
    if any(o is None or o == "" for o in opts):
        return None # 任何一项缺失，直接作废
        
    random.shuffle(opts)
    
    return {
        "stem": r_tpl(conf.get("stem_template","")), 
        "options": [f"{'ABCD'[i]}. {o}" for i,o in enumerate(opts)], 
        "correct": "ABCD"[opts.index(correct)], 
        "check_point": f"验证 {mis_code}。"
    }

# ==========================================
# 4. 数据拉取（包含详细排错）
# ==========================================
@st.cache_data(ttl=600)
def fetch_data():
    webhook_url = st.secrets["WPS_WEBHOOK_URL"]
    token = st.secrets["WPS_SCRIPT_TOKEN"]
    headers = {"AirScript-Token": token, "Content-Type": "application/json"}
    payload = {"Context": {"argv": {}}}
    
    resp = requests.post(webhook_url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    
    if data.get("error"):
        st.error(f"AirScript 脚本执行错误：{data['error']}")
        st.stop()
        
    result = data.get("data", {}).get("result", {})
    if not result:
        st.error("WPS 返回的数据为空，请检查 AirScript 是否成功 return 了数据。")
        st.stop()
        
    return (
        result.get("questions", []), result.get("strategies", {}), 
        result.get("graph_data", []), result.get("encouragements", [])
    )

try:
    Q, S, G, E = fetch_data()
    if not Q:
        st.warning("题库为空，请在 WPS 的 question_bank 表中录入数据。")
        
    # 🌟 核心：建立 node_uid 到 (subject, module) 的映射字典
    node_meta_map = {}
    for g_node in G:
        node_meta_map[g_node["node_uid"]] = {
            "subject": g_node.get("subject", "未知学科"),
            "module": g_node.get("module", "未知模块")
        }
        
    # 🌟 将图谱里的学科和模块，动态注入到每一道题里
    for q in Q:
        meta = node_meta_map.get(q["node_uid"])
        if meta:
            q["subject"] = meta["subject"]
            q["module"] = meta["module"]
        else:
            q["subject"] = "未关联图谱"
            q["module"] = "未关联图谱"
            
    st.session_state.update({"strategies": S, "graph_data": G, "encouragements": E})
except requests.exceptions.RequestException as e:
    st.error(f"网络请求失败，请检查 Secrets 中的 Webhook 和 Token 配置。\n详细错误：{e}")
    st.stop()
except Exception as e:
    st.error(f"数据解析失败：{e}")
    st.stop()

# ==========================================
# 5. 占位页面渲染
# ==========================================
def render_placeholder_pages(page_type):
    if page_type == "error_analysis":
        st.title("📝 AI 错题全息诊断（即将上线）")
        st.info("📸 **拍照上传，秒级溯源**\n\n上传你做错的题目，AI 将自动提取题干，精准定位它在你认知图谱中的节点，并指出是哪个前置知识断裂导致了这道题的错误。")
        st.write("---")
        st.write("### 🌌 你的当前认知坐标")
        st.graphviz_chart(render_graph({}), width='stretch')
        st.caption("👆 未来的错题会精准标记在这个星云图中。")
        
    elif page_type == "companion":
        st.title("🧑‍🏫 AI 认知伴学对话（即将上线）")
        st.info("🗣️ **多维对话，暴露真实盲区**\n\n在这里，你可以向 AI 讲述今天学的概念、技术或解题思路。AI 会抓取你的潜意识偏航点，动态更新你的长期认知档案。")
        st.write("---")
        st.write("### 🌌 知识星云定位")
        st.markdown("你现在所在的【微积分】模块，只是浩瀚数学宇宙的一角：")
        st.graphviz_chart(render_graph({}), width='stretch')
        st.text_area("试想一下，未来你可以这样提问：", "我今天学了链式法则，它到底是用在哪里的？感觉做题总是漏乘。", disabled=True)
        st.caption("👆 AI 回复：链式法则（技术层）是导数星云的核心骨架。你漏乘内层导数，是因为你的『结构识别』概念还没有自动化。我们来看看它在地图上的位置...")
    
    if st.button("返回主界面"):
        st.session_state.stage = "home"
        st.rerun()

# ==========================================
# 6. 导航与状态机
# ==========================================
if st.session_state.stage == "home":
    # 顶部大标题与核心定位
    st.title("⚡️ 欢迎来到私人数学认知系统")
    st.markdown("""
    > *“在这里，数学不再是枯燥的题海，而是你大脑认知升级的通关游戏。”*
    """)
    
    # 🌟 注入灵魂的介绍（使用 st.success 或 st.info 让它高亮显示）
    st.info("""
    **🧑‍🏫 你的专属私人数学认知教练已上线**
    
    我们不仅用**溯源的方法**帮你快速定位并修补知识缺口，取得考试胜利；
    我们更是你的**私人认知教练**，会用科学的数据，记录你每一步的认知升级，见证你智慧光芒散发的历史。
    
    *每一次红点的消灭，都是大脑神经回路的重塑。*
    """)
    
    st.write("---")
    st.write("### 今天你想进行哪项训练？")
    
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("🎯 知识诊断", width='stretch', type="primary"): 
            st.session_state.stage = "diagnostic"
            st.rerun()
        st.caption("扫描知识盲区，生成专属学情星图。")
        
    with c2:
        if st.button("📝 错题分析", width='stretch'): 
            st.session_state.stage = "error_analysis"
            st.rerun()
        st.caption("拍照上传，秒级溯源前置缺口。")
        
    with c3:
        if st.button("🧑‍🏫 伴学对话", width='stretch'): 
            st.session_state.stage = "companion"
            st.rerun()
        st.caption("多维对话，动态记录长期认知。")

elif st.session_state.stage in ["error_analysis", "companion"]:
    render_placeholder_pages(st.session_state.stage)

elif st.session_state.stage == "diagnostic":
    st.title("🎯 知识诊断")
    
    # 初始化一个占位符，用来显示动态欢迎语
    welcome_placeholder = st.empty()

    lid = st.text_input("你的学生代号", placeholder="例如：STU-01")

    if not lid.strip():
        welcome_placeholder.info("👋 **教练寄语**：请输入你的代号，调取你的专属认知档案。")
    else:
        history_mastery = load_student_history(lid)
        if history_mastery:
            welcome_placeholder.success(f"👋 **欢迎回来，{lid}！**\n\n我看到你上次留下了 {len(history_mastery)} 个认知锚点。上一次的红色断点，今天准备点亮它了吗？")
        else:
            welcome_placeholder.info(f"👋 **欢迎来到微积分加速站，{lid}！**\n\n这是你的第 1 次认知扫描。大胆暴露问题，我帮你兜底。")

    
    # 👇 新增：实时查询历史数据并展示初始掌握率
    if lid.strip():
        with st.spinner("正在调取认知档案..."):
            history_mastery = load_student_history(lid)
            
        if history_mastery:
            st.success(f"📊 已识别档案！系统已为你加载 {len(history_mastery)} 个知识点的历史掌握率。")
            with st.expander("👀 查看你的初始知识底子"):
                for node, prob in history_mastery.items():
                    # 用进度条直观显示
                    st.write(f"知识点：`{node}`")
                    st.progress(prob, text=f"当前掌握率：{int(prob*100)}%")
        else:
            st.info("🆕 未找到历史记录，这将是你的第一次认知基线扫描。")
    
    # 过滤异常数据
    valid_qs = [q for q in Q if q.get("subject") not in ["未关联图谱", ""] and len(q.get("subject")) < 20]
    if not valid_qs:
        st.error("数据异常：所有题目均未在图谱库中找到对应的 node_uid。")
        st.stop()
        
    subjects = sorted(list(set([q["subject"] for q in valid_qs])))
    subject_choice = st.selectbox("请选择学科：", subjects)
    
    modules = sorted(list(set([q["module"] for q in valid_qs if q["subject"] == subject_choice and len(q["module"]) < 20])))
    module_choice = st.selectbox("请选择知识模块：", modules)
    
    filtered_questions = [q for q in valid_qs if q["subject"] == subject_choice and q["module"] == module_choice]
    
    # 抽样
    sampled_questions = adaptive_question_selection(filtered_questions)
    
    # 将抽样后的题目存入 session_state，保证页面刷新时题目不会随机变来变去
    if "current_sampled_qs" not in st.session_state or st.session_state.get("current_mod") != module_choice:
        st.session_state.current_sampled_qs = sampled_questions
        st.session_state.current_mod = module_choice
        
    # 使用刚才存在 session_state 里的题目
    final_qs = st.session_state.current_sampled_qs
    st.write(f"📊 本次诊断将覆盖 **{len(final_qs)}** 个知识点。")

    with st.form("diag_form"):
        ans = {}
        for q in final_qs:
            st.subheader(f"题目 {q['item_id']}")
            st.markdown(render_text(q["stem_latex"]))
            ans[q['item_id']] = st.radio(
                "选择答案", 
                options=list(q["options"].keys()), 
                format_func=lambda x, o=q["options"]: f"{x}. {render_text(o[x])}", 
                key=f"c_{q['item_id']}"
            )
        sub = st.form_submit_button("提交全部答案", type="primary", width='stretch')
        
    # 🌟 核心修复：提交逻辑
    if sub:
        if not lid.strip():
            st.error("请先填写你的学生代号！")
        else:
            rows, now = [], datetime.now().isoformat(timespec="seconds")
            history_mastery = load_student_history(lid)
            
            # 初始化掌握率
            mastery = {q["node_uid"]: history_mastery.get(q["node_uid"], BKT_PARAMS["default"]["L0"]) for q in final_qs}
            
            # 计算 BKT
            for q in final_qs:
                sel = ans[q['item_id']]; cor = 1 if sel == q["correct_option"] else 0
                mis = q["mis_codes"].get(sel, "") if cor == 0 else ""
                mastery[q["node_uid"]] = update_bkt(mastery[q["node_uid"]], cor, q["node_uid"])
                rows.append({"learner_id": lid, "item_id": q["item_id"], "node_uid": q["node_uid"], "selected_option": sel, "correct": cor, "misconception_code": mis, "event_time": now, "node_mastery_prob": mastery[q["node_uid"]]})
            
            # 找出断点
            invs = [{"node": n, "original_L": L, "mis_code": [r for r in rows if r["node_uid"] == n and r["correct"] == 0][0]["misconception_code"]} for n, L in mastery.items() if L < 0.6 and any(r["node_uid"] == n and r["correct"] == 0 for r in rows)]
            
            # 溯源找题
            prereq_questions = []
            for inv in invs:
                graph_info = next((g for g in st.session_state.graph_data if g["node_uid"] == inv["node"]), None)
                if graph_info and graph_info.get("prereq_uids"):
                    for p in [x.strip() for x in graph_info["prereq_uids"].split(",") if x.strip()]:
                        p_qs = [q for q in Q if q["node_uid"] == p]
                        if p_qs: prereq_questions.append(p_qs[0]); break
            
            # 把结果保存到 session_state
            st.session_state.result_data = {
                "lid": lid, "rows": rows, "mastery": mastery, 
                "invs": invs, "prereq_questions": prereq_questions
            }
            
            save_student_history(lid, mastery)
            # 清除当前抽题缓存，防止下次进来还是上次的题
            del st.session_state.current_sampled_qs
            del st.session_state.current_mod
            
            
            # 路由跳转
            if prereq_questions: 
                st.session_state.stage = "prereq_check"
            else: 
                st.session_state.stage = "result"
                
            # 🌟 强制页面刷新，直接跳出循环！
            st.rerun()

elif st.session_state.stage == "prereq_check":
    st.title("🔍 认知断层溯源")
    st.warning("教练发现你的高维知识出现了断点。为了精准定位，请快速确认一下底层的这几个前置概念：")
    
    prereq_qs = st.session_state.result_data["prereq_questions"]
    with st.form("prereq_form"):
        ans = {}
        for q in prereq_qs:
            st.subheader(f"溯源确认 (底层节点: {q['node_uid']})")
            st.markdown(render_text(q["stem_latex"]))
            ans[q['item_id']] = st.radio("选择答案", options=list(q["options"].keys()), format_func=lambda x, o=q["options"]: f"{x}. {render_text(o[x])}", key=f"pq_{q['item_id']}")
        submitted = st.form_submit_button("提交溯源结果")
        
    if submitted:
        prereq_status = []
        for q in prereq_qs:
            is_correct = (ans[q['item_id']] == q["correct_option"])
            prereq_status.append({"node_uid": q["node_uid"], "passed": is_correct})
        
        st.session_state.result_data["prereq_status"] = prereq_status
        st.session_state.stage = "result"; st.rerun()

elif st.session_state.stage == "result":
    d = st.session_state.result_data
    st.success("诊断完成！以下为你当前的局部认知图谱：")
    st.graphviz_chart(render_graph(d["mastery"]), width='stretch')
    
    prereq_status = d.get("prereq_status", [])
    if prereq_status:
        st.write("### 🩺 病理学诊断结论")
        for p in prereq_status:
            if not p["passed"]:
                st.error(f"❌ **根因找到**：你的前置节点【{p['node_uid']}】未达标。这才是导致学习卡壳的真正元凶！")
            else:
                st.success(f"✅ **排除干扰**：前置节点【{p['node_uid']}】很扎实。问题纯粹出在新概念的理解上，不是基础差！")
    
    if d["invs"]:
        st.info(f"💡 **教练解读**：{get_psychological_anchor('DIAGNOSTIC', 'ALL')}")
        if st.button("🔧 开始修补与验证", type="primary"): st.session_state.stage = "intervention"; st.rerun()
    else:
        st.success("✅ 全盘掌握！"); st.button("生成最终报告", on_click=lambda: st.session_state.update(stage="final"))

elif st.session_state.stage == "intervention":
    st.title("🧠 认知重构与干预")
    for inv in st.session_state.result_data["invs"]:
        st.write(f"**节点: {inv['node']}**")
        conf = st.session_state.strategies.get(inv["mis_code"])
        st.warning(f"🔍 **解析**：{conf['content'] if conf else '请回顾步骤。'}")
        st.markdown(f"> *\"{get_psychological_anchor('INTERVENTION', inv['node'])}\"*")
        st.write("---")
    if st.button("✅ 我已理解，进入验证"): st.session_state.stage = "verification"; st.rerun()

elif st.session_state.stage == "verification":
    st.title("📝 平行验证测试")
    
    # 过滤掉无法生成模板的无效干预
    valid_vqs = []
    for inv in st.session_state.result_data["invs"]:
        vq = gen_verify_q(inv["mis_code"])
        if vq is not None:
            vq["node"] = inv["node"]
            vq["original_L"] = inv["original_L"]
            valid_vqs.append(vq)
            
    # 如果全都没有模板，直接跳回
    if not valid_vqs:
        st.warning("⚠️ 系统检测到该错误模式的变式题库尚未建全，跳过平行验证环节，直接为你生成干预建议。")
        if st.button("查看诊断报告"):
            st.session_state.stage = "final"
            st.rerun()
        st.stop()
        
    st.info("请完成以下专属变式题，证明你已经跨过了刚才的坑。")
    
    with st.form("verify"):
        ua = {}
        for i, vq in enumerate(valid_vqs):
            st.subheader(f"验证题 {i+1}")
            st.markdown(render_text(vq["stem"]))
            ua[i] = st.radio("选择答案", vq["options"], key=f"vq_{i}")[0]
            
        if st.form_submit_button("提交验证"):
            for i, vq in enumerate(valid_vqs):
                # 计算并存入新的掌握率
                vq["new_L"] = update_bkt(vq["original_L"], 1 if ua[i]==vq["correct"] else 0, vq["node"])
            
            st.session_state.result_data["vqs"] = valid_vqs
            st.session_state.stage = "final"
            st.rerun()

elif st.session_state.stage == "final":
    d = st.session_state.result_data
    st.title("🎉 修补闭环完成")
    new_m = d["mastery"].copy()
    ctx = ""
    for vq in d.get("vqs", []):
        new_m[vq["node"]] = vq["new_L"]
        ctx += f"- {vq['node']}: {vq['original_L']} -> {vq['new_L']}\n"
    
    st.write("### 🗺️ 修补后的图谱")
    st.graphviz_chart(render_graph(new_m), width='stretch')
    
    st.success(f"🏆 **教练嘉奖**：{get_psychological_anchor('VERIFICATION', 'ALL')}")
    st.write(f"这是你的第 **{st.session_state.history_count}** 次认知跃迁。")
    st.session_state.history_count += 1
    
    report_prompt = f"【学生】:{d['lid']}\n【初始断点】:{[i['node'] for i in d['invs']]}\n"
    if d.get("prereq_status"):
        for p in d["prereq_status"]:
            report_prompt += f"【溯源诊断】: 前置节点 {p['node_uid']} 是否达标：{p['passed']}\n"
    report_prompt += f"【干预验证轨迹】:\n{ctx}"
    
    st.write("### 📋 复制以下内容去 ima 生成最终报告")
    st.code(report_prompt, language="markdown")
    
    if st.button("结束体验，返回首页"): 
        st.session_state.stage = "home"; st.session_state.result_data = {}; st.rerun()
