import streamlit as st
import pandas as pd
import json
from bs4 import BeautifulSoup
import itertools
import google.generativeai as genai
from io import StringIO

# --- Page Configuration and Utility Functions ---

st.set_page_config(page_title="互動式排課助手", layout="wide")

def show_message(message, type='info', duration=3):
    """A consistent way to show messages, using st.toast for popups."""
    if type == 'success':
        st.toast(f"✅ {message}", icon="✅")
    elif type == 'warning':
        st.toast(f"⚠️ {message}", icon="⚠️")
    elif type == 'error':
        st.toast(f"❌ {message}", icon="❌")
    else: # info
        st.toast(f"ℹ️ {message}", icon="ℹ️")

DAY_MAP_DISPLAY = {"Mon": "一", "Tue": "二", "Wed": "三", "Thu": "四", "Fri": "五", "Sat": "六", "Sun": "日"}
DAY_MAP_HTML_INPUT = {"一": "Mon", "二": "Tue", "三": "Wed", "四": "Thu", "五": "Fri", "六": "Sat", "日": "Sun"}

# --- State Initialization ---

def initialize_session_state():
    """Initializes all necessary variables in Streamlit's session state."""
    if 'courses' not in st.session_state:
        st.session_state.courses = []
    if 'editing_course_index' not in st.session_state:
        st.session_state.editing_course_index = None # Using None instead of -1
    if 'current_editing_time_slots' not in st.session_state:
        st.session_state.current_editing_time_slots = []
    if 'generated_schedules' not in st.session_state:
        st.session_state.generated_schedules = []
    if 'conflict_schedules' not in st.session_state:
        st.session_state.conflict_schedules = []
    if 'gemini_api_key' not in st.session_state:
        st.session_state.gemini_api_key = ''

# --- Gemini API Helper ---

@st.cache_data(show_spinner="✨ 正在呼叫 AI...")
def call_gemini_api(prompt, api_key):
    """Helper function to call the Gemini API."""
    if not api_key:
        st.error("請在側邊欄輸入您的 Gemini API 金鑰。")
        return None
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        st.error(f"調用智慧API時出錯: {e}")
        return None

# --- Core Logic (from JS translated to Python) ---

def parse_html_to_courses(html_content):
    """Parses HTML table content into a list of course dictionaries."""
    if not html_content:
        return [], 0, 0

    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Try to find the most likely table
    tables = soup.find_all('table')
    if not tables:
        return [], 0, 0
    course_table = sorted(tables, key=lambda t: len(t.find_all('tr')), reverse=True)[0]
    
    rows = course_table.find_all('tr')
    newly_parsed_courses = []

    for row_idx, row in enumerate(rows):
        cells = row.find_all('td')
        if len(cells) < 15 or "系別" in cells[0].get_text():
            continue

        try:
            grade_text = cells[1].get_text(strip=True)
            original_class_id = cells[3].get_text(strip=True)
            class_group_text = cells[6].get_text(strip=True)
            
            combined_class_id = f"{grade_text} {class_group_text}".strip()
            if not combined_class_id: combined_class_id = original_class_id

            course_type = "必修" if "必" in cells[8].get_text(strip=True) else "選修"
            credits_val = int(cells[9].get_text(strip=True) or 0)
            
            name_cell = cells[11]
            course_name_text = name_cell.get_text(strip=True, separator=' ').split(' ')[0]

            teacher_cell = cells[13]
            teacher_name_text = teacher_cell.get_text(strip=True).split('(')[0]

            # --- Time Slot Parsing ---
            time_slots_list = []
            classroom_notes = []
            for time_cell_idx in [14, 15]:
                time_str = cells[time_cell_idx].get_text(strip=True)
                if not time_str or time_str == "　": continue
                parts = time_str.split('/')
                if len(parts) < 2: continue
                
                day_char, periods_str = parts[0], parts[1]
                classroom = parts[2] if len(parts) > 2 else ''
                day_eng = DAY_MAP_HTML_INPUT.get(day_char, day_char)
                
                if classroom: classroom_notes.append(classroom)
                
                for p_str in periods_str.split(','):
                    try:
                        period_num = int(p_str.strip())
                        time_slots_list.append([day_eng, period_num, classroom])
                    except ValueError:
                        continue
            
            notes = f"教室資訊: {', '.join(list(set(classroom_notes)))}" if classroom_notes else ""

            course_obj = {
                'name': course_name_text,
                'type': course_type,
                'class_id': combined_class_id,
                'credits': credits_val,
                'priority': 3,
                'time_slots': time_slots_list,
                'teacher': teacher_name_text,
                'notes': notes,
                'must_select': False,
                'temporarily_exclude': False,
                '_internal_original_id': original_class_id
            }
            newly_parsed_courses.append(course_obj)
        except (IndexError, ValueError) as e:
            print(f"Skipping row {row_idx} due to parsing error: {e}")
            continue

    # --- Add to main state, avoiding duplicates ---
    added_count = 0
    skipped_count = 0
    existing_ids = { (c.get('_internal_original_id') or c['class_id'], c['name']) for c in st.session_state.courses }

    for new_course in newly_parsed_courses:
        unique_key = (new_course.get('_internal_original_id') or new_course['class_id'], new_course['name'])
        if unique_key not in existing_ids:
            # Clean up temp property before adding
            if '_internal_original_id' in new_course:
                del new_course['_internal_original_id']
            st.session_state.courses.append(new_course)
            existing_ids.add(unique_key)
            added_count += 1
        else:
            skipped_count += 1

    return newly_parsed_courses, added_count, skipped_count

def generate_schedules_algorithm(all_courses, max_schedules):
    """The core scheduling algorithm, ported from JavaScript."""
    available_courses = [c for c in all_courses if not c.get('temporarily_exclude', False)]
    must_select_names = {c['name'] for c in available_courses if c.get('must_select', False)}

    grouped_courses = {}
    for c in available_courses:
        if c['name'] not in grouped_courses:
            grouped_courses[c['name']] = []
        grouped_courses[c['name']].append(c)

    course_options = [grouped_courses[name] for name in grouped_courses if grouped_courses[name]]

    if not course_options:
        return []

    # Using itertools.product for Cartesian product
    all_combinations = itertools.product(*course_options)
    
    schedules_found = []
    count_generated = 0

    for combo in all_combinations:
        if count_generated >= max_schedules:
            show_message(f"已達到最大排課方案數量 ({max_schedules})。", 'warning')
            break
        
        current_combo_course_names = {c['name'] for c in combo}
        if not must_select_names.issubset(current_combo_course_names):
            continue

        time_slot_map = {}
        conflict_details = []
        
        for course in combo:
            for day, period, _ in course.get('time_slots', []):
                key = f"{day}-{period}"
                if key not in time_slot_map:
                    time_slot_map[key] = []
                time_slot_map[key].append(course)

        for key, courses_in_slot in time_slot_map.items():
            if len(courses_in_slot) > 1:
                day, period_str = key.split('-')
                conflict_details.append({'day': day, 'period': int(period_str), 'courses': courses_in_slot})

        total_credits = sum(c['credits'] for c in combo)
        total_priority = sum(c['priority'] for c in combo)
        
        schedules_found.append({
            'combo': combo,
            'totalPriority': total_priority,
            'totalCredits': total_credits,
            'reqCredits': sum(c['credits'] for c in combo if c['type'] == '必修'),
            'eleCredits': sum(c['credits'] for c in combo if c['type'] == '選修'),
            'conflictsDetails': conflict_details if conflict_details else None,
            'conflictEventsCount': len(conflict_details)
        })
        count_generated += 1
        
    return schedules_found

# --- UI Rendering Functions ---

def render_sidebar():
    """Renders the sidebar for file operations and API key input."""
    with st.sidebar:
        st.title("操作選單")
        st.write("---")
        
        st.header("課程資料管理")
        json_uploader = st.file_uploader("載入課程資料 (JSON)", type=['json'])
        if json_uploader is not None:
            try:
                stringio = StringIO(json_uploader.getvalue().decode("utf-8"))
                loaded_data = json.load(stringio)
                if isinstance(loaded_data, list):
                    st.session_state.courses = loaded_data
                    show_message(f"成功載入 {len(st.session_state.courses)} 門課程。", 'success')
                else:
                    show_message("JSON 文件格式不正確，應為課程陣列。", 'error')
            except Exception as e:
                show_message(f"從 JSON 載入課程失敗: {e}", 'error')

        if st.session_state.courses:
            json_string = json.dumps(st.session_state.courses, indent=4, ensure_ascii=False)
            st.download_button(
                label="儲存課程資料 (JSON)",
                data=json_string,
                file_name="courses.json",
                mime="application/json",
            )
        
        st.write("---")
        st.header("AI 功能設定")
        st.session_state.gemini_api_key = st.text_input(
            "Google Gemini API 金鑰", 
            type="password", 
            value=st.session_state.get('gemini_api_key', ''),
            help="為了使用'產生建議備註'和'分析課表'功能，請在此輸入您的 API Key。"
        )

def render_add_edit_tab():
    """Renders the UI for adding or editing a course."""
    editing_mode = st.session_state.editing_course_index is not None
    
    if editing_mode:
        course = st.session_state.courses[st.session_state.editing_course_index]
        title = "編輯課程"
    else:
        course = {} # Default empty course for adding
        title = "新增課程"

    with st.form(key="course_form"):
        st.subheader(title)
        
        name = st.text_input("課程名稱*", value=course.get('name', ''))
        
        col1, col2 = st.columns(2)
        with col1:
            ctype = st.selectbox("類型*", ["必修", "選修"], index=["必修", "選修"].index(course.get('type', '選修')))
        with col2:
            class_id = st.text_input("班級 (年級+班別)*", value=course.get('class_id', ''))

        col3, col4 = st.columns(2)
        with col3:
            credits = st.number_input("學分數*", min_value=0, value=course.get('credits', 0), step=1)
        with col4:
            priority = st.select_slider("優先順序*", options=[1, 2, 3, 4, 5], value=course.get('priority', 3))

        teacher = st.text_input("授課老師", value=course.get('teacher', ''))
        
        # AI Smart Notes
        notes_col, btn_col = st.columns([3, 1])
        with notes_col:
            notes = st.text_area("備註", value=course.get('notes', ''), height=100)
        with btn_col:
            st.write("") # Spacer
            st.write("") # Spacer
            if st.button("✨ 產生建議備註"):
                if not name:
                    show_message("請先填寫課程名稱以產生建議備註。", 'warning')
                else:
                    prompt = f"針對一門大學課程「{name}」(授課老師: {teacher or '未知'})，請提供一些關於這門課可能的簡短備註。例如：作業量、教學風格、考試難度、是否推薦等。請以條列式呈現，總字數約50-100字。"
                    suggested_notes = call_gemini_api(prompt, st.session_state.gemini_api_key)
                    if suggested_notes:
                        notes = (notes + "\n\n" if notes else "") + "--- AI建議備註 ---\n" + suggested_notes
                        show_message("智慧備註已產生！", 'success')
        
        col5, col6 = st.columns(2)
        with col5:
            must_select = st.checkbox("必選", value=course.get('must_select', False))
        with col6:
            temporarily_exclude = st.checkbox("暫時排除", value=course.get('temporarily_exclude', False))
            
        # --- Time Slot Management ---
        with st.expander("上課時間*", expanded=True):
            st.write("目前已添加的時間：")
            if not st.session_state.current_editing_time_slots:
                st.caption("尚未添加時間")
            else:
                for i, ts in enumerate(st.session_state.current_editing_time_slots):
                    day, period, classroom = ts
                    ts_col1, ts_col2 = st.columns([4,1])
                    ts_col1.markdown(f"- **{DAY_MAP_DISPLAY.get(day, day)} 第 {period} 堂** (教室: {classroom or '未指定'})")
                    # The button needs to be inside the form to trigger a rerun correctly
                    if ts_col2.form_submit_button("移除", key=f"remove_ts_{i}", use_container_width=True):
                         st.session_state.current_editing_time_slots.pop(i)
                         st.rerun() # Rerun to reflect removal

            st.write("---")
            st.write("新增時間段：")
            ts_add_col1, ts_add_col2, ts_add_col3 = st.columns(3)
            with ts_add_col1:
                new_day = st.selectbox("星期", options=list(DAY_MAP_DISPLAY.keys()), format_func=lambda x: DAY_MAP_DISPLAY[x], key="new_day")
            with ts_add_col2:
                new_period = st.number_input("堂課", min_value=1, max_value=10, step=1, key="new_period")
            with ts_add_col3:
                # This button needs to be a form_submit_button to work within the form
                 if st.form_submit_button("➕ 添加時間", use_container_width=True):
                    new_slot = [new_day, new_period, ''] # Classroom is blank for manual adds
                    if new_slot not in st.session_state.current_editing_time_slots:
                        st.session_state.current_editing_time_slots.append(new_slot)
                        st.rerun() # Rerun to show the new slot
                    else:
                        show_message("該時間段已添加。", 'warning')

        # --- Form Submission ---
        st.write("---")
        submit_col1, submit_col2 = st.columns(2)
        submitted = submit_col1.form_submit_button("儲存課程" if editing_mode else "新增課程", type="primary", use_container_width=True)
        cleared = submit_col2.form_submit_button("清除表單", use_container_width=True)

        if submitted:
            if not name or not class_id or not st.session_state.current_editing_time_slots:
                show_message("請確保課程名稱、班級都已填寫，並已添加上課時間。", 'error')
            else:
                new_course_data = {
                    'name': name, 'type': ctype, 'class_id': class_id, 'credits': credits,
                    'priority': priority, 'teacher': teacher, 'notes': notes,
                    'must_select': must_select, 'temporarily_exclude': temporarily_exclude,
                    'time_slots': st.session_state.current_editing_time_slots
                }
                if editing_mode:
                    st.session_state.courses[st.session_state.editing_course_index] = new_course_data
                    show_message(f"課程 '{name}' 已更新。", 'success')
                else:
                    st.session_state.courses.append(new_course_data)
                    show_message(f"課程 '{name}' 已新增。", 'success')
                
                # Reset form state
                st.session_state.editing_course_index = None
                st.session_state.current_editing_time_slots = []
                st.rerun()
        
        if cleared:
            st.session_state.editing_course_index = None
            st.session_state.current_editing_time_slots = []
            st.rerun()

def render_html_import_tab():
    """Renders the UI for importing courses from HTML."""
    st.subheader("貼上HTML匯入課程")
    st.info("請從學校的課程查詢網頁，使用開發者工具 (F12) 選取包含所有課程資訊的 `<table>` 元素，然後複製其「外部 HTML」(Outer HTML)，並將其貼到下方的文字區域中。")
    
    html_paste_area = st.text_area("在此貼上課程表格的 HTML 原始碼", height=300, placeholder="<table>...</table>")
    
    if st.button("解析 HTML 並新增課程", type="primary"):
        if not html_paste_area:
            show_message("請先貼上 HTML 原始碼。", 'warning')
        else:
            with st.spinner("正在解析 HTML..."):
                _, added_count, skipped_count = parse_html_to_courses(html_paste_area)
            if added_count > 0:
                msg = f"成功從 HTML 新增 {added_count} 門課程。"
                if skipped_count > 0:
                    msg += f" 跳過了 {skipped_count} 門重複的課程。"
                show_message(msg, 'success')
            else:
                show_message("未從提供的 HTML 中解析到任何課程，或所有課程都已存在。", 'warning')

def render_course_list_tab():
    """Renders the course list using st.data_editor for interactivity."""
    st.subheader("課程列表")
    
    if not st.session_state.courses:
        st.warning("目前沒有課程。請從'新增課程'或'貼上HTML匯入'分頁加入。")
        return

    # Convert list of dicts to DataFrame for st.data_editor
    df = pd.DataFrame(st.session_state.courses)
    
    # Format time_slots for display
    df['time_slots_display'] = df['time_slots'].apply(
        lambda slots: '; '.join([f"{DAY_MAP_DISPLAY.get(s[0], s[0])}{s[1]}" + (f"({s[2]})" if s[2] else "") for s in slots])
    )
    
    # Add a 'delete' column for selection
    df.insert(0, "delete", False)

    column_config = {
        "delete": st.column_config.CheckboxColumn("刪除選取", default=False),
        "name": st.column_config.TextColumn("名稱", required=True),
        "type": st.column_config.SelectboxColumn("類型", options=["必修", "選修"], required=True),
        "class_id": "班級",
        "credits": st.column_config.NumberColumn("學分", min_value=0, format="%d"),
        "priority": st.column_config.NumberColumn("優先", min_value=1, max_value=5, format="%d"),
        "teacher": "老師",
        "time_slots_display": "時間/教室",
        "must_select": st.column_config.CheckboxColumn("必選", default=False),
        "temporarily_exclude": st.column_config.CheckboxColumn("排除", default=False),
        "notes": "備註",
        # Hide the raw time_slots column
        "time_slots": None,
    }
    
    column_order = [
        "delete", "name", "type", "class_id", "credits", "priority", 
        "teacher", "time_slots_display", "must_select", "temporarily_exclude", "notes"
    ]

    st.info("您可以直接在此表格中編輯大部分欄位。修改後，點擊下方的'更新課程列表'按鈕儲存變更。若要編輯上課時間，請使用下方的'編輯選取課程'功能。")
    
    edited_df = st.data_editor(
        df[column_order],
        column_config=column_config,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic" # This allows adding/deleting rows directly in the editor
    )
    
    if st.button("更新課程列表", type="primary"):
        # Filter out rows marked for deletion
        courses_to_keep = edited_df[edited_df['delete'] == False]
        
        # Convert DataFrame back to list of dicts, preserving original time_slots
        updated_courses = []
        for index, row in courses_to_keep.iterrows():
            original_course_data = {}
            if index < len(st.session_state.courses):
                original_course_data = st.session_state.courses[index]
            
            new_data = row.to_dict()
            new_data['time_slots'] = original_course_data.get('time_slots', []) # Keep original time slots
            del new_data['delete']
            del new_data['time_slots_display']
            updated_courses.append(new_data)
        
        st.session_state.courses = updated_courses
        show_message("課程列表已更新。", "success")
        st.rerun()

    st.write("---")
    st.subheader("編輯課程時間")
    st.caption("由於時間欄位較複雜，請在此選擇一門課進行編輯，系統將會跳轉至編輯頁面。")
    
    course_names_for_edit = [f"{i}: {c['name']} ({c['class_id']})" for i, c in enumerate(st.session_state.courses)]
    selected_course_to_edit = st.selectbox("選擇要編輯的課程", options=course_names_for_edit, index=None, placeholder="點此選擇...")

    if selected_course_to_edit:
        selected_index = int(selected_course_to_edit.split(':')[0])
        st.session_state.editing_course_index = selected_index
        # Pre-load time slots for the editing form
        st.session_state.current_editing_time_slots = st.session_state.courses[selected_index].get('time_slots', [])
        show_message("已載入課程進行編輯，請至'新增/編輯課程'分頁查看。")
        # No automatic tab switching in Streamlit, user needs to click the tab.
        st.rerun()
        
def render_schedule_generation_tab():
    """Renders the UI for generating and displaying schedules."""
    st.subheader("生成排課方案")
    
    with st.form("generation_form"):
        sort_option = st.radio(
            "選擇排序方式:",
            options=['conflict_priority', 'priority_conflict'],
            format_func=lambda x: {
                'conflict_priority': '先衝堂數量少到多，接著優先順序總和多到少',
                'priority_conflict': '先優先順序總和多到少，接著衝堂數量少到多'
            }[x]
        )
        max_schedules = st.number_input("最大排課方案數量:", min_value=10, max_value=10000, value=1000, step=100)
        
        generate_button = st.form_submit_button("生成排課方案", type="primary", use_container_width=True)

    if generate_button:
        if not st.session_state.courses:
            show_message("目前沒有課程可以排課。", 'warning')
            return
        
        with st.spinner("正在生成排課方案，請稍候..."):
            all_schedules_data = generate_schedules_algorithm(st.session_state.courses, max_schedules)

        if not all_schedules_data:
            show_message("無法生成任何排課方案。", 'error')
            st.session_state.generated_schedules = []
            st.session_state.conflict_schedules = []
            return

        # Sort the schedules
        all_schedules_data.sort(key=lambda s: (s['conflictEventsCount'], -s['totalPriority']) if sort_option == 'conflict_priority' else (-s['totalPriority'], s['conflictEventsCount']))
        
        st.session_state.generated_schedules = [s for s in all_schedules_data if s['conflictEventsCount'] == 0]
        st.session_state.conflict_schedules = [s for s in all_schedules_data if s['conflictEventsCount'] > 0]
        show_message(f"排課方案已生成。共 {len(all_schedules_data)} 個方案。", 'success')

    # --- Display Results ---
    if st.session_state.generated_schedules or st.session_state.conflict_schedules:
        st.write("---")
        st.header("排課結果")
        
        # Non-conflicting schedules
        st.subheader(f"✅ 不衝堂方案 ({len(st.session_state.generated_schedules)} 個)")
        if not st.session_state.generated_schedules:
            st.caption("無不衝堂的排課方案。")
        for i, schedule in enumerate(st.session_state.generated_schedules):
            render_single_schedule(schedule, i, is_conflict=False)

        # Conflicting schedules
        st.subheader(f"⚠️ 有衝堂方案 ({len(st.session_state.conflict_schedules)} 個)")
        if not st.session_state.conflict_schedules:
            st.caption("目前無有衝堂方案。")
        for i, schedule in enumerate(st.session_state.conflict_schedules):
            render_single_schedule(schedule, i, is_conflict=True)

def render_single_schedule(schedule, index, is_conflict):
    """Renders a single schedule inside an expander."""
    header = f"方案 {index + 1} (總優先度: {schedule['totalPriority']}, 總學分: {schedule['totalCredits']}"
    if is_conflict:
        header += f", 衝堂數: {schedule['conflictEventsCount']})"
    else:
        header += ")"
        
    with st.expander(header):
        st.markdown(f"**必修**: {schedule['reqCredits']} 學分, **選修**: {schedule['eleCredits']} 學分")
        
        # --- Course List ---
        for course in schedule['combo']:
            ts_str = '; '.join([f"{DAY_MAP_DISPLAY.get(s[0], s[0])}{s[1]}" for s in course['time_slots']])
            st.markdown(f"- **{course['name']}** ({course['type']}, {course['credits']}學分) - *{course['teacher']}* `時:{ts_str}`")

        # --- AI Analysis ---
        if st.button("✨ 分析此課表並提供建議", key=f"analyze_{'c' if is_conflict else 'nc'}_{index}"):
            course_descs = '; '.join([f"{c['name']} ({c['type']}, {c['credits']}學分, 老師: {c.get('teacher', '未知')})" for c in schedule['combo']])
            prompt = f"這是一個大學生的課表草案，總共 {schedule['totalCredits']} 學分，包含以下課程：{course_descs}。請針對這個課表提供一些分析與建議，例如：\n1. 整體學習負擔評估 (例如：輕鬆、適中、繁重)。\n2. 潛在的挑戰 (例如：某幾門課可能同時很多報告或考試)。\n3. 時間管理上的建議。\n4. 任何其他值得注意的優點或機會。\n請以條列式、簡潔的方式呈現，總字數約100-150字。"
            analysis_result = call_gemini_api(prompt, st.session_state.gemini_api_key)
            if analysis_result:
                st.info(f"**AI 課表分析建議:**\n\n{analysis_result}")

        # --- Conflict Details ---
        if is_conflict and schedule['conflictsDetails']:
            st.write("---")
            st.error("**衝堂詳情:**")
            for conflict in schedule['conflictsDetails']:
                overlap_str = ', '.join([c['name'] for c in conflict['courses']])
                st.markdown(f"- **{DAY_MAP_DISPLAY[conflict['day']]} 第 {conflict['period']} 堂:** {overlap_str}")

        # --- Schedule Grid ---
        st.write("---")
        render_schedule_grid(schedule)

def render_schedule_grid(schedule):
    """Renders the visual grid for a schedule."""
    days = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    periods = range(1, 11)
    
    # Create an empty DataFrame for the grid
    grid_df = pd.DataFrame(index=periods, columns=[DAY_MAP_DISPLAY[d] for d in days])
    grid_df = grid_df.fillna('')

    for course in schedule['combo']:
        for day, period, classroom in course.get('time_slots', []):
            if day in days:
                cell_content = f"**{course['name']}**<br><small>{course.get('teacher', '')}<br>{classroom}</small>"
                # Check for conflict
                if grid_df.loc[period, DAY_MAP_DISPLAY[day]]:
                     grid_df.loc[period, DAY_MAP_DISPLAY[day]] += f"<hr><span style='color:red;'>{cell_content}</span>"
                else:
                     grid_df.loc[period, DAY_MAP_DISPLAY[day]] = cell_content

    # Use st.markdown to render the table with HTML
    st.markdown(grid_df.to_html(escape=False), unsafe_allow_html=True)

# --- Main Application ---

def main():
    st.title("互動式排課助手")
    initialize_session_state()
    render_sidebar()

    tab1, tab2, tab3, tab4 = st.tabs([
        "課程列表", 
        "新增/編輯課程", 
        "貼上HTML匯入", 
        "生成排課方案"
    ])

    with tab1:
        render_course_list_tab()
    with tab2:
        render_add_edit_tab()
    with tab3:
        render_html_import_tab()
    with tab4:
        render_schedule_generation_tab()

if __name__ == "__main__":
    main()
