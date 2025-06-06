import streamlit as st
import pandas as pd
import json
from bs4 import BeautifulSoup
import itertools
from io import StringIO

# --- 頁面設定與輔助函式 ---

st.set_page_config(page_title="互動式排課助手", layout="wide")

def show_message(message, type='info'):
    """統一顯示訊息的方式，使用 st.toast 彈出提示。"""
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

# --- 狀態初始化 ---

def initialize_session_state():
    """初始化 Streamlit Session State 中所有必要的變數。"""
    if 'courses' not in st.session_state:
        st.session_state.courses = []
    if 'editing_course_index' not in st.session_state:
        st.session_state.editing_course_index = None
    if 'current_editing_time_slots' not in st.session_state:
        st.session_state.current_editing_time_slots = []
    if 'generated_schedules' not in st.session_state:
        st.session_state.generated_schedules = []
    if 'conflict_schedules' not in st.session_state:
        st.session_state.conflict_schedules = []

# --- 核心邏輯 (從 JS 轉譯為 Python) ---

def parse_html_to_courses(html_content):
    """
    將 HTML 表格內容解析為課程字典列表。
    *** NEW LOGIC ***: 使用 (課程名稱, 老師) 作為 key，將多行但屬於同一門課的時間合併。
    """
    if not html_content:
        return 0, 0

    soup = BeautifulSoup(html_content, 'html.parser')
    
    tables = soup.find_all('table')
    if not tables:
        return 0, 0
    # 假設課程最多的表格是主表格
    course_table = sorted(tables, key=lambda t: len(t.find_all('tr')), reverse=True)[0]
    
    rows = course_table.find_all('tr')
    # 使用字典來合併屬於同一老師的同一門課程
    parsed_courses_dict = {}

    for row_idx, row in enumerate(rows):
        cells = row.find_all('td')
        if len(cells) < 15 or "系別" in cells[0].get_text():
            continue

        try:
            # --- 解析儲存格資料 ---
            grade_text = cells[1].get_text(strip=True)
            class_group_text = cells[6].get_text(strip=True)
            combined_class_id = f"{grade_text} {class_group_text}".strip() or cells[3].get_text(strip=True)

            course_type = "必修" if "必" in cells[8].get_text(strip=True) else "選修"
            credits_val = int(cells[9].get_text(strip=True) or 0)
            
            name_cell = cells[11]
            course_name_text = name_cell.get_text(strip=True, separator=' ').split(' ')[0]

            teacher_cell = cells[13]
            teacher_name_text = teacher_cell.get_text(strip=True).split('(')[0]
            
            # --- 解析時間與教室 ---
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

            # --- 合併邏輯 ---
            course_key = (course_name_text, teacher_name_text)
            if course_key in parsed_courses_dict:
                # 如果課程已存在，合併時間和備註
                parsed_courses_dict[course_key]['time_slots'].extend(time_slots_list)
                # 避免重複時間
                unique_slots = [list(t) for t in set(tuple(s) for s in parsed_courses_dict[course_key]['time_slots'])]
                parsed_courses_dict[course_key]['time_slots'] = unique_slots
                if notes and notes not in parsed_courses_dict[course_key]['notes']:
                    parsed_courses_dict[course_key]['notes'] += " / " + notes
            else:
                # 如果是新課程，建立新項目
                course_obj = {
                    'name': course_name_text, 'type': course_type, 'class_id': combined_class_id,
                    'credits': credits_val, 'priority': 3, 'time_slots': time_slots_list,
                    'teacher': teacher_name_text, 'notes': notes, 'must_select': False,
                    'temporarily_exclude': False
                }
                parsed_courses_dict[course_key] = course_obj

        except (IndexError, ValueError) as e:
            print(f"Skipping row {row_idx} due to parsing error: {e}")
            continue
    
    # --- 將解析完的課程與現有課程列表合併 ---
    newly_parsed_courses = list(parsed_courses_dict.values())
    added_count = 0
    skipped_count = 0
    existing_course_keys = {(c['name'], c['teacher']) for c in st.session_state.courses}

    for new_course in newly_parsed_courses:
        key = (new_course['name'], new_course['teacher'])
        if key not in existing_course_keys:
            st.session_state.courses.append(new_course)
            added_count += 1
        else:
            skipped_count += 1

    return added_count, skipped_count


