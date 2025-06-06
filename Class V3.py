import streamlit as st
import pandas as pd
import json
import requests
from bs4 import BeautifulSoup
from itertools import product
from collections import defaultdict
import copy

# --- Page Configuration ---
st.set_page_config(
    page_title="智慧排課助手 (Streamlit)",
    page_icon="🧠",
    layout="wide"
)

# --- Helper Dictionaries and Constants ---
DAY_MAP_DISPLAY = {"Mon": "一", "Tue": "二", "Wed": "三", "Thu": "四", "Fri": "五", "Sat": "六", "Sun": "日"}
DAY_MAP_HTML_INPUT = {"一": "Mon", "二": "Tue", "三": "Wed", "四": "Thu", "五": "Fri", "六": "Sat", "日": "Sun"}
DAY_OPTIONS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PRIORITY_OPTIONS = [1, 2, 3, 4, 5]

# --- Default Course Structure ---
def create_course_object(data={}):
    time_slots = data.get('time_slots', [])
    processed_slots = [(slot + ['', ''])[:3] for slot in time_slots]
    return {
        'name': data.get('name', ''), 'type': data.get('type', '選修'),
        'class_id': data.get('class_id', ''), 'credits': int(data.get('credits', 0)),
        'priority': int(data.get('priority', 3)), 'time_slots': processed_slots,
        'must_select': data.get('must_select', False),
        'temporarily_exclude': data.get('temporarily_exclude', False),
        'teacher': data.get('teacher', ''), 'notes': data.get('notes', '')
    }

# --- Session State Initialization ---
def initialize_session_state():
    defaults = {
        'courses': [], 'generated_schedules': [], 'analysis_results': {},
        'gemini_api_key': '', 'editing_course_index': -1,
        'course_draft': create_course_object() # Holds the course being edited/created
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# --- Gemini API Call Function ---
def call_gemini_api(prompt, api_key):
    if not api_key:
        st.error("請在側邊欄輸入您的 Gemini API 金鑰。")
        return None
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        response = requests.post(api_url, json=payload, headers={'Content-Type': 'application/json'})
        response.raise_for_status()
        result = response.json()
        return result["candidates"][0]["content"]["parts"][0]["text"]
    except requests.exceptions.RequestException as e:
        st.error(f"API 請求失敗: {e}")
        return None
    except (KeyError, IndexError) as e:
        st.error(f"解析 API 回應時出錯: {e}")
        return None

# --- Sidebar ---
def render_sidebar():
    with st.sidebar:
        st.header("⚙️ 操作選單")
        st.session_state.gemini_api_key = st.text_input("Google AI Gemini API Key", type="password", help="從 Google AI Studio 取得金鑰以啟用智慧功能。")
        st.subheader("載入/儲存課程資料")
        uploaded_file = st.file_uploader("載入課程資料 (JSON)", type="json")
        if uploaded_file:
            st.session_state.courses = [create_course_object(c) for c in json.load(uploaded_file)]
            st.toast(f"✅ 成功載入 {len(st.session_state.courses)} 門課程。", icon="🎉")
        if st.session_state.courses:
            st.download_button("儲存課程資料 (JSON)", json.dumps(st.session_state.courses, indent=4, ensure_ascii=False), "courses.json", "application/json", use_container_width=True)

# --- Tab: Add/Edit Course (REBUILT WITHOUT FORM) ---
def render_add_edit_tab():
    is_editing = st.session_state.editing_course_index > -1
    header_text = "編輯課程" if is_editing else "新增課程"
    st.subheader(header_text)

    draft = st.session_state.course_draft
    
    # --- Course Inputs ---
    draft['name'] = st.text_input("課程名稱*", value=draft['name'])
    col1, col2 = st.columns(2)
    with col1:
        draft['type'] = st.selectbox("類型*", ["必修", "選修"], index=["必修", "選修"].index(draft['type']))
        draft['credits'] = st.number_input("學分數*", min_value=0, value=draft['credits'])
    with col2:
        draft['class_id'] = st.text_input("班級 (年級+班別)*", value=draft['class_id'])
        draft['priority'] = st.selectbox("優先順序*", PRIORITY_OPTIONS, index=PRIORITY_OPTIONS.index(draft['priority']))
    draft['teacher'] = st.text_input("授課老師", value=draft['teacher'])
    
    # --- Notes with AI Helper ---
    note_header_col, note_button_col = st.columns([3, 1])
    note_header_col.markdown("**備註**")
    if note_button_col.button("✨ 產生建議備註"):
        if not draft['name']:
            st.warning("請先填寫課程名稱。")
        else:
            with st.spinner("🧠 正在呼叫 AI..."):
                prompt = f"針對一門大學課程「{draft['name']}」(老師: {draft['teacher'] or '未知'})，提供一些關於此課程可能的簡短備註(作業、風格、難度等)。以條列式呈現，總字數約50-100字。"
                suggested_notes = call_gemini_api(prompt, st.session_state.gemini_api_key)
                if suggested_notes:
                    current_notes = draft.get('notes', '')
                    draft['notes'] = (current_notes + "\n\n--- AI建議備註 ---\n" + suggested_notes).strip()
    
    draft['notes'] = st.text_area("備註欄位", value=draft['notes'], label_visibility="collapsed")

    # --- Time Slot Management ---
    with st.container(border=True):
        st.markdown("**上課時間**")
        slot_col1, slot_col2, slot_col3 = st.columns([2, 1, 1])
        day = slot_col1.selectbox("星期", DAY_OPTIONS, format_func=lambda d: DAY_MAP_DISPLAY[d])
        period = slot_col2.number_input("堂課", 1, 10)
        if slot_col3.button("添加時間", use_container_width=True):
            draft['time_slots'].append([day, period, ''])
        
        for i, (d, p, c) in enumerate(draft['time_slots']):
            ts_col1, ts_col2 = st.columns([4, 1])
            ts_col1.write(f"• {DAY_MAP_DISPLAY[d]} 第 {p} 堂" + (f" ({c})" if c else ""))
            if ts_col2.button("移除", key=f"rem_ts_{i}", use_container_width=True):
                draft['time_slots'].pop(i)
                st.rerun()

    # --- Final Controls ---
    st.markdown("---")
    col_check1, col_check2 = st.columns(2)
    draft['must_select'] = col_check1.checkbox("必選", value=draft['must_select'])
    draft['temporarily_exclude'] = col_check2.checkbox("暫時排除", value=draft['temporarily_exclude'])

    save_col, clear_col, _ = st.columns([1, 1, 3])
    if save_col.button("💾 儲存課程", type="primary", use_container_width=True):
        if not draft['name'] or not draft['class_id'] or not draft['time_slots']:
            st.error("請確保課程名稱、班級都已填寫，並已添加上課時間。")
        else:
            if is_editing:
                st.session_state.courses[st.session_state.editing_course_index] = copy.deepcopy(draft)
                st.toast(f"課程 '{draft['name']}' 已更新。", icon="🔄")
            else:
                st.session_state.courses.append(copy.deepcopy(draft))
                st.toast(f"課程 '{draft['name']}' 已新增。", icon="✅")
            st.session_state.course_draft = create_course_object()
            st.session_state.editing_course_index = -1
            st.rerun()

    if clear_col.button("🧹 清除表單", use_container_width=True):
        st.session_state.course_draft = create_course_object()
        st.session_state.editing_course_index = -1
        st.rerun()

# --- Tab: Course List ---
def render_course_list_tab():
    st.subheader("課程列表")
    if not st.session_state.courses:
        st.warning("目前沒有課程。請先新增或匯入。")
        return

    df = pd.DataFrame(st.session_state.courses)
    df.insert(0, "select", False)
    display_cols = {
        'select': '選取', 'name': '名稱', 'type': '類型', 'class_id': '班級', 'credits': '學分',
        'priority': '優先', 'teacher': '老師', 'time_slots': '時間/教室',
        'must_select': '必選', 'temporarily_exclude': '排除'
    }
    df['time_slots'] = df['time_slots'].apply(lambda slots: '; '.join([f"{DAY_MAP_DISPLAY.get(s[0], s[0])}{s[1]}{f'({s[2]})' if s[2] else ''}" for s in slots]))
    df_display = df[display_cols.keys()].rename(columns=display_cols)
    
    edited_df = st.data_editor(df_display, use_container_width=True, hide_index=True, disabled=['時間/教室'])

    edit_col, del_col, _ = st.columns([1,1,4])
    if edit_col.button("✍️ 編輯選取列", use_container_width=True):
        selected_indices = edited_df[edited_df['選取']].index.tolist()
        if len(selected_indices) != 1:
            st.warning("請只選取一門課程進行編輯。")
        else:
            index_to_edit = selected_indices[0]
            st.session_state.editing_course_index = index_to_edit
            st.session_state.course_draft = copy.deepcopy(st.session_state.courses[index_to_edit])
            st.query_params["tab"] = "add"
            st.rerun()

    if del_col.button("🗑️ 刪除選取列", use_container_width=True):
        selected_indices = edited_df[edited_df['選取']].index.tolist()
        if not selected_indices:
            st.warning("請先選取要刪除的課程。")
        else:
            for i in sorted(selected_indices, reverse=True):
                st.session_state.courses.pop(i)
            st.rerun()

# --- Placeholder for functions that are unchanged but needed for execution ---
def render_import_html_tab(): st.warning("HTML import logic is defined but omitted for brevity in this response.")
def render_generate_tab(): st.warning("Schedule generation logic is defined but omitted for brevity in this response.")

# --- MAIN APP ---
def main():
    st.title("🧠 智慧排課助手 (Streamlit 版)")
    initialize_session_state()
    render_sidebar()
    
    # Reset editing state when changing tabs
    def clear_editing_state():
        st.session_state.editing_course_index = -1
        st.session_state.course_draft = create_course_object()

    tab1, tab2, tab3, tab4 = st.tabs(["✍️ 新增/編輯課程", "📋 貼上HTML匯入", "📚 課程列表", "📊 生成排課方案"])
    
    with tab1:
        # No state clearing logic needed here as it's the primary editing tab
        render_add_edit_tab()
    with tab2:
        clear_editing_state()
        render_import_html_tab()
    with tab3:
        clear_editing_state()
        render_course_list_tab()
    with tab4:
        clear_editing_state()
        render_generate_tab()
        
if __name__ == "__main__":
    # For a fully runnable script, the placeholder functions (render_import_html_tab, 
    # render_generate_tab, and their dependencies) must be copied from the previous answers.
    main()
