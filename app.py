import csv
import io
from datetime import datetime
import re

import requests
import streamlit as st

# ==========================================
# BKT 参数预设 (这里填入你之前定好的先验值)
# 如果你所有节点的参数都一样，就用 default，有特殊节点就加在后面
# ==========================================


BKT_PARAMS = {
    "default": {"L0": 0.15, "T": 0.28, "G": 0.18, "S": 0.12},
    # 例如：如果你知道某个节点基础好，可以单独设置
    # "D-DER-0001": {"L0": 0.40, "T": 0.25, "G": 0.20, "S": 0.10},
}

def update_bkt_single_step(current_L, is_correct, node_uid):
    """
    单步更新 BKT 掌握概率
    current_L: 作答本题前的掌握率
    is_correct: 本题是否答对 (1/0)
    """
    params = BKT_PARAMS.get(node_uid, BKT_PARAMS["default"])
    T, G, S = params["T"], params["G"], params["S"]

    # 1. 贝叶斯后验更新
    if is_correct == 1:
        num = current_L * (1 - S)
        den = current_L * (1 - S) + (1 - current_L) * G
    else:
        num = current_L * S
        den = current_L * S + (1 - current_L) * (1 - G)
        
    posterior = num / den if den > 0 else current_L

    # 2. 学习转移
    new_L = posterior + (1 - posterior) * T
    return round(new_L, 3)

# ==========================================
# 1. 安全渲染函数（防止公式中的下划线被 Markdown 吞掉）
# ==========================================
def render_text_safely(text):
    if not text:
        return ""
    # 拆分出 $...$ 包裹的公式部分
    parts = re.split(r'(\$.*?\$)', text)
    result = ""
    for part in parts:
        if part.startswith("$") and part.endswith("$"):
            result += part  # 公式原样保留
        else:
            # 纯文本部分转义特殊字符
            part = part.replace("_", r"\_").replace("*", r"\*")
            result += part
    return result

# ==========================================
# 2. 页面配置
# ==========================================
st.set_page_config(page_title="数学诊断作答", layout="centered")
st.title("数学诊断作答")

# ==========================================
# 3. 从 WPS 拉取题库数据
# ==========================================
@st.cache_data(ttl=600)
def fetch_questions():
    webhook_url = st.secrets["WPS_WEBHOOK_URL"]
    token = st.secrets["WPS_SCRIPT_TOKEN"]

    headers = {
        "AirScript-Token": token,
        "Content-Type": "application/json",
    }
    payload = {"Context": {"argv": {}}}

    resp = requests.post(webhook_url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    questions = data.get("data", {}).get("result", {}).get("questions", [])
    if not questions:
        st.error("未获取到题目。请检查 AirScript 脚本是否成功返回。")
        st.stop()
        
    # 强制按 item_id 排序
    questions.sort(key=lambda x: x.get("item_id", ""))
    
    return questions

try:
    QUESTIONS = fetch_questions()
except Exception as e:
    st.error(f"读取题库失败：{e}")
    st.stop()

# ==========================================
# 4. 表单交互区
# ==========================================
learner_id = st.text_input("你的学生代号（请向老师确认）", placeholder="例如：STU-01")

with st.form("diagnostic_form", clear_on_submit=False):
    answers = {}
    for q in QUESTIONS:
        item_id = q['item_id']
        st.subheader(f"题目 {item_id}")
        
        # 渲染题干
        st.markdown(render_text_safely(q["stem_latex"]))
        
        # 渲染单选框
        choice = st.radio(
            "选择答案",
            options=list(q["options"].keys()),
            format_func=lambda x, opts=q["options"]: f"{x}. {render_text_safely(opts[x])}",
            key=f"choice_{item_id}",
        )
        answers[item_id] = choice
        
        # 记录推理备注
        answers[f"reason_{item_id}"] = st.text_area(
            "选这个答案时，你在哪一步犹豫了？（可选）",
            key=f"reason_{item_id}",
            height=60,
        )

    submitted = st.form_submit_button("提交全部答案")

# ==========================================
# 5. 提交处理与数据导出
# ==========================================
if submitted:
    if not learner_id.strip():
        st.error("请先填写学生代号。")
    else:
        rows = []
        now = datetime.now().isoformat(timespec="seconds")

        # 1. 初始化每个节点的当前掌握率字典 (默认为 L0)
        current_mastery = {}
        for q in QUESTIONS:
            node = q.get("node_uid", "")
            if node not in current_mastery:
                params = BKT_PARAMS.get(node, BKT_PARAMS["default"])
                current_mastery[node] = params["L0"]

        # 2. 遍历每一道题，边算边记录
        for q in QUESTIONS:
            item_id = q['item_id']
            node_uid = q.get("node_uid", "")
            selected = answers.get(item_id, "")
            correct = 1 if selected == q.get("correct_option") else 0
            
            # 提取错误码
            mis_codes = q.get("mis_codes", {})
            mis_code = mis_codes.get(selected, "")

            # 👇 核心：取出该节点上一题算出的 L，结合本题对错，算出当前 L
            L_before = current_mastery[node_uid]
            L_after = update_bkt_single_step(L_before, correct, node_uid)
            
            # 更新字典，供这个节点的下一题使用
            current_mastery[node_uid] = L_after

            rows.append({
                "learner_id": learner_id.strip(),
                "item_id": item_id,
                "node_uid": node_uid,
                "selected_option": selected,
                "correct": correct,
                "misconception_code": mis_code,
                "reasoning_note": answers.get(f"reason_{item_id}", ""),
                "event_time": now,
                # 👇 记录的是作答完这道题“当时”的掌握率
                "node_mastery_prob": L_after
            })

        st.success(f"提交成功：{len(rows)} 条作答记录。")
        


        st.success(f"提交成功：{len(rows)} 条作答记录。")

        # ====================================================
        # 自动化提取：生成给大模型的 Prompt 和 诊断摘要
        # ====================================================
        
        # 1. 页面直接展示“断崖节点”
        st.write("### 📊 各节点最终掌握率")
        summary_data = [{"节点": k, "最终掌握率": v} for k, v in current_mastery.items()]
        st.table(summary_data)

        # 2. 自动组装错题上下文和轨迹
        wrong_context = ""
        for idx, r in enumerate(rows):
            if r["correct"] == 0:
                # 找到这道题的掌握率轨迹（这里简化处理，直接展示错误时的状态）
                wrong_context += f"- 题目 [{r['item_id']}] (所属节点: {r['node_uid']})：学生选了 {r['selected_option']}，对应错误码：{r['misconception_code']}，此时该节点掌握率变为 {r['node_mastery_prob']}。\n"

        # 3. 生成一键复制的超级 Prompt
        st.write("---")
#        st.write("### 📋 一键生成诊断报告（复制下方内容去 ima 运行）")
        
#        prompt = f"""你是一名国际数学诊断专家。请根据以下学生的作答数据，严格按照四节结构（一句话判断、证据、维修工建议、下一步），写一份专业的诊断报告。
        prompt=f"""
【学生代号】{learner_id}

【数据摘要】
- 未达标节点及最终掌握率：{[{"节点": k, "掌握率": v} for k, v in current_mastery.items() if v < 0.6]}

【错题轨迹与错误码】
{wrong_context if wrong_context else "所有题目均作答正确，无明显错误轨迹。"}"""
        


#请输出完整的诊断报告：
#1. 一句话判断（指出该生最深层的认知缺口）
#2. 证据（引用错误码和掌握率的断崖变化）
#3. 维修工建议（分理解、技术、思维给出具体修补方案）
#4. 下一步（具体练习建议）"""
  
        st.code(prompt, language="markdown")
#      st.caption("👆 点击代码块右上角的复制按钮，粘贴到 ima 中即可生成最终报告。")

        # 4. 原有的 CSV 导出
        st.write("---")
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        
        st.download_button(
            "下载本次作答 CSV（用于备份/入库）",
            output.getvalue().encode("utf-8-sig"),
            file_name=f"answers_{learner_id.strip()}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )
