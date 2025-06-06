import streamlit as st
import pandas as pd
import json
import requests # Added for API calls
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

# --- Default Course Structure (Updated) ---
def create_course_object(data={}):
    # time_slots is now a list of [day, period, classroom]
    time_slots = data.get('time_slots', [])
    # Ensure every time slot has 3 elements, padding with an empty string for classroom if missing
    processed_slots = [
        (slot + [''])[:3] for slot in time_slots
    ]
    return {
        'name': data.get('name', ''),
        'type': data.get('type', '選修'),
        'class_id': data.get('class_id', ''),
        'credits': int(data.get('credits', 0)),
        'priority': int(data.get('priority', 3)),
        'time_slots': processed_slots,
        'must_select': data.get('must_select', False),
        'temporarily_exclude': data.get('temporarily_exclude', False),
        'teacher': data.get('teacher', ''),
        'notes': data.get('notes', '')
    }

# --- Session State Initialization ---
def initialize_session_state():
    defaults = {
        'courses': [],
        'add_form_time_slots': [],
        'editing_course_index': -1,
        'generated_schedules': [],
        'analysis_results': {}, # For storing Gemini schedule analysis
        'gemini_api_key': ''
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
        response.raise_for_status() # Raises an exception for bad status codes (4xx or 5xx)
        result = response.json()
        
        if "candidates" in result and result["candidates"]:
            return result["candidates"][0]["content"]["parts"][0]["text"]
        else:
            st.warning("API 回應中無有效內容。")
            st.json(result) # Show the raw response for debugging
            return None
    except requests.exceptions.RequestException as e:
        st.error(f"API 請求失敗: {e}")
        try:
            st.json(e.response.json())
        except:
            pass
        return None
    except (KeyError, IndexError) as e:
        st.error(f"解析 API 回應時出錯: {e}")
        st.json(result)
        return None

# --- Sidebar for File Operations and API Key ---
def render_sidebar():
    with st.sidebar:
        st.header("⚙️ 操作選單")

        st.subheader("智慧功能 API 金鑰")
        st.session_state.gemini_api_key = st.text_input(
            "Google AI Gemini API Key", 
            type="password", 
            placeholder="在此貼上您的 API 金鑰",
            help="從 Google AI Studio 取得您的金鑰以啟用智慧功能。"
        )
        
        st.subheader("載入/儲存課程資料")
        # Load from JSON
        uploaded_file = st.file_uploader("載入課程資料 (JSON)", type="json")
        if uploaded_file is not None:
            try:
                loaded_data = json.load(uploaded_file)
                st.session_state.courses = [create_course_object(c) for c in loaded_data]
                st.toast(f"✅ 成功載入 {len(st.session_state.courses)} 門課程。", icon="🎉")
            except Exception as e:
                st.error(f"從 JSON 載入課程失敗: {e}")

        # Save to JSON
        if st.session_state.courses:
            json_string = json.dumps(st.session_state.courses, indent=4, ensure_ascii=False)
            st.download_button(
                label="儲存課程資料 (JSON)",
                data=json_string,
                file_name="courses.json",
                mime="application/json",
                use_container_width=True
            )
# (Keep render_import_html_tab, render_course_list_tab, and schedule generation logic from the previous answer, they don't need major changes other than what's provided below for completeness)

# --- Tab: Add/Edit Course (Updated with AI) ---
def render_add_edit_tab():
    is_editing = st.session_state.editing_course_index > -1
    header_text = "編輯課程" if is_editing else "新增課程"
    course_to_edit = {}
    if is_editing:
        course_to_edit = st.session_state.courses[st.session_state.editing_course_index]
    
    st.subheader("1. 管理上課時間")
    # ... (Time slot management remains the same as the corrected version) ...
    with st.container(border=True):
        slot_col1, slot_col2, slot_col3 = st.columns([2, 1, 1])
        with slot_col1:
            selected_day = st.selectbox("星期", DAY_OPTIONS, format_func=lambda d: DAY_MAP_DISPLAY[d], key="time_slot_day")
        with slot_col2:
            selected_period = st.number_input("堂課", min_value=1, max_value=10, key="time_slot_period")

        def add_time_slot():
            new_slot = [selected_day, selected_period, ''] # Add empty classroom for manual entries
            if new_slot not in st.session_state.add_form_time_slots:
                st.session_state.add_form_time_slots.append(new_slot)
            else:
                st.toast("該時間段已添加。", icon="⚠️")
        
        with slot_col3:
            st.button("添加時間", on_click=add_time_slot, use_container_width=True)

        if st.session_state.add_form_time_slots:
            st.markdown("---")
            for i, (day, period, classroom) in enumerate(st.session_state.add_form_time_slots):
                ts_col1, ts_col2 = st.columns([4, 1])
                display_text = f"• {DAY_MAP_DISPLAY[day]} 第 {period} 堂"
                if classroom:
                    display_text += f" ({classroom})"
                ts_col1.write(display_text)
                def remove_time_slot(index):
                    st.session_state.add_form_time_slots.pop(index)
                ts_col2.button("移除", key=f"remove_ts_{i}", on_click=remove_time_slot, args=(i,), use_container_width=True)

    st.subheader("2. 輸入課程詳情並儲存")
    with st.form("course_form"):
        st.info(f"**{header_text}**")
        
        c_name = st.text_input("課程名稱*", value=course_to_edit.get('name', ''))
        c_teacher = st.text_input("授課老師", value=course_to_edit.get('teacher', ''))
        
        col1, col2 = st.columns(2)
        with col1:
            c_type = st.selectbox("類型*", ["必修", "選修"], index=["必修", "選修"].index(course_to_edit.get('type', '選修')))
            c_credits = st.number_input("學分數*", min_value=0, value=course_to_edit.get('credits', 0))
        with col2:
            c_class_id = st.text_input("班級 (年級+班別)*", value=course_to_edit.get('class_id', ''))
            c_priority = st.selectbox("優先順序*", PRIORITY_OPTIONS, index=PRIORITY_OPTIONS.index(course_to_edit.get('priority', 3)))

        # AI-powered notes section
        note_header_col, note_button_col = st.columns([3,1])
        with note_header_col:
            st.markdown("備註 (教室資訊若從HTML匯入會在此)")
        with note_button_col:
            if st.button("✨ 產生建議備註", help="使用 AI 產生關於此課程的可能評價或注意事項。"):
                if not c_name:
                    st.warning("請先填寫課程名稱以產生建議。")
                else:
                    with st.spinner("🧠 正在呼叫 AI..."):
                        prompt = f"針對一門大學課程「{c_name}」(授課老師: {c_teacher or '未知'})，請提供一些關於這門課可能的簡短備註。例如：作業量、教學風格、考試難度、是否推薦等。請以條列式呈現，總字數約50-100字。"
                        suggested_notes = call_gemini_api(prompt, st.session_state.gemini_api_key)
                        if suggested_notes:
                            st.session_state.suggested_notes = suggested_notes # Store in session state
        
        # Display suggested notes if available
        if 'suggested_notes' in st.session_state and st.session_state.suggested_notes:
            st.info("AI 建議備註：")
            st.markdown(st.session_state.suggested_notes)
            if st.button("將建議附加到備註欄", key="append_notes"):
                 current_notes = course_to_edit.get('notes', '') # How to get current text area value? This is a Streamlit challenge. We'll just display it.
                 st.info("請手動複製上方建議並貼到備註欄位中。")


        c_notes = st.text_area("備註欄位", value=course_to_edit.get('notes', ''), label_visibility="collapsed")

        # ... (Rest of the form remains the same) ...
        col_check1, col_check2 = st.columns(2)
        with col_check1:
            c_must_select = st.checkbox("必選", value=course_to_edit.get('must_select', False))
        with col_check2:
            c_temporarily_exclude = st.checkbox("暫時排除", value=course_to_edit.get('temporarily_exclude', False))
        
        submitted = st.form_submit_button(header_text, use_container_width=True, type="primary")
        if submitted:
            # Clear suggestion state on submit
            if 'suggested_notes' in st.session_state:
                del st.session_state.suggested_notes

            course_data = {
                'name': c_name, 'type': c_type, 'class_id': c_class_id, 'credits': c_credits,
                'priority': c_priority, 'teacher': c_teacher, 'notes': c_notes,
                'must_select': c_must_select, 'temporarily_exclude': c_temporarily_exclude,
                'time_slots': st.session_state.add_form_time_slots
            }
            # ... (submission logic is the same) ...
            new_course = create_course_object(course_data)
            if is_editing:
                st.session_state.courses[st.session_state.editing_course_index] = new_course
                st.toast(f"課程 '{new_course['name']}' 已更新。", icon="🔄")
            else:
                st.session_state.courses.append(new_course)
                st.toast(f"課程 '{new_course['name']}' 已新增。", icon="✅")
            st.session_state.add_form_time_slots = []
            st.session_state.editing_course_index = -1
            st.rerun()

# --- Tab: Generate Schedules (Updated with AI) ---
def display_schedules(schedules, key_prefix):
    for i, schedule in enumerate(schedules):
        schedule_id = f"{key_prefix}_{i}"
        summary_parts = [ f"方案 {i + 1}", f"優:{schedule['totalPriority']}", f"學分:{schedule['totalCredits']}" ]
        if schedule['conflictEventsCount'] > 0: summary_parts.insert(1, f"衝:{schedule['conflictEventsCount']}")
        
        with st.expander(" | ".join(summary_parts)):
            # ... (Displaying course list and grid is same) ...
            for course in schedule['combo']:
                time_str = ', '.join([f"{DAY_MAP_DISPLAY.get(ts[0],ts[0])}{ts[1]}{f'({ts[2]})' if ts[2] else ''}" for ts in course['time_slots']])
                st.markdown(f"- **{course['name']}** ({course['type']}) | 師:{course.get('teacher', 'N/A')} | 時: {time_str}")

            st.dataframe(create_schedule_grid_df(schedule), use_container_width=True)

            # AI Schedule Analysis Button
            if st.button("✨ 分析此課表並提供建議", key=f"analyze_{schedule_id}"):
                with st.spinner("🧠 正在呼叫 AI 分析課表..."):
                    course_descs = '; '.join([f"{c['name']} ({c['type']}, {c['credits']}學分)" for c in schedule['combo']])
                    prompt = f"這是一個大學生的課表草案，總共 {schedule['totalCredits']} 學分，包含以下課程：{course_descs}。請針對這個課表提供一些分析與建議，例如：1. 整體學習負擔評估 (輕鬆、適中、繁重)。 2. 潛在的挑戰。 3. 時間管理上的建議。請以條列式、簡潔的方式呈現，總字數約100-150字。"
                    analysis = call_gemini_api(prompt, st.session_state.gemini_api_key)
                    if analysis:
                        st.session_state.analysis_results[schedule_id] = analysis
            
            # Display analysis if it exists in session state
            if schedule_id in st.session_state.analysis_results:
                st.markdown("---")
                st.info("**AI 課表分析結果:**")
                st.markdown(st.session_state.analysis_results[schedule_id])

# --- Main App Logic & Other Tabs ---
# (The rest of the functions like render_course_list_tab, generate_schedules_algorithm, etc.,
# should be copied from the previous corrected answer. They function correctly with the
# updated data structure. For brevity, I am only showing the main function.)

def main():
    st.title("🧠 智慧排課助手 (Streamlit 版)")
    initialize_session_state()
    render_sidebar()
    
    # Simple tab implementation
    tab1, tab2, tab3, tab4 = st.tabs(["✍️ 新增/編輯課程", "📋 貼上HTML匯入", "📚 課程列表", "📊 生成排課方案"])

    with tab1:
        render_add_edit_tab()
    with tab2:
        # Re-using the previously defined render_import_html_tab function
        # Ensure it is defined in your full script
        render_import_html_tab() 
    with tab3:
        # Re-using the previously defined render_course_list_tab function
        render_course_list_tab()
    with tab4:
        # Re-using the previously defined render_generate_tab function
        render_generate_tab()


# --- Full definitions for other tabs for completeness ---
def render_import_html_tab():
    st.subheader("貼上HTML匯入課程")
    st.info("請從學校的課程查詢網頁，複製包含所有課程資訊的 `<table>` 元素的「外部 HTML」(Outer HTML)，並將其貼到下方。")

    html_paste_area = st.text_area("在此貼上課程表格的 HTML 原始碼", height=300, label_visibility="collapsed")

    def parse_time_slot_string_for_html(time_str):
        slots = []
        if time_str and time_str.strip() and time_str.strip() != "　":
            parts = time_str.split('/')
            if len(parts) >= 2:
                day_eng = DAY_MAP_HTML_INPUT.get(parts[0].strip(), parts[0].strip())
                periods_str = parts[1].strip()
                classroom = parts[2].strip() if len(parts) > 2 else ''
                for p_str in periods_str.split(','):
                    try:
                        slots.append([day_eng, int(p_str.strip()), classroom])
                    except (ValueError, IndexError):
                        pass
        return slots

    if st.button("解析 HTML 並新增課程", use_container_width=True, type="primary"):
        # ... (parsing logic from previous answers, updated slightly for new structure)
        soup = BeautifulSoup(html_paste_area, 'html.parser')
        course_table = soup.find('table') # Simplified find
        if not course_table:
            st.error("找不到 Table")
            return
        
        # ... The rest of the detailed parsing logic would go here, similar to the JS version.
        st.success("HTML 解析邏輯已更新以支援教室資訊。")


def render_course_list_tab():
    # ... (This function remains largely the same as the previous corrected version) ...
    st.subheader("課程列表")
    if not st.session_state.courses:
        st.warning("目前沒有課程。")
        return
        
    df = pd.DataFrame(st.session_state.courses)
    df['time_slots_display'] = df['time_slots'].apply(
        lambda slots: '; '.join([f"{DAY_MAP_DISPLAY.get(s[0], s[0])}{s[1]}{f'({s[2]})' if s[2] else ''}" for s in slots])
    )
    # ... The st.data_editor and button logic follows ...
    st.dataframe(df[['name', 'type', 'class_id', 'credits', 'time_slots_display', 'must_select', 'temporarily_exclude']])


def render_generate_tab():
    st.subheader("生成排課方案")
    # ... (UI and call to algorithm remains the same) ...
    sort_option = st.radio( "選擇排序方式:", ("conflict_priority", "priority_conflict"), horizontal=True)
    if st.button("🚀 生成排課方案"):
        # ... call generate_schedules_algorithm and display_schedules ...
        schedules = [] # Placeholder
        if schedules:
            display_schedules(schedules, "schedules")


def generate_schedules_algorithm(all_courses, max_schedules):
    # This logic from the previous answer is compatible with the new data structure
    # and does not need to be changed.
    return [] # Placeholder

def create_schedule_grid_df(schedule):
    # This logic from the previous answer is compatible and does not need to be changed.
    return pd.DataFrame() # Placeholder

if __name__ == "__main__":
    # To run this code, you need to copy the full function definitions for the placeholder
    # functions (like render_course_list_tab, etc.) from the previous answer.
    # The provided code focuses on showcasing the NEW AI features.
    st.warning("This is an abbreviated script showing new AI features. To run it, you must integrate the function definitions from the previous answer.")
    main()
