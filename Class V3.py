import streamlit as st
import pandas as pd
import json
from bs4 import BeautifulSoup
from itertools import product
from collections import defaultdict
import copy

# --- Page Configuration ---
st.set_page_config(
    page_title="互動式排課助手 (Streamlit)",
    page_icon="🗓️",
    layout="wide"
)

# --- Helper Dictionaries and Constants ---
DAY_MAP_DISPLAY = {"Mon": "一", "Tue": "二", "Wed": "三", "Thu": "四", "Fri": "五", "Sat": "六", "Sun": "日"}
DAY_MAP_HTML_INPUT = {"一": "Mon", "二": "Tue", "三": "Wed", "四": "Thu", "五": "Fri", "六": "Sat", "日": "Sun"}
DAY_OPTIONS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PRIORITY_OPTIONS = [1, 2, 3, 4, 5]

# --- Default Course Structure ---
def create_course_object(data={}):
    return {
        'name': data.get('name', ''),
        'type': data.get('type', '選修'),
        'class_id': data.get('class_id', ''),
        'credits': int(data.get('credits', 0)),
        'priority': int(data.get('priority', 3)),
        'time_slots': data.get('time_slots', []),  # List of [day, period]
        'must_select': data.get('must_select', False),
        'temporarily_exclude': data.get('temporarily_exclude', False),
        'teacher': data.get('teacher', ''),
        'notes': data.get('notes', '')
    }

# --- Session State Initialization ---
def initialize_session_state():
    if 'courses' not in st.session_state:
        st.session_state.courses = []
    if 'add_form_time_slots' not in st.session_state:
        st.session_state.add_form_time_slots = []
    if 'editing_course_index' not in st.session_state:
        st.session_state.editing_course_index = -1 # -1 for new, index for editing
    if 'generated_schedules' not in st.session_state:
        st.session_state.generated_schedules = []


# --- Sidebar for File Operations ---
def render_sidebar():
    with st.sidebar:
        st.header("⚙️ 操作選單")
        
        st.subheader("載入/儲存課程資料")

        # Load from JSON
        uploaded_file = st.file_uploader("載入課程資料 (JSON)", type="json")
        if uploaded_file is not None:
            try:
                loaded_data = json.load(uploaded_file)
                if isinstance(loaded_data, list):
                    st.session_state.courses = [create_course_object(c) for c in loaded_data]
                    st.toast(f"✅ 成功載入 {len(st.session_state.courses)} 門課程。", icon="🎉")
                else:
                    st.error("JSON 檔案格式不正確，應為課程陣列。")
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
        else:
            st.warning("目前沒有課程可以儲存。")
            
# --- Tab: Add/Edit Course ---
def render_add_edit_tab():
    is_editing = st.session_state.editing_course_index > -1
    header_text = "編輯課程" if is_editing else "新增課程"
    submit_text = "更新課程" if is_editing else "新增課程到列表"

    course_to_edit = {}
    if is_editing:
        course_to_edit = st.session_state.courses[st.session_state.editing_course_index]

    with st.form("course_form", clear_on_submit=True):
        st.subheader(header_text)
        
        c_name = st.text_input("課程名稱*", value=course_to_edit.get('name', ''))
        
        col1, col2 = st.columns(2)
        with col1:
            c_type = st.selectbox("類型*", ["必修", "選修"], index=["必修", "選修"].index(course_to_edit.get('type', '選修')))
            c_credits = st.number_input("學分數*", min_value=0, value=course_to_edit.get('credits', 0))
        with col2:
            c_class_id = st.text_input("班級/科系代碼*", value=course_to_edit.get('class_id', ''))
            c_priority = st.selectbox("優先順序*", PRIORITY_OPTIONS, index=PRIORITY_OPTIONS.index(course_to_edit.get('priority', 3)))

        c_teacher = st.text_input("授課老師", value=course_to_edit.get('teacher', ''))
        c_notes = st.text_area("備註", value=course_to_edit.get('notes', ''))

        col_check1, col_check2 = st.columns(2)
        with col_check1:
            c_must_select = st.checkbox("必選", value=course_to_edit.get('must_select', False))
        with col_check2:
            c_temporarily_exclude = st.checkbox("暫時排除", value=course_to_edit.get('temporarily_exclude', False))

        st.markdown("---")
        st.subheader("上課時間*")

        # Time Slot Management
        with st.container(border=True):
            slot_col1, slot_col2, slot_col3 = st.columns([2, 1, 1])
            with slot_col1:
                day_key = "time_slot_day"
                selected_day = st.selectbox("星期", DAY_OPTIONS, format_func=lambda d: DAY_MAP_DISPLAY[d], key=day_key)
            with slot_col2:
                period_key = "time_slot_period"
                selected_period = st.number_input("堂課", min_value=1, max_value=10, key=period_key)

            def add_time_slot():
                new_slot = [selected_day, selected_period]
                if new_slot not in st.session_state.add_form_time_slots:
                    st.session_state.add_form_time_slots.append(new_slot)
                else:
                    st.toast("該時間段已添加。", icon="⚠️")
            
            with slot_col3:
                 st.button("添加時間", on_click=add_time_slot, use_container_width=True)

            if not st.session_state.add_form_time_slots:
                st.caption("尚未添加時間")
            else:
                for i, (day, period) in enumerate(st.session_state.add_form_time_slots):
                    ts_col1, ts_col2 = st.columns([4, 1])
                    ts_col1.write(f"• {DAY_MAP_DISPLAY[day]} 第 {period} 堂")
                    def remove_time_slot(index):
                        st.session_state.add_form_time_slots.pop(index)
                    ts_col2.button("移除", key=f"remove_ts_{i}", on_click=remove_time_slot, args=(i,), use_container_width=True)

        st.markdown("---")
        
        submitted = st.form_submit_button(submit_text, use_container_width=True, type="primary")
        if submitted:
            if not c_name or not c_class_id or not st.session_state.add_form_time_slots:
                st.error("請確保課程名稱、班級都已填寫，並已添加上課時間。")
            else:
                course_data = {
                    'name': c_name, 'type': c_type, 'class_id': c_class_id, 'credits': c_credits,
                    'priority': c_priority, 'teacher': c_teacher, 'notes': c_notes,
                    'must_select': c_must_select, 'temporarily_exclude': c_temporarily_exclude,
                    'time_slots': st.session_state.add_form_time_slots
                }
                new_course = create_course_object(course_data)
                
                if is_editing:
                    st.session_state.courses[st.session_state.editing_course_index] = new_course
                    st.toast(f"課程 '{new_course['name']}' 已更新。", icon="🔄")
                else:
                    # Check for duplicates before adding
                    duplicate = next((c for c in st.session_state.courses if c['name'] == new_course['name'] and c['class_id'] == new_course['class_id']), None)
                    if duplicate:
                        st.error(f"課程 '{new_course['name']}' (班級 {new_course['class_id']}) 已存在。")
                    else:
                        st.session_state.courses.append(new_course)
                        st.toast(f"課程 '{new_course['name']}' 已新增。", icon="✅")
                
                # Reset form state
                st.session_state.add_form_time_slots = []
                st.session_state.editing_course_index = -1
                st.rerun()

# --- Tab: Import HTML ---
def render_import_html_tab():
    st.subheader("貼上HTML匯入課程")
    st.info("請從學校的課程查詢網頁，複製包含所有課程資訊的 `<table>` 元素的「外部 HTML」(Outer HTML)，並將其貼到下方。")

    html_paste_area = st.text_area("在此貼上課程表格的 HTML 原始碼", height=300, label_visibility="collapsed")

    def parse_time_slot_string_for_html(time_str, current_notes_ref):
        slots, classroom_info = [], ""
        if time_str and time_str.strip() and time_str.strip() != "　":
            parts = time_str.split('/')
            if len(parts) >= 2:
                day_eng = DAY_MAP_HTML_INPUT.get(parts[0], parts[0])
                periods_str = parts[1]
                if len(parts) >= 3:
                    classroom_info = parts[2]
                
                for p_str in periods_str.split(','):
                    try:
                        slots.append([day_eng, int(p_str.strip())])
                    except ValueError:
                        pass
        if classroom_info:
            existing = current_notes_ref.get("classroom", "")
            if classroom_info not in existing:
                current_notes_ref["classroom"] = (existing + "; " if existing else "") + classroom_info
        return slots

    if st.button("解析 HTML 並新增課程", use_container_width=True, type="primary"):
        if not html_paste_area:
            st.warning("請先貼上 HTML 原始碼。")
            return

        soup = BeautifulSoup(html_paste_area, 'html.parser')
        tables = soup.find_all('table')
        if not tables:
            st.error("在貼上的內容中找不到任何 <table> 元素。")
            return
            
        course_table = max(tables, key=lambda t: len(t.find_all('tr')))
        rows = course_table.find_all('tr')
        newly_parsed_courses = []
        
        for i, row in enumerate(rows):
            cells = row.find_all('td')
            # NCKU specific logic, may need adjustment for other schools
            if len(cells) < 15 or (cells[0] and "系別" in cells[0].get_text()):
                continue
            
            try:
                notes_dict = {}
                grade_text = cells[1].get_text(strip=True)
                if grade_text: notes_dict["grade"] = f"年級: {grade_text}"

                class_id = cells[3].get_text(strip=True)
                course_type = "必修" if cells[8].get_text(strip=True) == "必" else "選修"
                credits = int(cells[9].get_text(strip=True) or 0)
                
                name_cell = cells[11]
                course_name = name_cell.get_text(strip=True)
                # Refine name extraction if needed
                if name_cell.find('u'): course_name = name_cell.find('u').get_text(strip=True)
                
                teacher = cells[13].get_text(strip=True).split('(')[0]
                
                time_slots = []
                time_slots.extend(parse_time_slot_string_for_html(cells[14].get_text(strip=True), notes_dict))
                time_slots.extend(parse_time_slot_string_for_html(cells[15].get_text(strip=True), notes_dict))
                
                final_notes = "; ".join(filter(None, notes_dict.values()))

                if course_name and class_id:
                    parsed_course = create_course_object({
                        'name': course_name, 'type': course_type, 'class_id': class_id,
                        'credits': credits, 'teacher': teacher, 'time_slots': time_slots, 'notes': final_notes
                    })
                    newly_parsed_courses.append(parsed_course)

            except Exception as e:
                st.warning(f"處理第 {i+1} 行時出錯: {e}")

        added_count, skipped_count = 0, 0
        for new_course in newly_parsed_courses:
            is_duplicate = any(c['name'] == new_course['name'] and c['class_id'] == new_course['class_id'] for c in st.session_state.courses)
            if not is_duplicate:
                st.session_state.courses.append(new_course)
                added_count += 1
            else:
                skipped_count += 1
        
        if added_count > 0:
            st.success(f"成功從 HTML 新增 {added_count} 門課程。")
        if skipped_count > 0:
            st.info(f"跳過了 {skipped_count} 門重複的課程。")
        if added_count == 0 and skipped_count == 0:
            st.warning("未從提供的 HTML 中解析到任何課程。")

# --- Tab: Course List ---
def render_course_list_tab():
    st.subheader("課程列表")
    st.info("""
    - **必選**: 在排課時，此課程會被強制排入（除非被暫時排除）。
    - **暫時排除**: 暫時不將該課程納入排課考慮。
    - **編輯**: 點擊 `編輯` 按鈕修改課程所有欄位。
    - **直接編輯**: 您可以直接在下表中修改部分欄位 (如名稱、學分)，修改後會自動保存。
    """)

    if not st.session_state.courses:
        st.warning("目前沒有課程。請先新增或匯入。")
        return

    # Convert to DataFrame for st.data_editor
    df = pd.DataFrame(st.session_state.courses)
    df.insert(0, "select", False) # For selection
    
    # Reorder and rename columns for display
    display_cols = {
        'select': '選取', 'name': '名稱', 'type': '類型', 'class_id': '班級', 'credits': '學分',
        'priority': '優先', 'teacher': '老師', 'time_slots': '時間槽',
        'must_select': '必選', 'temporarily_exclude': '排除', 'notes': '備註'
    }
    df['time_slots'] = df['time_slots'].apply(lambda slots: '; '.join([f"{DAY_MAP_DISPLAY.get(s[0], s[0])}{s[1]}" for s in slots]))
    
    df_display = df[display_cols.keys()].rename(columns=display_cols)
    
    # Use data_editor for interactivity
    edited_df = st.data_editor(
        df_display,
        key="course_list_editor",
        use_container_width=True,
        hide_index=True,
        column_config={
             "選取": st.column_config.CheckboxColumn(required=True)
        },
        num_rows="dynamic" # Allow deletion
    )

    # Detect changes and update session state
    if edited_df is not None:
        # Check for row deletions
        if len(edited_df) < len(st.session_state.courses):
            # This is complex to map back perfectly without unique IDs. A simpler approach is to rebuild.
            st.warning("偵測到行刪除。請使用下方的 '刪除選取列' 按鈕。表格已還原。")
        else:
            # Update courses based on edits
            updated_courses = []
            for i, row in edited_df.iterrows():
                # Revert time_slots from string to list of lists
                original_course = st.session_state.courses[i]
                updated_course_data = {
                    'name': row['名稱'], 'type': row['類型'], 'class_id': row['班級'],
                    'credits': int(row['學分']), 'priority': int(row['優先']), 'teacher': row['老師'],
                    'must_select': row['必選'], 'temporarily_exclude': row['排除'],
                    'notes': row['備註'], 'time_slots': original_course['time_slots'] # Keep original slots as they are not editable here
                }
                updated_courses.append(updated_course_data)
            
            if updated_courses != st.session_state.courses:
                 st.session_state.courses = updated_courses
                 st.toast("課程列表已更新。", icon="💾")
                 # No rerun needed, data_editor handles its state
    
    col1, col2, _ = st.columns([1,1,3])
    with col1:
        if st.button("刪除選取列", use_container_width=True):
            selected_indices = edited_df[edited_df['選取']].index.tolist()
            if not selected_indices:
                st.warning("請先選取要刪除的課程。")
            else:
                # Delete from backend list in reverse order
                for i in sorted(selected_indices, reverse=True):
                    st.session_state.courses.pop(i)
                st.toast(f"已刪除 {len(selected_indices)} 門課程。", icon="🗑️")
                st.rerun()

    with col2:
        if st.button("編輯選取列", use_container_width=True):
            selected_indices = edited_df[edited_df['選取']].index.tolist()
            if len(selected_indices) != 1:
                st.warning("請只選取一門課程進行編輯。")
            else:
                index_to_edit = selected_indices[0]
                st.session_state.editing_course_index = index_to_edit
                st.session_state.add_form_time_slots = copy.deepcopy(st.session_state.courses[index_to_edit]['time_slots'])
                # Switch to the 'Add/Edit' tab by changing the query param, a common Streamlit pattern
                st.query_params["tab"] = "add"
                st.rerun()

# --- Tab: Generate Schedules ---
def render_generate_tab():
    st.subheader("生成排課方案")
    with st.container(border=True):
        sort_option = st.radio(
            "選擇排序方式:",
            ("conflict_priority", "priority_conflict"),
            format_func=lambda x: "先衝堂數量少 > 多，再優先順序總和高 > 低" if x == "conflict_priority" else "先優先順序總和高 > 低，再衝堂數量少 > 多",
            horizontal=True
        )
        max_schedules = st.number_input("最大排課方案數量:", min_value=10, max_value=10000, value=1000)

    if st.button("🚀 生成排課方案", type="primary", use_container_width=True):
        if not st.session_state.courses:
            st.error("沒有課程可以排課。")
            return
        
        with st.spinner("正在生成排課方案，請稍候..."):
            all_schedules_data = generate_schedules_algorithm(st.session_state.courses, max_schedules)
            
            if not all_schedules_data:
                st.warning("無法生成任何排課方案。請檢查課程設定（例如是否有必選課程但已被排除）。")
                st.session_state.generated_schedules = []
                return

            all_schedules_data.sort(key=lambda s: (s['conflictEventsCount'], -s['totalPriority']) if sort_option == "conflict_priority" else (-s['totalPriority'], s['conflictEventsCount']))
            
            st.session_state.generated_schedules = all_schedules_data
            st.success(f"排課方案已生成。共 {len(all_schedules_data)} 個方案。")

    # Display results if they exist
    if st.session_state.generated_schedules:
        no_conflict_schedules = [s for s in st.session_state.generated_schedules if s['conflictEventsCount'] == 0]
        conflict_schedules = [s for s in st.session_state.generated_schedules if s['conflictEventsCount'] > 0]
        
        st.header("✅ 不衝堂方案")
        if not no_conflict_schedules:
            st.info("無不衝堂的排課方案。")
        else:
            display_schedules(no_conflict_schedules)

        st.header("⚠️ 有衝堂方案")
        if not conflict_schedules:
            st.info("目前無有衝堂方案。")
        else:
            display_schedules(conflict_schedules)

def generate_schedules_algorithm(all_courses, max_schedules):
    available_courses = [c for c in all_courses if not c['temporarily_exclude']]
    must_select_names = {c['name'] for c in available_courses if c['must_select']}

    # Group courses by name
    grouped_courses = defaultdict(list)
    for c in available_courses:
        grouped_courses[c['name']].append(c)

    # Ensure must-select courses have options
    for name in must_select_names:
        if not grouped_courses[name]:
            st.error(f"必選課程 '{name}' 沒有可選的時間段或已被暫時排除。")
            return []

    # Cartesian product of course options
    course_options = [grouped_courses[name] for name in grouped_courses]
    all_combinations = product(*course_options)

    schedules_found = []
    for i, combo in enumerate(all_combinations):
        if len(schedules_found) >= max_schedules:
            st.warning(f"已達到最大排課方案數量 ({max_schedules})，停止生成。")
            break
        
        # Check if combo satisfies all must-select courses
        combo_names = {c['name'] for c in combo}
        if not must_select_names.issubset(combo_names):
            continue

        # Check for conflicts
        time_slot_map = defaultdict(list)
        for c in combo:
            for day, period in c['time_slots']:
                time_slot_map[f"{day}-{period}"].append(c)
        
        conflicts_details = []
        for key, courses_in_slot in time_slot_map.items():
            if len(courses_in_slot) > 1:
                day, period = key.split('-')
                conflicts_details.append({'day': day, 'period': int(period), 'courses': courses_in_slot})
        
        total_credits = sum(c['credits'] for c in combo)
        schedules_found.append({
            'combo': combo,
            'totalPriority': sum(c['priority'] for c in combo),
            'totalCredits': total_credits,
            'reqCredits': sum(c['credits'] for c in combo if c['type'] == '必修'),
            'eleCredits': sum(c['credits'] for c in combo if c['type'] == '選修'),
            'conflictsDetails': conflicts_details,
            'conflictEventsCount': len(conflicts_details)
        })
    return schedules_found

def display_schedules(schedules):
    for i, schedule in enumerate(schedules):
        summary_parts = [
            f"方案 {i + 1}",
            f"優:{schedule['totalPriority']}",
            f"學分:{schedule['totalCredits']}"
        ]
        if schedule['conflictEventsCount'] > 0:
            summary_parts.insert(1, f"衝:{schedule['conflictEventsCount']}")
        
        with st.expander(" | ".join(summary_parts)):
            st.markdown(f"**必修**: {schedule['reqCredits']} 學分, **選修**: {schedule['eleCredits']} 學分")
            
            for course in schedule['combo']:
                st.markdown(f"- **{course['name']}** ({course['type']}) | 班:{course['class_id']}, 學分:{course['credits']}, 優:{course['priority']}, 師:{course.get('teacher', 'N/A')}")
            
            # Display schedule grid
            st.dataframe(create_schedule_grid_df(schedule), use_container_width=True)

            if schedule['conflictsDetails']:
                st.markdown("🔴 **衝堂詳情**:")
                for conflict in schedule['conflictsDetails']:
                    overlap_str = ', '.join([c['name'] for c in conflict['courses']])
                    st.write(f"- {DAY_MAP_DISPLAY[conflict['day']]} 第 {conflict['period']} 堂: {overlap_str}")

def create_schedule_grid_df(schedule):
    days_to_display = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    periods = range(1, 11)
    df = pd.DataFrame(index=periods, columns=[DAY_MAP_DISPLAY[d] for d in days_to_display])
    df = df.fillna('')

    for course in schedule['combo']:
        for day, period in course['time_slots']:
            if day in days_to_display:
                display_day = DAY_MAP_DISPLAY[day]
                # Combine name and teacher, handle potential conflicts in the same cell
                cell_content = f"{course['name']}\n({course.get('teacher', 'N/A')})"
                if df.at[period, display_day] == '':
                    df.at[period, display_day] = cell_content
                else: # Conflict
                    df.at[period, display_day] += f"\n---\n{cell_content}"
    
    # Custom styling for conflicts
    def style_conflicts(val):
        return 'background-color: #fee2e2; color: #ef4444; font-weight: bold;' if '---\n' in val else ''
    
    return df.style.applymap(style_conflicts)

# --- Main App Logic ---
def main():
    st.title("🗓️ 互動式排課助手 (Streamlit 版)")
    initialize_session_state()
    render_sidebar()

    # Tab navigation using query parameters
    query_params = st.query_params
    default_tab_index = ["add", "html", "list", "gen"].index(query_params.get("tab", "add"))

    tab1, tab2, tab3, tab4 = st.tabs(["✍️ 新增/編輯課程", "📋 貼上HTML匯入", "📚 課程列表", "📊 生成排課方案"])

    with tab1:
        render_add_edit_tab()
    with tab2:
        render_import_html_tab()
    with tab3:
        render_course_list_tab()
    with tab4:
        render_generate_tab()

if __name__ == "__main__":
    main()