def generate_schedules_algorithm(all_courses, max_schedules):
    """核心排課演算法"""
    # 篩選出未被排除的課程
    available_courses = [c for c in all_courses if not c.get('temporarily_exclude', False)]
    # 找出必選課程的名稱
    must_select_names = {c['name'] for c in available_courses if c.get('must_select', False)}

    # *** GROUPING LOGIC ***: 以課程名稱將不同老師/時段的課程分組
    grouped_courses = {}
    for c in available_courses:
        if c['name'] not in grouped_courses:
            grouped_courses[c['name']] = []
        grouped_courses[c['name']].append(c)

    # course_options 會是 [[微積分A], [微積分B]], [[線代A]], ...
    course_options = [grouped_courses[name] for name in grouped_courses if grouped_courses[name]]

    if not course_options:
        return []

    # 使用 itertools.product 產生所有可能的課程組合
    # 演算法會從每個群組中挑選一個，確保同名課只會出現一次
    all_combinations = itertools.product(*course_options)
    
    schedules_found = []
    count_generated = 0

    for combo in all_combinations:
        if count_generated >= max_schedules:
            show_message(f"已達到最大排課方案數量 ({max_schedules})。", 'warning')
            break
        
        # 檢查是否包含所有必選課程
        current_combo_course_names = {c['name'] for c in combo}
        if not must_select_names.issubset(current_combo_course_names):
            continue

        # 檢查時間衝突
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
            'combo': combo, 'totalPriority': total_priority, 'totalCredits': total_credits,
            'reqCredits': sum(c['credits'] for c in combo if c['type'] == '必修'),
            'eleCredits': sum(c['credits'] for c in combo if c['type'] == '選修'),
            'conflictsDetails': conflict_details if conflict_details else None,
            'conflictEventsCount': len(conflict_details)
        })
        count_generated += 1
        
    return schedules_found

# --- UI 渲染函式 (與前一版相同) ---

def render_sidebar():
    """渲染側邊欄，用於檔案操作。"""
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

def render_add_edit_tab():
    """渲染新增或編輯課程的 UI。"""
    editing_mode = st.session_state.editing_course_index is not None
    
    if editing_mode:
        course = st.session_state.courses[st.session_state.editing_course_index]
        title = "編輯課程"
    else:
        course = {}
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
        
        notes = st.text_area("備註", value=course.get('notes', ''), height=100)
        
        col5, col6 = st.columns(2)
        with col5:
            must_select = st.checkbox("必選", value=course.get('must_select', False))
        with col6:
            temporarily_exclude = st.checkbox("暫時排除", value=course.get('temporarily_exclude', False))
            
        with st.expander("上課時間*", expanded=True):
            st.write("目前已添加的時間：")
            if not st.session_state.current_editing_time_slots:
                st.caption("尚未添加時間")
            else:
                for i, ts in enumerate(st.session_state.current_editing_time_slots):
                    day, period, classroom = ts
                    ts_col1, ts_col2 = st.columns([4,1])
                    ts_col1.markdown(f"- **{DAY_MAP_DISPLAY.get(day, day)} 第 {period} 堂** (教室: {classroom or '未指定'})")
                    if ts_col2.form_submit_button("移除", key=f"remove_ts_{i}", use_container_width=True):
                         st.session_state.current_editing_time_slots.pop(i)
                         st.rerun()

            st.write("---")
            st.write("新增時間段：")
            ts_add_col1, ts_add_col2, ts_add_col3 = st.columns(3)
            with ts_add_col1:
                new_day = st.selectbox("星期", options=list(DAY_MAP_DISPLAY.keys()), format_func=lambda x: DAY_MAP_DISPLAY[x], key="new_day")
            with ts_add_col2:
                new_period = st.number_input("堂課", min_value=1, max_value=10, step=1, key="new_period")
            with ts_add_col3:
                 if st.form_submit_button("➕ 添加時間", use_container_width=True):
                    new_slot = [new_day, new_period, '']
                    if new_slot not in st.session_state.current_editing_time_slots:
                        st.session_state.current_editing_time_slots.append(new_slot)
                        st.rerun()
                    else:
                        show_message("該時間段已添加。", 'warning')

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
                
                st.session_state.editing_course_index = None
                st.session_state.current_editing_time_slots = []
                st.rerun()
        
        if cleared:
            st.session_state.editing_course_index = None
            st.session_state.current_editing_time_slots = []
            st.rerun()

def render_html_import_tab():
    """渲染從 HTML 匯入課程的 UI。"""
    st.subheader("貼上HTML匯入課程")
    st.info("請從學校的課程查詢網頁，使用開發者工具 (F12) 選取包含所有課程資訊的 `<table>` 元素，然後複製其「外部 HTML」(Outer HTML)，並將其貼到下方的文字區域中。")
    
    html_paste_area = st.text_area("在此貼上課程表格的 HTML 原始碼", height=300, placeholder="<table>...</table>")
    
    if st.button("解析 HTML 並新增課程", type="primary"):
        if not html_paste_area:
            show_message("請先貼上 HTML 原始碼。", 'warning')
        else:
            with st.spinner("正在解析 HTML..."):
                # *** UPDATED CALL ***
                added_count, skipped_count = parse_html_to_courses(html_paste_area)
            if added_count > 0:
                msg = f"成功從 HTML 新增 {added_count} 門課程。"
                if skipped_count > 0:
                    msg += f" 跳過了 {skipped_count} 門重複或已存在的課程。"
                show_message(msg, 'success')
            else:
                show_message("未從提供的 HTML 中解析到任何新課程，或所有課程都已存在。", 'warning')

def render_course_list_tab():
    """使用 st.data_editor 渲染課程列表以進行互動。"""
    st.subheader("課程列表")
    
    if not st.session_state.courses:
        st.warning("目前沒有課程。請從'新增課程'或'貼上HTML匯入'分頁加入。")
        return

    df = pd.DataFrame(st.session_state.courses)
    
    df['time_slots_display'] = df['time_slots'].apply(
        lambda slots: '; '.join([f"{DAY_MAP_DISPLAY.get(s[0], s[0])}{s[1]}" + (f"({s[2]})" if s[2] else "") for s in slots]) if slots else ""
    )
    
    df.insert(0, "delete", False)

    column_config = {
        "delete": st.column_config.CheckboxColumn("刪除選取", default=False),
        "name": st.column_config.TextColumn("名稱", required=True),
        "type": st.column_config.SelectboxColumn("類型", options=["必修", "選修"], required=True),
        "class_id": "班級",
        "credits": st.column_config.NumberColumn("學分", min_value=0, format="%d"),
        "priority": st.column_config.NumberColumn("優先", min_value=1, max_value=5, format="%d"),
        "teacher": "老師", "time_slots_display": "時間/教室",
        "must_select": st.column_config.CheckboxColumn("必選", default=False),
        "temporarily_exclude": st.column_config.CheckboxColumn("排除", default=False),
        "notes": "備註", "time_slots": None,
    }
    
    column_order = [
        "delete", "name", "type", "class_id", "credits", "priority", 
        "teacher", "time_slots_display", "must_select", "temporarily_exclude", "notes"
    ]

    st.info("您可以直接在此表格中編輯大部分欄位。修改後，點擊下方的'更新課程列表'按鈕儲存變更。若要編輯上課時間，請使用下方的'編輯選取課程'功能。")
    
    edited_df = st.data_editor(
        df[column_order], column_config=column_config, use_container_width=True,
        hide_index=True, num_rows="dynamic"
    )
    
    if st.button("更新課程列表", type="primary"):
        courses_to_keep = edited_df[edited_df['delete'] == False]
        
        updated_courses = []
        for index, row in courses_to_keep.iterrows():
            original_course_data = {}
            if index < len(st.session_state.courses):
                original_course_data = st.session_state.courses[index]
            
            new_data = row.to_dict()
            new_data['time_slots'] = original_course_data.get('time_slots', [])
            del new_data['delete']
            del new_data['time_slots_display']
            updated_courses.append(new_data)
        
        st.session_state.courses = updated_courses
        show_message("課程列表已更新。", "success")
        st.rerun()

    st.write("---")
    st.subheader("編輯課程時間")
    st.caption("由於時間欄位較複雜，請在此選擇一門課進行編輯，系統將會跳轉至編輯頁面。")
    
    course_names_for_edit = [f"{i}: {c['name']} ({c['teacher']})" for i, c in enumerate(st.session_state.courses)]
    selected_course_to_edit = st.selectbox("選擇要編輯的課程", options=course_names_for_edit, index=None, placeholder="點此選擇...")

    if selected_course_to_edit:
        selected_index = int(selected_course_to_edit.split(':')[0])
        st.session_state.editing_course_index = selected_index
        st.session_state.current_editing_time_slots = st.session_state.courses[selected_index].get('time_slots', [])
        show_message("已載入課程進行編輯，請至'新增/編輯課程'分頁查看。")
        st.rerun()
        
def render_schedule_generation_tab():
    """渲染生成和顯示課表的 UI。"""
    st.subheader("生成排課方案")
    
    with st.form("generation_form"):
        sort_option = st.radio(
            "選擇排序方式:", options=['conflict_priority', 'priority_conflict'],
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

        all_schedules_data.sort(key=lambda s: (s['conflictEventsCount'], -s['totalPriority']) if sort_option == 'conflict_priority' else (-s['totalPriority'], s['conflictEventsCount']))
        
        st.session_state.generated_schedules = [s for s in all_schedules_data if s['conflictEventsCount'] == 0]
        st.session_state.conflict_schedules = [s for s in all_schedules_data if s['conflictEventsCount'] > 0]
        show_message(f"排課方案已生成。共 {len(all_schedules_data)} 個方案。", 'success')

    if st.session_state.generated_schedules or st.session_state.conflict_schedules:
        st.write("---")
        st.header("排課結果")
        
        st.subheader(f"✅ 不衝堂方案 ({len(st.session_state.generated_schedules)} 個)")
        if not st.session_state.generated_schedules:
            st.caption("無不衝堂的排課方案。")
        for i, schedule in enumerate(st.session_state.generated_schedules):
            render_single_schedule(schedule, i, is_conflict=False)

        st.subheader(f"⚠️ 有衝堂方案 ({len(st.session_state.conflict_schedules)} 個)")
        if not st.session_state.conflict_schedules:
            st.caption("目前無有衝堂方案。")
        for i, schedule in enumerate(st.session_state.conflict_schedules):
            render_single_schedule(schedule, i, is_conflict=True)

def render_single_schedule(schedule, index, is_conflict):
    """在 expander 中渲染單個課表。"""
    header = f"方案 {index + 1} (總優先度: {schedule['totalPriority']}, 總學分: {schedule['totalCredits']}"
    if is_conflict:
        header += f", 衝堂數: {schedule['conflictEventsCount']})"
    else:
        header += ")"
        
    with st.expander(header):
        st.markdown(f"**必修**: {schedule['reqCredits']} 學分, **選修**: {schedule['eleCredits']} 學分")
        
        for course in schedule['combo']:
            ts_str = '; '.join([f"{DAY_MAP_DISPLAY.get(s[0], s[0])}{s[1]}" for s in course['time_slots']])
            st.markdown(f"- **{course['name']}** ({course['type']}, {course['credits']}學分) - *{course['teacher']}* `時:{ts_str}`")

        if is_conflict and schedule['conflictsDetails']:
            st.write("---")
            st.error("**衝堂詳情:**")
            for conflict in schedule['conflictsDetails']:
                overlap_str = ', '.join([c['name'] for c in conflict['courses']])
                st.markdown(f"- **{DAY_MAP_DISPLAY[conflict['day']]} 第 {conflict['period']} 堂:** {overlap_str}")

        st.write("---")
        render_schedule_grid(schedule)

def render_schedule_grid(schedule):
    """渲染課表的視覺化網格。"""
    days = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    periods = range(1, 11)
    
    grid_df = pd.DataFrame(index=periods, columns=[DAY_MAP_DISPLAY[d] for d in days])
    grid_df = grid_df.fillna('')

    for course in schedule['combo']:
        for day, period, classroom in course.get('time_slots', []):
            if day in days:
                cell_content = f"**{course['name']}**<br><small>{course.get('teacher', '')}<br>{classroom}</small>"
                if grid_df.loc[period, DAY_MAP_DISPLAY[day]]:
                     grid_df.loc[period, DAY_MAP_DISPLAY[day]] += f"<hr><span style='color:red;'>{cell_content}</span>"
                else:
                     grid_df.loc[period, DAY_MAP_DISPLAY[day]] = cell_content

    st.markdown(grid_df.to_html(escape=False), unsafe_allow_html=True)

# --- 主應用程式 ---

def main():
    st.title("互動式排課助手")
    initialize_session_state()
    render_sidebar()

    tab1, tab2, tab3, tab4 = st.tabs([
        "課程列表", "新增/編輯課程", "貼上HTML匯入", "生成排課方案"
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
