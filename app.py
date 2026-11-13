import csv
import io
from datetime import datetime
import re

import requests
import streamlit as st

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
        
        for q in QUESTIONS:
            item_id = q['item_id']
            # 获取学生答案
            selected = answers.get(item_id, "")
            # 自动判分
            correct = 1 if selected == q.get("correct_option") else 0
            
            # 安全提取错误码（兼容字符串和字典类型）
            mapping = q.get("distractor_mapping", "")
            mis_code = ""
            if isinstance(mapping, dict):
                mis_code = mapping.get(selected, "")
            
            rows.append({
                "learner_id": learner_id.strip(),
                "item_id": item_id,
                "node_uid": q.get("node_uid", ""),
                "selected_option": selected,
                "correct": correct,
                "misconception_code": mis_code,
                "reasoning_note": answers.get(f"reason_{item_id}", ""),
                "event_time": now,
            })

        st.success(f"提交成功：{len(rows)} 条作答记录。")
        st.dataframe(rows, use_container_width=True)

        # 使用内置库生成 CSV
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        
        # 提供下载按钮
        st.download_button(
            "下载本次作答 CSV（用于导入 WPS）",
            output.getvalue().encode("utf-8-sig"),
            file_name=f"answers_{learner_id.strip()}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )
