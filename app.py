import csv
import io
from datetime import datetime

import requests
import streamlit as st

st.set_page_config(page_title="数学诊断作答", layout="centered")
st.title("数学诊断作答")


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

    # 如果路径不对，先打印完整响应看结构
    questions = data.get("data", {}).get("result", {}).get("questions", [])
    if not questions:
        st.error("未获取到题目。检查 AirScript 是否 return { questions: [...] }，或打印完整响应确认路径。")
        st.json(data)  # 调试用，确认后删掉
        st.stop()
    questions.sort(key=lambda x: x.get("item_id", ""))
    return questions


try:
    QUESTIONS = fetch_questions()
except Exception as e:
    st.error(f"读取题库失败：{e}")
    st.stop()

learner_id = st.text_input("你的学生代号（请向老师确认）", placeholder="例如：STU-01")

with st.form("diagnostic_form", clear_on_submit=False):
    answers = {}
    for q in QUESTIONS:
        st.subheader(f"题目 {q['item_id']}")
        st.markdown(q["stem_latex"])

        choice = st.radio(
            "选择答案",
            options=list(q["options"].keys()),
            format_func=lambda x, opts=q["options"]: f"{x}. {opts[x]}",
            key=f"choice_{q['item_id']}",
        )
        answers[q["item_id"]] = choice
        answers[f"reason_{q['item_id']}"] = st.text_area(
            "选这个答案时，你在哪一步犹豫了？（可选）",
            key=f"reason_{q['item_id']}",
            height=60,
        )

    submitted = st.form_submit_button("提交全部答案")

if submitted:
    if not learner_id.strip():
        st.error("请先填写学生代号。")
    else:
        rows = []
        now = datetime.now().isoformat(timespec="seconds")
        for q in QUESTIONS:
            selected = answers[q["item_id"]]
            correct = 1 if selected == q["correct_option"] else 0
            rows.append({
                "learner_id": learner_id.strip(),
                "item_id": q["item_id"],
                "node_uid": q["node_uid"],
                "selected_option": selected,
                "correct": correct,
                "misconception_code": q.get("distractor_mapping", {}).get(selected, ""),
                "reasoning_note": answers[f"reason_{q['item_id']}"],
                "event_time": now,
            })

        st.success(f"提交成功：{len(rows)} 条作答记录。")
        st.dataframe(rows, use_container_width=True)

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        st.download_button(
            "下载本次作答 CSV（用于导入 WPS）",
            output.getvalue().encode("utf-8-sig"),
            file_name=f"answers_{learner_id.strip()}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )