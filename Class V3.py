import streamlit as st
from dataclasses import dataclass, asdict
from typing import List, Tuple, Dict, Any
import json
import itertools
import pandas as pd
from io import StringIO
from bs4 import BeautifulSoup # <--- 新增匯入 BeautifulSoup

# 定義 Course 類別
@dataclass
class Course:
    name: str
    type: str  # '必修' 或 '選修'
    class_id: str
    credits: int
    priority: int  # 優先順序，1最低，5最高
    time_slots: List[Tuple[str, int]]
    must_select: bool = False
    temporarily_exclude: bool = False
    teacher: str = ""  # 授課老師
    notes: str = ""  # 備註

# 保存課程到 JSON
def save_courses_to_json(courses: List[Course]) -> str:
    return json.dumps([asdict(c) for c in courses], ensure_ascii=False, indent=4)

# 從 JSON 載入課程
def load_courses_from_json(uploaded_file) -> List[Course]:
    try:
        stringio = StringIO(uploaded_file.getvalue().decode("utf-8"))
        data = json.load(stringio)
        courses = []
        for item in data:
            course = Course(
                name=item['name'],
                type=item['type'],
                class_id=item['class_id'],
                credits=item['credits'],
                priority=item.get('priority', 3), 
                time_slots=[tuple(ts) for ts in item['time_slots']],
                must_select=item.get('must_select', False), 
                temporarily_exclude=item.get('temporarily_exclude', False), 
                teacher=item.get('teacher', ""), 
                notes=item.get('notes', "") 
            )
            courses.append(course)
        return courses
    except Exception as e:
        st.error(f"從 JSON 載入課程失敗: {e}")
        return []

# --- 新增：從 HTML 解析課程的函數 ---
def parse_time_slot_string_for_html(time_str: str, current_notes: Dict[str, str]) -> List[Tuple[str, int]]:
    """
    輔助函數：解析 HTML 中的時間字串 (例如 "五 / 6,7 / B 312")
    並將教室資訊更新到 current_notes 字典中。
    """
    slots = []
    classroom_info = ""
    day_map_html = {"一": "Mon", "二": "Tue", "三": "Wed", "四": "Thu", "五": "Fri", "六": "Sat", "日": "Sun"}

    if time_str and time_str.strip() and time_str.strip() != "　": # "　" 是全形空白
        parts = [p.strip() for p in time_str.split('/')]
        if len(parts) >= 2:
            day_char = parts[0]
            day_eng = day_map_html.get(day_char, day_char) # 轉換為英文或保持原樣
            periods_str = parts[1]
            
            if len(parts) >= 3 and parts[2]:
                classroom_info = parts[2]

            for p_str in periods_str.split(','):
                try:
                    period_num = int(p_str.strip())
                    slots.append((day_eng, period_num))
                except ValueError:
                    # 忽略無法轉換為數字的節次 (例如空字串或非數字)
                    pass 
    
    if classroom_info:
        # 避免重複加入相同的教室資訊，如果時間字串被拆分為多個欄位
        existing_classrooms = current_notes.get("classroom", "")
        if classroom_info not in existing_classrooms.split('; '):
             current_notes["classroom"] = (existing_classrooms + "; " if existing_classrooms else "") + classroom_info
    return slots

def parse_courses_from_html(html_content: str) -> List[Course]:
    """
    從提供的 HTML 字串中解析課程資料。
    """
    if not html_content:
        return []

    soup = BeautifulSoup(html_content, 'html.parser')
    parsed_courses = []

    # 根據您提供的 HTML 結構，選擇器可能需要微調
    # 這裡假設課程表格是 <table border="1" width="100%" bgcolor="#FFFFFF"...>
    # 並且課程列在 <tbody> 下的 <tr>
    course_table = soup.find('table', {'border': '1', 'width': '100%', 'bgcolor': '#FFFFFF'})
    if not course_table:
        st.warning("在貼上的內容中找不到預期的課程表格結構。")
        return []
    
    table_body = course_table.find('tbody')
    if not table_body:
        st.warning("在課程表格中找不到 tbody 結構。")
        return []

    rows = table_body.find_all('tr')

    for row in rows:
        cells = row.find_all('td')
        
        # 過濾表頭或不包含足夠儲存格的列
        # 以及包含 "系別(Department)" 的標題列
        if len(cells) < 16 or (cells[0].get_text(strip=True) and "系別" in cells[0].get_text(strip=True)):
            continue

        try:
            current_notes_dict = {} # 用於收集備註

            # 年級 (cells[1]) -> notes
            grade_text = cells[1].get_text(strip=True)
            if grade_text: current_notes_dict["grade"] = f"年級: {grade_text}"

            # 科目編號 (cells[3])
            class_id_text = cells[3].get_text(strip=True)

            # 班別 (cells[6]) -> notes
            class_group_text = cells[6].get_text(strip=True)
            if class_group_text: current_notes_dict["class_group"] = f"班別: {class_group_text}"
            
            # 必選修 (cells[8])
            course_type_str = cells[8].get_text(strip=True)
            course_type = "選修" # 預設為選修
            if course_type_str == "必":
                course_type = "必修"
            
            # 學分 (cells[9])
            credits_val = 0
            try:
                credits_val = int(cells[9].get_text(strip=True))
            except ValueError:
                pass # 學分轉換失敗則保持0

            # 科目名稱 (cells[11])
            course_name_tag = cells[11].find('font', {'color': 'blue'})
            course_name_text = course_name_tag.u.get_text(strip=True) if course_name_tag and course_name_tag.u else cells[11].get_text(strip=True)
            
            # 英文科目名稱 (cells[11] 的 span title) -> notes
            eng_name_span = cells[11].find('span', title=lambda t: t and t.startswith("英文科目名稱(Course):"))
            if eng_name_span and eng_name_span.get('title'):
                current_notes_dict["eng_name"] = eng_name_span.get('title').replace("英文科目名稱(Course): ", "").strip()

            # 課程特定備註，例如全英語授課 (cells[11] 的 font color Maroon) -> notes
            maroon_note_tag = cells[11].find('font', {'color': 'Maroon'})
            if maroon_note_tag:
                current_notes_dict["course_specific_note"] = maroon_note_tag.get_text(strip=True)

            # 人數設限 (cells[12]) -> notes
            limit_text = cells[12].get_text(strip=True)
            if limit_text: current_notes_dict["limit"] = f"人數設限: {limit_text}"
            
            # 授課教師 (cells[13])
            teacher_tag = cells[13].find('a') # 老師名稱通常在 <a> 標籤內
            teacher_name_text = teacher_tag.get_text(strip=True).split('(')[0].strip() if teacher_tag else cells[13].get_text(strip=True)

            # 上課時間 / 教室 (cells[14] 和 cells[15])
            time_slots_list = []
            time_str1 = cells[14].get_text(strip=True)
            time_slots_list.extend(parse_time_slot_string_for_html(time_str1, current_notes_dict))
            
            time_str2 = cells[15].get_text(strip=True)
            time_slots_list.extend(parse_time_slot_string_for_html(time_str2, current_notes_dict))
            
            # 組合 notes
            final_notes = "; ".join(value for value in current_notes_dict.values() if value)

            # 檢查是否為實習課 (從開課序號欄位 cells[2] 判斷)
            course_seq_tag = cells[2].find('font', {'color': 'DD0080'})
            is_practical_lesson = course_seq_tag and "(實習)" in course_seq_tag.get_text(strip=True)
            
            final_course_name = course_name_text
            if is_practical_lesson and credits_val == 0:
                if "(實習課)" not in final_course_name and "(實習)" not in final_course_name:
                    final_course_name += "(實習課)"

            if final_course_name and class_id_text: # 確保有課程名稱和編號
                course_obj = Course(
                    name=final_course_name,
                    type=course_type,
                    class_id=class_id_text,
                    credits=credits_val,
                    priority=3, # 預設優先級，使用者後續可修改
                    time_slots=time_slots_list,
                    must_select=False, # 預設
                    temporarily_exclude=False, # 預設
                    teacher=teacher_name_text,
                    notes=final_notes
                )
                parsed_courses.append(course_obj)

        except Exception as e:
            st.warning(f"處理某一課程列時發生錯誤: {e}。該列資料: {' | '.join(c.get_text(strip=True) for c in cells[:15])}...") # 顯示部分資料以供除錯
            continue # 繼續處理下一列

    return parsed_courses
# --- HTML 解析函數結束 ---


# 排課算法 (與先前版本相同，此處省略以節省空間，實際使用時請保留)
def generate_schedules(all_courses: List[Course], max_schedules=1000):
    schedules: Dict[int, List[Any]] = {} 
    grouped_courses: Dict[str, List[Course]] = {}
    must_select_names = set(
        c.name for c in all_courses if c.must_select and not c.temporarily_exclude
    )
    available_courses = [c for c in all_courses if not c.temporarily_exclude]
    for name in must_select_names:
        if not any(c.name == name for c in available_courses):
            st.error(f"必選課程 '{name}' 沒有可選的時間段或已被暫時排除。")
            return []
    for c in available_courses:
        if c.name not in grouped_courses:
            grouped_courses[c.name] = []
        grouped_courses[c.name].append(c)
    for name, group in grouped_courses.items():
        grouped_courses[name] = sorted(group, key=lambda c: (not c.must_select, -c.priority))
    course_names = list(grouped_courses.keys())
    if not course_names:
        st.info("沒有可供排課的課程 (可能所有課程都被暫時排除了)。")
        return []
    course_options = [grouped_courses[n] for n in course_names]
    all_combinations = itertools.product(*course_options)
    count_generated = 0  
    for combo_tuple in all_combinations: 
        combo: List[Course] = list(combo_tuple) 
        if count_generated >= max_schedules:
            st.warning(f"已達到最大排課方案數量 ({max_schedules})，停止生成更多方案。")
            break
        current_combo_course_names = {c.name for c in combo}
        if not must_select_names.issubset(current_combo_course_names):
            continue
        time_slot_map: Dict[Tuple[str, int], List[Course]] = {}
        for c in combo:
            for day, period in c.time_slots:
                key = (day, period)
                if key not in time_slot_map:
                    time_slot_map[key] = []
                time_slot_map[key].append(c)
        conflicts_details: List[Tuple[str, int, List[Course]]] = [] 
        conflict_events_count = 0  
        for (day, period), course_list_in_slot in time_slot_map.items():
            if len(course_list_in_slot) > 1:
                conflicts_details.append((day, period, course_list_in_slot))
                conflict_events_count += 1 
        total_credits = sum(c.credits for c in combo)
        req_credits = sum(c.credits for c in combo if c.type == '必修')
        ele_credits = sum(c.credits for c in combo if c.type == '選修')
        total_priority = sum(c.priority for c in combo)
        schedules.setdefault(conflict_events_count, []).append(
            (combo, total_priority, total_credits, req_credits, ele_credits, conflicts_details if conflict_events_count > 0 else None, conflict_events_count)
        )
        count_generated += 1
    sorted_conflict_counts = sorted(schedules.keys())
    all_schedules_list: List[Any] = [] 
    for ccount in sorted_conflict_counts:
        schedules[ccount].sort(key=lambda x: (-x[1], -x[2])) 
        all_schedules_list.extend(schedules[ccount])
    return all_schedules_list

# 顯示排課格子函數 (與先前版本相同，此處省略以節省空間)
def display_schedule_grid(combo: List[Course], conflicts: List[Tuple[str, int, List[Course]]]=None):
    days = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    periods = list(range(1, 11)) 
    schedule_df = pd.DataFrame("", index=periods, columns=days)
    for course in combo:
        for day, period_val in course.time_slots: 
            if day in days and 1 <= period_val <= 10:
                cell_content = f"{course.name}"
                if course.teacher:
                    cell_content += f"({course.teacher})"
                if schedule_df.at[period_val, day] == "":
                    schedule_df.at[period_val, day] = cell_content
                else:
                    if "衝堂" not in schedule_df.at[period_val, day]:
                         schedule_df.at[period_val, day] += f", {cell_content} <font color='red'>(衝堂)</font>"
                    else: 
                         schedule_df.at[period_val, day] += f", {cell_content}"
    schedule_df.replace("", "-", inplace=True)
    html_table = "<table><thead><tr><th>時段</th>"
    for day in days:
        html_table += f"<th>{day}</th>"
    html_table += "</tr></thead><tbody>"
    for period_val in periods: 
        html_table += f"<tr><td>{period_val}</td>"
        for day in days:
            cell_value = schedule_df.at[period_val, day]
            if "<font color='red'>(衝堂)</font>" in cell_value:
                html_table += f"<td style='background-color:#fff0f0;'>{cell_value}</td>"
            else:
                html_table += f"<td>{cell_value}</td>"
        html_table += "</tr>"
    html_table += "</tbody></table>"
    st.markdown(html_table, unsafe_allow_html=True)
    if conflicts:
        st.write("**衝堂詳情:**")
        for day, period_val, overlapping_courses in conflicts: 
            overlap_str = ', '.join(
                [f"{c.name}({c.teacher})" if c.teacher else f"{c.name}" for c in overlapping_courses]
            )
            st.write(f"- {day} 第 {period_val} 堂: {overlap_str}")

def main():
    st.set_page_config(page_title="排課助手", layout="wide")
    st.title("排課助手")

    # 初始化 session state (與先前版本相同，此處省略部分以節省空間)
    if 'courses' not in st.session_state:
        st.session_state.courses = []
    if 'generated_schedules' not in st.session_state:
        st.session_state.generated_schedules = []
    if 'conflict_schedules' not in st.session_state:
        st.session_state.conflict_schedules = []
    
    course_types = ['必修', '選修']
    priority_options = [1, 2, 3, 4, 5] 

    for course_type in course_types:
        prefix = f"add_form_{course_type}"
        if f'{prefix}_name' not in st.session_state: st.session_state[f'{prefix}_name'] = ""
        if f'{prefix}_class_id' not in st.session_state: st.session_state[f'{prefix}_class_id'] = ""
        if f'{prefix}_credits' not in st.session_state: st.session_state[f'{prefix}_credits'] = 1
        if f'{prefix}_priority' not in st.session_state: st.session_state[f'{prefix}_priority'] = 3 
        if f'{prefix}_teacher' not in st.session_state: st.session_state[f'{prefix}_teacher'] = ""
        if f'{prefix}_notes' not in st.session_state: st.session_state[f'{prefix}_notes'] = ""
        if f'{prefix}_must_select' not in st.session_state: st.session_state[f'{prefix}_must_select'] = False
        if f'{prefix}_temporarily_exclude' not in st.session_state: st.session_state[f'{prefix}_temporarily_exclude'] = False
        if f'{prefix}_time_slots' not in st.session_state: st.session_state[f'{prefix}_time_slots'] = []
        if f'{prefix}_priority_index' not in st.session_state:
            try:
                st.session_state[f'{prefix}_priority_index'] = priority_options.index(st.session_state[f'{prefix}_priority'])
            except ValueError: 
                st.session_state[f'{prefix}_priority_index'] = priority_options.index(priority_options[0]) 
                st.session_state[f'{prefix}_priority'] = priority_options[0]

    # 側邊欄操作 (與先前版本相同)
    st.sidebar.header("操作選單")
    uploaded_file = st.sidebar.file_uploader("載入課程資料 (JSON)", type=["json"], key="json_uploader")
    if uploaded_file:
        loaded_courses = load_courses_from_json(uploaded_file)
        if loaded_courses:
            st.session_state.courses = loaded_courses
            st.sidebar.success(f"成功載入 {len(st.session_state.courses)} 門課程。")
            for ct in course_types: # 清空表單
                prefix_clear = f"add_form_{ct}"
                st.session_state[f'{prefix_clear}_name'] = ""
                st.session_state[f'{prefix_clear}_class_id'] = ""
                # ... (其他表單欄位重設邏輯)
                st.session_state[f'{prefix_clear}_time_slots'] = []


    if st.sidebar.button("儲存課程資料 (JSON)", key="save_json_btn"):
        if not st.session_state.courses:
            st.sidebar.warning("目前沒有課程可以儲存。")
        else:
            json_data = save_courses_to_json(st.session_state.courses)
            st.sidebar.download_button(
                label="下載課程資料",
                data=json_data,
                file_name="courses.json",
                mime="application/json",
                key="download_json_btn"
            )
            st.sidebar.success("課程資料已準備好下載。")

    # --- 修改：新增 "貼上HTML匯入課程" 分頁 ---
    tab_titles = ["新增課程", "貼上HTML匯入課程", "課程列表", "生成排課方案"]
    tabs = st.tabs(tab_titles)

    # 新增課程分頁 (與先前版本相同，此處省略部分以節省空間)
    with tabs[0]:
        st.subheader("新增課程")
        # ... (先前的新增課程表單邏輯) ...
        for course_type in course_types:
            prefix = f"add_form_{course_type}"
            with st.expander(f"新增 {course_type} 課程", expanded=True):
                def _create_on_change_handler(p, k_suffix, widget_k):
                    def _handler():
                        st.session_state[f"{p}_{k_suffix}"] = st.session_state[widget_k]
                    return _handler
                def _create_priority_on_change_handler(p, opts, widget_k):
                    def _handler():
                        selected_idx = st.session_state[widget_k]
                        st.session_state[f"{p}_priority_index"] = selected_idx
                        st.session_state[f"{p}_priority"] = opts[selected_idx]
                    return _handler

                name_widget_key = f"widget_input_{prefix}_name"
                st.text_input("課程名稱", value=st.session_state[f'{prefix}_name'], key=name_widget_key, on_change=_create_on_change_handler(prefix, 'name', name_widget_key))
                class_id_widget_key = f"widget_input_{prefix}_class_id"
                st.text_input("班級", value=st.session_state[f'{prefix}_class_id'], key=class_id_widget_key,on_change=_create_on_change_handler(prefix, 'class_id', class_id_widget_key))
                credits_widget_key = f"widget_input_{prefix}_credits"
                st.number_input("學分數", min_value=0, step=1, value=st.session_state[f'{prefix}_credits'], key=credits_widget_key,on_change=_create_on_change_handler(prefix, 'credits', credits_widget_key))
                priority_widget_key = f"widget_input_{prefix}_priority_selectbox"
                st.selectbox("優先順序", options=priority_options, index=st.session_state[f'{prefix}_priority_index'], key=priority_widget_key,on_change=_create_priority_on_change_handler(prefix, priority_options, priority_widget_key))
                teacher_widget_key = f"widget_input_{prefix}_teacher"
                st.text_input("授課老師", value=st.session_state[f'{prefix}_teacher'], key=teacher_widget_key,on_change=_create_on_change_handler(prefix, 'teacher', teacher_widget_key))
                notes_widget_key = f"widget_input_{prefix}_notes"
                st.text_input("備註", value=st.session_state[f'{prefix}_notes'], key=notes_widget_key,on_change=_create_on_change_handler(prefix, 'notes', notes_widget_key))
                must_select_widget_key = f"widget_input_{prefix}_must_select_checkbox"
                st.checkbox("必選", value=st.session_state[f'{prefix}_must_select'], key=must_select_widget_key,on_change=_create_on_change_handler(prefix, 'must_select', must_select_widget_key))
                temporarily_exclude_widget_key = f"widget_input_{prefix}_temporarily_exclude_checkbox"
                st.checkbox("暫時排除", value=st.session_state[f'{prefix}_temporarily_exclude'], key=temporarily_exclude_widget_key,on_change=_create_on_change_handler(prefix, 'temporarily_exclude', temporarily_exclude_widget_key))

                st.markdown("### 上課時間")
                col1, col2, col3 = st.columns([2, 2, 1])
                day_options = ["Mon", "Tue", "Wed", "Thu", "Fri"]
                temp_day = col1.selectbox("星期", options=day_options, key=f"temp_{prefix}_day_selector_manual") 
                temp_period = col2.number_input("堂課", min_value=1, max_value=10, step=1, key=f"temp_{prefix}_period_selector_manual")
                if col3.button("添加時間", key=f"add_time_btn_{prefix}_manual"):
                    st.session_state[f'{prefix}_time_slots'].append((temp_day, temp_period))
                    st.success(f"已添加時間: {temp_day} {temp_period}")
                    st.rerun()
                current_time_slots = st.session_state[f'{prefix}_time_slots']
                if current_time_slots:
                    st.write("已添加的上課時間:")
                    delete_indices = []
                    for idx, (d, p) in enumerate(current_time_slots):
                        if st.checkbox(f"刪除 {d} {p}", key=f"del_timeslot_cb_{prefix}_{idx}_manual"): 
                            delete_indices.append(idx)
                    if st.button("刪除選定時間槽", key=f"del_time_btn_{prefix}_manual"):
                        for idx in sorted(delete_indices, reverse=True):
                            del st.session_state[f'{prefix}_time_slots'][idx]
                        st.success("已刪除選定的時間槽。")
                        st.rerun()
                with st.form(key=f"final_add_course_form_{course_type}_manual"):
                    st.markdown(f"**{course_type} 課程預覽:**")
                    st.caption(f"名稱: {st.session_state[f'{prefix}_name']}") # ... (其他預覽欄位)
                    submit_course_button = st.form_submit_button("新增課程到列表")
                    if submit_course_button:
                        name_val = st.session_state[f'{prefix}_name']
                        class_id_val = st.session_state[f'{prefix}_class_id']
                        time_slots_val = st.session_state[f'{prefix}_time_slots']
                        if not name_val or not class_id_val or not time_slots_val:
                            st.error("請確保課程名稱、班級都已填寫，並已添加上課時間。")
                        else: # ... (新增課程到 st.session_state.courses 的邏輯)
                            credits_val = st.session_state[f'{prefix}_credits']
                            priority_val = st.session_state[f'{prefix}_priority']
                            teacher_val = st.session_state[f'{prefix}_teacher']
                            notes_val = st.session_state[f'{prefix}_notes']
                            must_select_val = st.session_state[f'{prefix}_must_select']
                            temporarily_exclude_val = st.session_state[f'{prefix}_temporarily_exclude']
                            
                            duplicate = any(c.name == name_val and c.class_id == class_id_val for c in st.session_state.courses)
                            if duplicate:
                                st.error(f"課程 '{name_val}' (班級 {class_id_val}) 已存在。")
                            else:
                                new_course = Course(
                                    name=name_val, type=course_type, class_id=class_id_val,
                                    credits=int(credits_val), priority=int(priority_val),
                                    time_slots=list(time_slots_val), 
                                    must_select=must_select_val,
                                    temporarily_exclude=temporarily_exclude_val,
                                    teacher=teacher_val, notes=notes_val
                                )
                                st.session_state.courses.append(new_course)
                                st.success(f"課程 '{name_val}' 已新增。")
                                # 清空表單
                                st.session_state[f'{prefix}_name'] = ""
                                st.session_state[f'{prefix}_class_id'] = ""
                                st.session_state[f'{prefix}_credits'] = 1
                                st.session_state[f'{prefix}_priority'] = 3
                                st.session_state[f'{prefix}_priority_index'] = priority_options.index(3) if 3 in priority_options else 0
                                st.session_state[f'{prefix}_teacher'] = ""
                                st.session_state[f'{prefix}_notes'] = ""
                                st.session_state[f'{prefix}_must_select'] = False
                                st.session_state[f'{prefix}_temporarily_exclude'] = False
                                st.session_state[f'{prefix}_time_slots'] = []
                                st.rerun()
        st.markdown("---")


    # --- 新增的 "貼上HTML匯入課程" 分頁邏輯 ---
    with tabs[1]:
        st.subheader("貼上HTML匯入課程")
        st.markdown("""
        請從學校的課程查詢網頁，使用開發者工具 (F12) 選取包含所有課程資訊的 `<table>` 元素，
        然後複製其「外部 HTML」(Outer HTML)，並將其貼到下方的文字區域中。
        """)
        
        html_input = st.text_area("貼上課程表格的 HTML 原始碼", height=300, key="html_paste_area")
        
        if st.button("解析 HTML 並新增課程", key="parse_html_btn"):
            if html_input:
                with st.spinner("正在解析 HTML 並匯入課程..."):
                    newly_parsed_courses = parse_courses_from_html(html_input)
                
                if newly_parsed_courses:
                    added_count = 0
                    skipped_count = 0
                    for new_course in newly_parsed_courses:
                        # 檢查是否重複 (基於課程名稱和班級ID)
                        is_duplicate = any(
                            existing_course.name == new_course.name and existing_course.class_id == new_course.class_id
                            for existing_course in st.session_state.courses
                        )
                        if not is_duplicate:
                            st.session_state.courses.append(new_course)
                            added_count += 1
                        else:
                            skipped_count += 1
                    
                    st.success(f"成功從 HTML 新增 {added_count} 門課程。")
                    if skipped_count > 0:
                        st.info(f"跳過了 {skipped_count} 門重複的課程。")
                    st.rerun() # 更新課程列表顯示
                else:
                    st.warning("未從提供的 HTML 中解析到任何課程，或解析過程中發生錯誤。請檢查 HTML 內容和格式。")
            else:
                st.warning("請先貼上 HTML 原始碼。")

    # 課程列表分頁 (tabs[2]，原 tabs[1])
    with tabs[2]:
        st.subheader("課程列表")
        # ... (先前的課程列表邏輯，注意 st.data_editor 的 key 可能需要更新以避免衝突) ...
        st.markdown("""
        - **必選**: 在排課時，有勾選此項的課程（無論必修或選修）會被強制排入課表（除非被暫時排除）。
        - **暫時排除**: 暫時不將該課程納入生成排課方案的考慮範圍。
        - **編輯與刪除**:
            - 雙擊儲存格即可編輯內容。
            - 點擊任一課程左側的勾選框選取該列，表格右上角會出現垃圾桶圖示以刪除選取的課程。
            - 修改後請點擊下方的「更新課程列表」按鈕以保存變更。
        """)
        if st.session_state.courses:
            course_data_for_editor = []
            for idx, c_obj in enumerate(st.session_state.courses):
                course_data_for_editor.append({
                    'id': idx, '名稱': c_obj.name, '類型': c_obj.type, '班級': c_obj.class_id,
                    '學分': c_obj.credits, '優先順序': c_obj.priority, '授課老師': c_obj.teacher,
                    '備註': c_obj.notes,
                    '時間槽': '; '.join([f"{d} {p}" for d, p in c_obj.time_slots]),
                    '必選': c_obj.must_select, '暫時排除': c_obj.temporarily_exclude 
                })
            edited_df_data = st.data_editor( 
                pd.DataFrame(course_data_for_editor), num_rows="dynamic", use_container_width=True,
                key='course_list_editor_widget_main', # 更新 key
                hide_index=True,
                column_config={
                    "id": None, "類型": st.column_config.SelectboxColumn(options=["必修", "選修"], required=True),
                    "優先順序": st.column_config.SelectboxColumn(options=priority_options, required=True),
                    "必選": st.column_config.CheckboxColumn(default=False),
                    "暫時排除": st.column_config.CheckboxColumn(default=False),
                    "時間槽": st.column_config.TextColumn(help="格式: Mon 1; Tue 3 (用分號分隔多個時段)", required=True)
                }
            )
            if st.button("更新課程列表", key="update_course_list_btn_main"): # 更新 key
                # ... (更新課程列表的邏輯)
                updated_courses_from_editor = []
                valid_data = True
                day_options_check = ["Mon", "Tue", "Wed", "Thu", "Fri"] 
                for _, row in edited_df_data.iterrows(): 
                    if pd.isna(row['名稱']) or str(row['名稱']).strip() == "" or \
                       pd.isna(row['班級']) or str(row['班級']).strip() == "" or \
                       pd.isna(row['時間槽']) or str(row['時間槽']).strip() == "":
                        st.error(f"錯誤：課程 '{row['名稱'] if pd.notna(row['名稱']) else '未命名課程'}' 的「名稱」、「班級」或「時間槽」為空。")
                        valid_data = False; break
                    time_slots = []
                    try:
                        for ts_str in str(row['時間槽']).split(';'):
                            ts_str = ts_str.strip()
                            if not ts_str: continue 
                            parts = ts_str.split()
                            if len(parts) != 2: raise ValueError(f"時間槽格式錯誤: '{ts_str}'")
                            day, period_str = parts[0], parts[1]
                            if day not in day_options_check: raise ValueError(f"星期格式錯誤: '{day}'")
                            period = int(period_str)
                            if not (1 <= period <= 10): raise ValueError(f"堂課數字錯誤: '{period_str}'")
                            time_slots.append((day, period))
                    except Exception as e:
                        st.error(f"處理課程 '{row['名稱']}' 的時間槽 ('{row['時間槽']}') 時出錯: {e}")
                        valid_data = False; break
                    if not time_slots and str(row['時間槽']).strip() != "": 
                         st.error(f"課程 '{row['名稱']}' 的時間槽 '{row['時間槽']}' 解析後為空或格式不正確。")
                         valid_data = False; break
                    if not time_slots and str(row['時間槽']).strip() == "":
                         st.error(f"課程 '{row['名稱']}' 必須提供至少一個有效的時間槽。")
                         valid_data = False; break
                    updated_courses_from_editor.append(Course(
                        name=str(row['名稱']), type=str(row['類型']), class_id=str(row['班級']),
                        credits=int(row['學分']), priority=int(row['優先順序']),
                        time_slots=time_slots, must_select=bool(row['必選']),
                        temporarily_exclude=bool(row['暫時排除']),
                        teacher=str(row['授課老師']) if pd.notna(row['授課老師']) else "",
                        notes=str(row['備註']) if pd.notna(row['備註']) else ""
                    ))
                if valid_data:
                    st.session_state.courses = updated_courses_from_editor
                    st.success("課程列表已更新。"); st.rerun()
        else:
            st.info("目前沒有課程。")


    # 生成排課方案分頁 (tabs[3]，原 tabs[2])
    with tabs[3]:
        st.subheader("生成排課方案")
        # ... (先前的生成排課方案邏輯) ...
        st.markdown("---"); st.header("排課方案排序")
        if "schedule_sort_option" not in st.session_state:
            st.session_state.schedule_sort_option = "先衝堂數量少到多，接著優先順序總和多到少"
        sort_option_choices = [
            "先衝堂數量少到多，接著優先順序總和多到少",
            "先優先順序總和多到少，接著衝堂數量少到多"
        ]
        try: current_sort_option_index = sort_option_choices.index(st.session_state.schedule_sort_option)
        except ValueError: current_sort_option_index = 0; st.session_state.schedule_sort_option = sort_option_choices[0]
        def update_sort_option_main():
            st.session_state.schedule_sort_option = st.session_state.schedule_sort_option_radio_key_main
        st.radio("選擇排序方式",options=sort_option_choices,index=current_sort_option_index,key="schedule_sort_option_radio_key_main",on_change=update_sort_option_main)
        st.markdown("---")
        if st.button("生成排課方案", key="generate_schedules_btn_main_tab"): 
            if not st.session_state.courses: st.warning("目前沒有課程可以排課。")
            else:
                with st.spinner("正在生成排課方案，請稍候..."): all_schedules_data = generate_schedules(st.session_state.courses) 
                if not all_schedules_data:
                    st.error("無法生成任何排課方案。"); st.session_state.generated_schedules = []; st.session_state.conflict_schedules = []
                else:
                    def sort_key_func(s_data):
                        conflict_c, total_p = s_data[6], s_data[1]
                        return (conflict_c, -total_p) if st.session_state.schedule_sort_option == sort_option_choices[0] else (-total_p, conflict_c)
                    all_schedules_data.sort(key=sort_key_func)
                    st.session_state.generated_schedules = [s for s in all_schedules_data if s[6] == 0]
                    st.session_state.conflict_schedules = [s for s in all_schedules_data if s[6] > 0]
                    st.success(f"排課方案已生成。共 {len(all_schedules_data)} 個方案。")
        if st.session_state.generated_schedules or st.session_state.conflict_schedules:
            st.markdown("### 不衝堂方案")
            if st.session_state.generated_schedules:
                for i, (combo, tp, tc, rc, ec, cf_details, ccount) in enumerate(st.session_state.generated_schedules, start=1):
                    with st.expander(f"方案 {i} (優:{tp}, 學分:{tc})"):
                        st.write(f"必修:{rc}, 選修:{ec}")
                        for c_item in combo: st.write(f"- **{c_item.name}** ({c_item.type}) 班:{c_item.class_id}, {c_item.credits}學分, 優:{c_item.priority}. 師:{c_item.teacher or ''} 註:{c_item.notes or ''} 時:{'; '.join([f'{d} {p}' for d,p in c_item.time_slots])}")
                        display_schedule_grid(combo, conflicts=None) 
            else: st.write("無不衝堂的排課方案。")
            st.markdown("### 有衝堂方案")
            if st.session_state.conflict_schedules:
                for i, (combo, tp, tc, rc, ec, cf_details, ccount) in enumerate(st.session_state.conflict_schedules, start=1):
                    with st.expander(f"方案 {i} (衝:{ccount}, 優:{tp}, 學分:{tc})"):
                        st.write(f"必修:{rc}, 選修:{ec}")
                        for c_item in combo: st.write(f"- **{c_item.name}** ({c_item.type}) 班:{c_item.class_id}, {c_item.credits}學分, 優:{c_item.priority}. 師:{c_item.teacher or ''} 註:{c_item.notes or ''} 時:{'; '.join([f'{d} {p}' for d,p in c_item.time_slots])}")
                        display_schedule_grid(combo, conflicts=cf_details)
            else: st.write("目前無有衝堂方案。")
        else: st.info("請先點擊「生成排課方案」按鈕。")

if __name__ == "__main__":
    main()
