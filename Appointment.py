import streamlit as st
import sqlite3
from datetime import datetime, date, time, timedelta
import pandas as pd
import uuid
from typing import List, Tuple
import calendar as cal
import html

DB_PATH = 'barber_shop.db'

# -----------------------------
# Database Helpers
# -----------------------------

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS barbers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS services (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            duration_min INTEGER NOT NULL,
            price REAL NOT NULL
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS appointments (
            id TEXT PRIMARY KEY,
            barber_id TEXT NOT NULL,
            service_id TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            customer_phone TEXT NOT NULL,
            appt_date TEXT NOT NULL, -- YYYY-MM-DD
            start_time TEXT NOT NULL, -- HH:MM
            end_time TEXT NOT NULL,   -- HH:MM
            notes TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (barber_id) REFERENCES barbers(id),
            FOREIGN KEY (service_id) REFERENCES services(id)
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS waitlist (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            notes TEXT,
            requested_date TEXT,
            created_at TEXT NOT NULL
        );
        """
    )

    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS barber_unavailability (
            id TEXT PRIMARY KEY,
            barber_id TEXT NOT NULL,
            date TEXT NOT NULL, -- YYYY-MM-DD
            start_time TEXT,    -- HH:MM, nullable (if full day)
            end_time TEXT,      -- HH:MM, nullable (if full day)
            reason TEXT
        );
        '''
    )

    # Seed basic data if empty
    cur.execute("SELECT COUNT(*) FROM barbers")
    if cur.fetchone()[0] == 0:
        barbers = [(str(uuid.uuid4()), n) for n in ["Alex", "Sam", "Jordan"]]
        cur.executemany("INSERT INTO barbers (id, name) VALUES (?, ?)", barbers)

    cur.execute("SELECT COUNT(*) FROM services")
    if cur.fetchone()[0] == 0:
        services = [
            (str(uuid.uuid4()), "Men's Haircut", 30, 100.0),
            (str(uuid.uuid4()), "Kids' Haircut (under 15)", 25, 75.0),
            (str(uuid.uuid4()), "Seniors' Cut", 25, 75.0),
            (str(uuid.uuid4()), "Beard Trim", 20, 50.0),
            (str(uuid.uuid4()), "Shave Normal", 15, 25.0),
            (str(uuid.uuid4()), "Hair color / Dry", 30, 25.0),
            (str(uuid.uuid4()), "Haircut + hair color/Dry", 45, 125.0),
            (str(uuid.uuid4()), "Haircut + Beard Trim", 45, 150.0),
            (str(uuid.uuid4()), "Haircut + Shave + hair color/Dry", 60, 175.0),
        ]
        cur.executemany(
            "INSERT INTO services (id, name, duration_min, price) VALUES (?, ?, ?, ?)",
            services,
        )

    conn.commit()
    conn.close()


def fetch_df(query: str, params: Tuple = ()):  
    conn = get_conn()
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def get_barbers():
    return fetch_df("SELECT id, name FROM barbers ORDER BY name")


def get_services():
    return fetch_df("SELECT id, name, duration_min, price FROM services ORDER BY name")


def get_appointments_for_barber(barber_id: str, on_date: date):
    return fetch_df(
        """
        SELECT a.id, a.appt_date, a.start_time, a.end_time, s.name as service, c.name as barber, a.customer_name, a.customer_phone, a.notes
        FROM appointments a
        JOIN services s ON s.id=a.service_id
        JOIN barbers c ON c.id=a.barber_id
        WHERE a.barber_id=? AND a.appt_date=?
        ORDER BY a.start_time
        """,
        (barber_id, on_date.isoformat()),
    )


def create_appointment(barber_id: str, service_id: str, customer_name: str, customer_phone: str,
                        appt_date: date, start_time: time, notes: str="") -> str:
    # Compute end time from service duration
    services = get_services()
    duration = int(services.loc[services['id'] == service_id, 'duration_min'].iloc[0])
    end_dt = datetime.combine(appt_date, start_time) + timedelta(minutes=duration)
    end_time = end_dt.time()

    # Check conflict
    if has_conflict(barber_id, appt_date, start_time, end_time):
        raise ValueError("This time slot is no longer available. Please pick another.")

    appt_id = str(uuid.uuid4())
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO appointments (id, barber_id, service_id, customer_name, customer_phone, appt_date, start_time, end_time, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            appt_id,
            barber_id,
            service_id,
            customer_name.strip(),
            customer_phone.strip(),
            appt_date.isoformat(),
            start_time.strftime('%H:%M'),
            end_time.strftime('%H:%M'),
            notes.strip(),
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    conn.close()
    return appt_id


def delete_appointment(appt_id: str):
    conn = get_conn()
    conn.execute("DELETE FROM appointments WHERE id=?", (appt_id,))
    conn.commit()
    conn.close()


def has_conflict(barber_id: str, appt_date: date, start: time, end: time) -> bool:
    df = fetch_df(
        """
        SELECT start_time, end_time FROM appointments
        WHERE barber_id=? AND appt_date=?
        """,
        (barber_id, appt_date.isoformat()),
    )
    start_dt = datetime.combine(appt_date, start)
    end_dt = datetime.combine(appt_date, end)
    for _, row in df.iterrows():
        row_start = datetime.combine(appt_date, datetime.strptime(row['start_time'], '%H:%M').time())
        row_end = datetime.combine(appt_date, datetime.strptime(row['end_time'], '%H:%M').time())
        # Overlap check
        if not (end_dt <= row_start or start_dt >= row_end):
            return True
    return False


def get_barber_unavailability(barber_id: str, d: date):
    return fetch_df(
        '''SELECT * FROM barber_unavailability WHERE barber_id=? AND date=?''',
        (barber_id, d.isoformat())
    )


def is_barber_unavailable(barber_id: str, d: date, start: time, end: time) -> bool:
    df = get_barber_unavailability(barber_id, d)
    for _, row in df.iterrows():
        if row['start_time'] is None or row['end_time'] is None:
            # Full day unavailable
            return True
        unav_start = datetime.strptime(row['start_time'], '%H:%M').time()
        unav_end = datetime.strptime(row['end_time'], '%H:%M').time()
        # Overlap check
        if not (end <= unav_start or start >= unav_end):
            return True
    return False


# -----------------------------
# Scheduling Logic
# -----------------------------

WORKING_HOURS = {
    'Mon': (time(8, 30), time(20, 30)),
    'Tue': None,  # Tuesday closed
    'Wed': (time(8, 30), time(20, 30)),
    'Thu': (time(8, 30), time(20, 30)),
    'Fri': (time(8, 30), time(20, 30)),
    'Sat': (time(8, 30), time(18, 0)),   # Saturday till 18:00
    'Sun': (time(8, 30), time(15, 0)),   # Sunday till 15:00
}

SLOT_INTERVAL_MIN = 60  # 1 hour slots


def weekday_key(d: date) -> str:
    return d.strftime('%a')  # Mon/Tue/...


def list_time_slots(d: date) -> List[time]:
    wk = weekday_key(d)
    if wk not in WORKING_HOURS or WORKING_HOURS[wk] is None:
        return []
    start, end = WORKING_HOURS[wk]
    slots = []
    cur_dt = datetime.combine(d, start)
    end_dt = datetime.combine(d, end)
    lunch_start = datetime.combine(d, time(12, 30))
    lunch_end = datetime.combine(d, time(13, 30))
    break_start = datetime.combine(d, time(17, 30))
    break_end = datetime.combine(d, time(18, 0))
    while cur_dt <= end_dt - timedelta(minutes=SLOT_INTERVAL_MIN):
        # Skip lunch and evening break
        if (lunch_start <= cur_dt < lunch_end) or (break_start <= cur_dt < break_end):
            cur_dt += timedelta(minutes=SLOT_INTERVAL_MIN)
            continue
        slots.append(cur_dt.time())
        cur_dt += timedelta(minutes=SLOT_INTERVAL_MIN)
    return slots


def available_start_times(barber_id: str, service_id: str, d: date) -> List[time]:
    # If the service_id is None, just use the first available service for slot calculation
    services = get_services()
    if service_id is None or service_id not in list(services['id']):
        if not services.empty:
            service_id = services.iloc[0]['id']
        else:
            return []
    dur = int(services.loc[services['id'] == service_id, 'duration_min'].iloc[0])
    slots = list_time_slots(d)
    free = []
    for s in slots:
        end_dt = datetime.combine(d, s) + timedelta(minutes=dur)
        if WORKING_HOURS.get(weekday_key(d)) is None:
            continue
        _, end_of_day = WORKING_HOURS[weekday_key(d)]
        if end_dt.time() > end_of_day:
            continue
        # Exclude if barber is unavailable
        if is_barber_unavailable(barber_id, d, s, end_dt.time()):
            continue
        if not has_conflict(barber_id, d, s, end_dt.time()):
            free.append(s)
    return free


# -----------------------------
# Calendar Helpers
# -----------------------------

def ensure_session_defaults():
    if 'book_date' not in st.session_state:
        st.session_state['book_date'] = date.today()
    if 'cal_year' not in st.session_state or 'cal_month' not in st.session_state:
        today = date.today()
        st.session_state['cal_year'] = today.year
        st.session_state['cal_month'] = today.month


def month_label(y: int, m: int) -> str:
    return f"{cal.month_name[m]} {y}"


def move_month(delta: int):
    y = st.session_state['cal_year']
    m = st.session_state['cal_month'] + delta
    if m < 1:
        m = 12
        y -= 1
    elif m > 12:
        m = 1
        y += 1
    st.session_state['cal_year'] = y
    st.session_state['cal_month'] = m


def is_mobile():
    ua = st.session_state.get('user_agent', None)
    if ua is None:
        try:
            ua = st.query_params.get('ua', None)
        except Exception:
            ua = None
    if ua is None:
        try:
            import os
            ua = os.environ.get('HTTP_USER_AGENT', None)
        except Exception:
            ua = None
    if ua:
        ua = ua.lower()
        return any(x in ua for x in ['iphone', 'android', 'mobile', 'ipad'])
    return False


def render_month_grid(barber_id: str, service_id: str):
    y, m = st.session_state['cal_year'], st.session_state['cal_month']
    month_cal = cal.Calendar(firstweekday=0).monthdatescalendar(y, m)
    st.markdown(f"### {month_label(y, m)}")
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    today = date.today()
    any_enabled = False
    if is_mobile():
        # Render as HTML table for mobile
        table_html = '<div class="calendar-wrapper"><table style="width:100%; min-width:420px;"><thead><tr>'
        for w in days:
            table_html += f'<th>{w}</th>'
        table_html += '</tr></thead><tbody>'
        for week in month_cal:
            table_html += '<tr>'
            for i, d in enumerate(week):
                is_current_month = (d.month == m)
                times = available_start_times(barber_id, service_id, d) if is_current_month else []
                label = f"{d.day}"
                disabled = (len(times) == 0) or (d < today) or (not is_current_month)
                cell_class = "calendar-cell disabled" if disabled else "calendar-cell"
                btn = ''
                if is_current_month and not disabled:
                    any_enabled = True
                    btn = f'<button onclick="window.location.search=window.location.search+`&pick={d.isoformat()}`" class="calendar-btn">{label}</button>'
                else:
                    btn = f'<div class="{cell_class}">{label}</div>'
                table_html += f'<td style="padding:0;">{btn}</td>'
            table_html += '</tr>'
        table_html += '</tbody></table></div>'
        st.markdown(table_html, unsafe_allow_html=True)
        # Handle pick from query param
        pick = st.query_params.get('pick', None)
        if pick:
            try:
                picked_date = datetime.strptime(pick, '%Y-%m-%d').date()
                st.session_state['book_date'] = picked_date
                st.session_state['scroll_to_times'] = True
                # Remove pick param from URL
                st.query_params.clear()
            except Exception:
                pass
    else:
        # Desktop: use st.columns
        header = st.columns(7)
        for i, w in enumerate(days):
            header[i].markdown(f"**{w}**")
        for week in month_cal:
            cols = st.columns(7)
            for i, d in enumerate(week):
                is_current_month = (d.month == m)
                times = available_start_times(barber_id, service_id, d) if is_current_month else []
                label = f"{d.day}"
                disabled = (len(times) == 0) or (d < today) or (not is_current_month)
                cell_class = "calendar-cell disabled" if disabled else "calendar-cell"
                with cols[i]:
                    if is_current_month:
                        if disabled:
                            st.markdown(f'<div class="{cell_class}">{label}</div>', unsafe_allow_html=True)
                        else:
                            any_enabled = True
                            if st.button(label, key=f"day-{d.isoformat()}"):
                                st.session_state['book_date'] = d
                                st.session_state['scroll_to_times'] = True
                    else:
                        st.markdown(f'<div class="{cell_class}">{label}</div>', unsafe_allow_html=True)
    if not any_enabled:
        st.info("No available days for booking in this month. Please try another month.")


# -----------------------------
# Streamlit App
# -----------------------------

st.set_page_config(page_title="The Groom Room", page_icon="✂️", layout="wide")
# Enhanced mobile-friendly CSS for calendar grid
st.markdown('''
    <style>
    /* Responsive table for admin */
    .mobile-table-wrapper { overflow-x: auto; }
    table { width: 100% !important; min-width: 400px; border-spacing: 0 !important; border-collapse: collapse !important; }
    th, td { font-size: 1em; padding: 0 !important; }
    /* Make buttons and inputs larger for touch, but reduce padding for compactness */
    .stButton > button, .stTextInput > div > input, .stSelectbox > div, .calendar-btn {
      min-height: 32px; font-size: 0.96em; padding: 0 !important;
    }
    .calendar-btn {
      width: 100%; border: none; background: #18191a; color: #fff; border-radius: 4px;
      font-weight: 500; transition: background 0.2s; margin: 0 !important; padding: 0 !important;
    }
    .calendar-btn:hover { background: #2d2d2d; cursor: pointer; }
    /* Make columns stack on small screens */
    @media (max-width: 600px) {
      .stColumns { flex-direction: column !important; }
      .stButton > button, .stTextInput > div > input, .stSelectbox > div { width: 100% !important; }
      table { font-size: 0.95em; }
      .calendar-wrapper { overflow-x: auto; -webkit-overflow-scrolling: touch; }
      .calendar-cell { min-width: 24px; margin: 0 !important; font-size: 0.96em; padding: 0 !important; }
    }
    /* Calendar grid: always show border and spacing for day cells */
    .calendar-row { display: flex; justify-content: flex-start; margin-bottom: 0; }
    .calendar-cell {
      border: 1px solid #333; border-radius: 4px; padding: 0 !important; text-align: center;
      background: #18191a; margin: 0 !important; min-width: 20px; max-width: 28px; font-weight: 500;
      transition: background 0.2s;
      font-size: 0.96em;
    }
    .calendar-cell.disabled, .calendar-btn:disabled { opacity: 0.35; background: #222; color: #888; }
    /* Available slots: compact buttons */
    .stColumns > div > .stButton { margin: 0 !important; padding: 0 !important; }
    .stColumns > div > .stButton > button { margin: 0 !important; min-width: 32px; min-height: 20px; font-size: 0.96em; padding: 0 !important; }
    /* Reduce space between columns for time slots */
    .stColumns { gap: 2px !important; margin: 0 !important; }
    .stButton { margin: 0 !important; padding: 0 !important; }
    </style>
''', unsafe_allow_html=True)

init_db()
ensure_session_defaults()

# Custom header with emoji and new title as a table for alignment
st.markdown('''
<table style="border:none;background:none;width:auto;">
  <tr style="border:none;background:none;">
    <td style="border:none;background:none;vertical-align:middle;"><span style="font-size:2.5em;">✂️🪒</span></td>
    <td style="border:none;background:none;vertical-align:middle;">
      <span style="background:#465a77;padding:0.2em 0.7em;margin-left:0.5em;border-radius:4px;color:#fff;font-size:1.15em;font-weight:bold;">The Groom Room</span>
      <span style="font-size:0.85em;color:#bbb;margin-left:0.7em;">by Pravesh</span>
    </td>
  </tr>
</table>''', unsafe_allow_html=True)
st.markdown('<div style="margin-bottom:0.5em;"><em>“Book it. Own it. Style it.”</em></div>', unsafe_allow_html=True)

# Pricing sidebar toggle state
if 'show_pricing_sidebar' not in st.session_state:
    st.session_state['show_pricing_sidebar'] = False
if 'pricing_btn_counter' not in st.session_state:
    st.session_state['pricing_btn_counter'] = 0

# --- Place Show Pricing button at the very top left ---
top_cols = st.columns([1, 8])
with top_cols[0]:
    show_pricing_clicked = st.button('Show Pricing', key=f'show_pricing_btn_top_{st.session_state["pricing_btn_counter"]}')
    if show_pricing_clicked:
        st.session_state['show_pricing_sidebar'] = True
        st.session_state['pricing_btn_counter'] += 1  # Only increment here

# Move pricing list to main page, below header, and show/expand when button is clicked
if st.session_state.get('show_pricing_sidebar', False):
    st.markdown('''
    <div style="background:#f7f7fa;border-radius:10px;padding:1.2em 1.5em 1.2em 1.5em;margin-bottom:1em;box-shadow:0 2px 8px #e0e0e0;max-width:480px;">
      <h3 style="margin-top:0;margin-bottom:0.7em;font-size:1.3em;color:#465a77;">✂️🪒 <span style="color:#222;">Barber Shop Price List</span></h3>
      <div style="margin-bottom:0.7em;"><b style="color:#465a77;">Haircuts</b></div>
      <ul style="list-style:none;padding-left:0;margin-bottom:0.7em;">
        <li><span style="font-size:1.2em;">👨</span> <span style="color:#2d8cff;">Men's Haircut</span> <span style="float:right;color:#27ae60;font-weight:bold;">Rs 100</span></li>
        <li><span style="font-size:1.2em;">🧒</span> <span style="color:#e67e22;">Kids' Haircut (under 15)</span> <span style="float:right;color:#27ae60;font-weight:bold;">Rs 75</span></li>
        <li><span style="font-size:1.2em;">🧓</span> <span style="color:#8e44ad;">Seniors' Cut</span> <span style="float:right;color:#27ae60;font-weight:bold;">Rs 75</span></li>
      </ul>
      <div style="margin-bottom:0.7em;"><b style="color:#465a77;">Beard & Color</b></div>
      <ul style="list-style:none;padding-left:0;margin-bottom:0.7em;">
        <li><span style="font-size:1.2em;">🧔</span> <span style="color:#d35400;">Beard Trim</span> <span style="float:right;color:#2980b9;font-weight:bold;">Rs 50</span></li>
        <li><span style="font-size:1.2em;">🪒</span> <span style="color:#c0392b;">Shave Normal</span> <span style="float:right;color:#2980b9;font-weight:bold;">Rs 25</span></li>
        <li><span style="font-size:1.2em;">🎨</span> <span style="color:#16a085;">Hair color / Dry</span> <span style="float:right;color:#2980b9;font-weight:bold;">Rs 25</span></li>
      </ul>
      <div style="margin-bottom:0.7em;"><b style="color:#465a77;">Combo Deals</b></div>
      <ul style="list-style:none;padding-left:0;">
        <li><span style="font-size:1.2em;">💇‍♂️+🎨</span> <span style="color:#e67e22;">Haircut + hair color/Dry</span> <span style="float:right;color:#e67e22;font-weight:bold;">Rs 125</span></li>
        <li><span style="font-size:1.2em;">💇‍♂️+🧔</span> <span style="color:#8e44ad;">Haircut + Beard Trim</span> <span style="float:right;color:#8e44ad;font-weight:bold;">Rs 150</span></li>
        <li><span style="font-size:1.2em;">💇‍♂️+🪒+🎨</span> <span style="color:#16a085;">Haircut + Shave + hair color/Dry</span> <span style="float:right;color:#16a085;font-weight:bold;">Rs 175</span></li>
      </ul>
    </div>
    ''', unsafe_allow_html=True)
    if st.button('Close', key='close_pricing_sidebar'):
        st.session_state['show_pricing_sidebar'] = False

# Hide sidebar if user interacts with main area (simulate click outside)
def hide_sidebar_on_interaction():
    if st.session_state.get('show_pricing_sidebar', False):
        st.session_state['show_pricing_sidebar'] = False

barbers_df = get_barbers()
services_df = get_services()

# Tabs
cal_tab, admin_tab = st.tabs(["Calendar", "Admin"])

with cal_tab:
    st.subheader("Pick a date")
    # Use default barber/service (first in list) for calendar tab
    cal_barber_id = barbers_df.iloc[0]['id']
    cal_service_id = services_df.iloc[0]['id']
    # Show selected date in DD/MM/YY format above the picker
    st.markdown(f"**Selected date:** {st.session_state['book_date'].strftime('%d/%m/%y')}")
    picked_date = st.date_input("Pick a date", value=st.session_state['book_date'], min_value=date.today(), key='date_input_main')
    if picked_date != st.session_state['book_date']:
        st.session_state['book_date'] = picked_date
        st.session_state['scroll_to_times'] = True
        hide_sidebar_on_interaction()

    # Anchor for available times
    st.markdown('<a name="available-times"></a>', unsafe_allow_html=True)
    if st.session_state.get('scroll_to_times', False):
        st.markdown('<script>document.getElementsByName("available-times")[0].scrollIntoView({behavior: "smooth"});</script>', unsafe_allow_html=True)
        st.session_state['scroll_to_times'] = False

    st.divider()
    st.subheader("Available times on " + st.session_state['book_date'].strftime('%A %d/%m/%y'))
    today = date.today()
    book_date = st.session_state['book_date']
    if book_date < today:
        st.warning("You cannot book appointments for past dates.")
    else:
        times = available_start_times(cal_barber_id, cal_service_id, book_date)
        if not times:
            st.info("No free slots on this day — try another.")
        else:
            # Render time slot buttons in a compact custom HTML grid (horizontally stacked, wrapping)
            now = datetime.now()
            is_today = (book_date == today)
            btn_html = '<div style="display:flex;flex-wrap:wrap;gap:16px 24px;">'
            for i, tm in enumerate(times):
                time_str = tm.strftime('%H:%M')
                # Disable expired slots for today
                expired = False
                if is_today:
                    slot_dt = datetime.combine(book_date, tm)
                    if slot_dt <= now:
                        expired = True
                if expired:
                    btn_html += f'''<button disabled style="background:#222;color:#888;border:1.5px solid #888;border-radius:10px;font-size:1em;padding:0.15em 1.5em;margin:0;min-width:90px;min-height:48px;opacity:0.5;">{time_str}</button>'''
                else:
                    btn_html += f'''<form action="" method="get" style="margin:0 0 12px 0;padding:0;display:inline;">
                    <button name="pick_time" value="{time_str}" style="background:#18191a;color:#fff;border:1.5px solid #888;border-radius:10px;font-size:1em;padding:0.15em 1.5em;margin:0;min-width:90px;min-height:48px;cursor:pointer;display:inline-block;">{time_str}</button></form>'''
            btn_html += '</div>'
            st.markdown(btn_html, unsafe_allow_html=True)
            # Handle button click via query param
            pick_time = st.query_params.get('pick_time', None)
            if pick_time:
                st.session_state['chosen_time'] = pick_time
                st.session_state['scroll_to_quick_book'] = True
                st.query_params.clear()
            st.caption("Tip: pick a time, then fill your details below.")
            # Show chosen time below the tip if selected, with a clear button
            chosen_time = st.session_state.get('chosen_time', None)
            if chosen_time:
                col_time, col_clear = st.columns([3,1])
                with col_time:
                    st.markdown(f'<div style="margin-bottom:0.5em;"><b>Time chosen:</b> <span style="color:#2d8cff;">{chosen_time}</span></div>', unsafe_allow_html=True)
                with col_clear:
                    if st.button("Clear", key="clear_chosen_time"):
                        st.session_state['chosen_time'] = None
                        st.rerun()

        # Anchor for quick book
        st.markdown('<a name="quick-book"></a>', unsafe_allow_html=True)
        if st.session_state.get('scroll_to_quick_book', False):
            st.markdown('<script>document.getElementsByName("quick-book")[0].scrollIntoView({behavior: "smooth"});</script>', unsafe_allow_html=True)
            st.session_state['scroll_to_quick_book'] = False

        # Quick booking form right in the calendar tab
        # Only show the waitlist form if not already inside a form
        with st.form("quick_book_form"):
            st.write("### Confirm & get ready to shine")
            customer_name = st.text_input("Your name", key='cal_name')
            customer_phone = st.text_input("Phone", placeholder="e.g., +2305xxxxxx", key='cal_phone')
            # Multi-select for services
            # Always show all services in the specified order, regardless of DB content
            service_options = [
                "Men's Haircut (Rs 100)",
                "Kids' Haircut (under 15) (Rs 75)",
                "Seniors' Cut (Rs 75)",
                "Beard Trim (Rs 50)",
                "Shave Normal (Rs 25)",
                "Hair color / Dry (Rs 25)",
                "Haircut + hair color/Dry (Rs 125)",
                "Haircut + Beard Trim (Rs 150)",
                "Haircut + Shave + hair color/Dry (Rs 175)"
            ]
            name_map = {
                "Men's Haircut (Rs 100)": "Men's Haircut",
                "Kids' Haircut (under 15) (Rs 75)": "Kids' Haircut (under 15)",
                "Seniors' Cut (Rs 75)": "Seniors' Cut",
                "Beard Trim (Rs 50)": "Beard Trim",
                "Shave Normal (Rs 25)": "Shave Normal",
                "Hair color / Dry (Rs 25)": "Hair color / Dry",
                "Haircut + hair color/Dry (Rs 125)": "Haircut + hair color/Dry",
                "Haircut + Beard Trim (Rs 150)": "Haircut + Beard Trim",
                "Haircut + Shave + hair color/Dry (Rs 175)": "Haircut + Shave + hair color/Dry"
            }
            # For each option, try to get the service id from the DB, fallback to None if not found
            service_name_to_id = {}
            for opt in service_options:
                db_name = name_map[opt]
                match = services_df[services_df['name'] == db_name]
                service_name_to_id[opt] = match['id'].iloc[0] if not match.empty else None

            selected_services = st.multiselect("Select service(s)", service_options, default=[], key='cal_services')

            # ✅ FIXED: Calculate prices using DB values (no fragile string parsing)
            total_price = 0
            if selected_services and len(selected_services) > 0:
                st.markdown("**Selected services and prices:**", unsafe_allow_html=True)
                for s in selected_services:
                    db_name = name_map[s]
                    # Get price straight from services_df
                    price_row = services_df.loc[services_df['name'] == db_name, 'price']
                    price = float(price_row.values[0]) if not price_row.empty else 0
                    st.write(f"- {db_name} (Rs {int(price) if price.is_integer() else price})")
                    total_price += price
                # Render integer if whole number
                total_display = int(total_price) if float(total_price).is_integer() else total_price
                st.markdown(f"**Total: Rs {total_display}**", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color:#bbb;'>No service selected.</span>", unsafe_allow_html=True)

            notes = st.text_area("Notes (optional)", key='cal_notes')
            default_time_str = st.session_state.get('chosen_time', None)
            if default_time_str:
                st.markdown(f'<div style="margin-bottom:0.5em;"><b>Time booked:</b> <span style="color:#2d8cff;">{default_time_str}</span></div>', unsafe_allow_html=True)
            # Disable buttons if no service selected
            submit = st.form_submit_button("Confirm Booking", disabled=(not selected_services))
            join_waitlist_disabled = st.session_state.get('chosen_time', None) is not None or not selected_services
            join_waitlist = st.form_submit_button("JOIN WAITLIST  →", key='waitlist_submit2', disabled=join_waitlist_disabled)
            if submit:
                if not default_time_str:
                    st.error("Please choose a time above first.")
                elif not customer_name or not customer_phone:
                    st.error("Please enter your name and phone number.")
                elif not selected_services:
                    st.error("Please select at least one service.")
                elif book_date < today:
                    st.error("Cannot book appointments for past dates.")
                else:
                    try:
                        start_time_val = datetime.strptime(default_time_str, '%H:%M').time()
                        # For now, only book the first selected service (for compatibility with existing logic)
                        chosen_service_id = service_name_to_id[selected_services[0]]
                        if chosen_service_id is None:
                            st.error("Selected service not found in database. Please contact admin.")
                        else:
                            appt_id = create_appointment(
                                barber_id=cal_barber_id,
                                service_id=chosen_service_id,
                                customer_name=customer_name,
                                customer_phone=''.join([c for c in customer_phone if c.isdigit() or c=='+']),
                                appt_date=book_date,
                                start_time=start_time_val,
                                notes=notes,
                            )
                            st.success(f"✅ Booking confirmed for {book_date.strftime('%d/%m/%y')} at {default_time_str}! Ref: {appt_id[:8]}")
                            st.balloons()
                    except ValueError as e:
                        st.error(str(e))
                    except Exception as ex:
                        st.error(f"Something went wrong: {ex}")
            # Only process waitlist if button is enabled and no time is chosen
            if join_waitlist and not join_waitlist_disabled:
                if not customer_name or not customer_phone:
                    st.error("Please enter your name and phone number.")
                else:
                    conn = get_conn()
                    cur = conn.cursor()
                    waitlist_note = notes
                    if default_time_str:
                        waitlist_note = f"Requested time: {default_time_str}. " + (notes or "")
                    cur.execute('''INSERT INTO waitlist (id, name, phone, notes, requested_date, created_at) VALUES (?, ?, ?, ?, ?, ?)''',
                        (str(uuid.uuid4()), customer_name.strip(), ''.join([c for c in customer_phone if c.isdigit() or c=='+']), waitlist_note.strip(), book_date.isoformat(), datetime.utcnow().isoformat()))
                    conn.commit()
                    conn.close()
                    st.success(f"You have been added to the waitlist for {book_date.strftime('%d/%m/%y')}! We will contact you if a slot opens up.")

with admin_tab:
    st.subheader("Owner / Admin")
    # --- DISABLED ADMIN PASSWORD CHECK FOR TESTING ---
    st.session_state["admin_ok"] = True
    if st.session_state.get("admin_ok"):
        st.success("Admin mode active")
        # --- Admin Date Picker ---
        if 'admin_cal_date' not in st.session_state:
            st.session_state['admin_cal_date'] = date.today()
        # Show selected admin date in DD/MM/YY format above the picker
        st.markdown(f"**Selected date:** {st.session_state['admin_cal_date'].strftime('%d/%m/%y')}")
        admin_date = st.date_input("Pick a date to view bookings", value=st.session_state['admin_cal_date'], key='admin_date_input')
        st.session_state['admin_cal_date'] = admin_date
        sel_date = admin_date
        # --- Barber Unavailability Admin UI ---
        st.write("### Set Barber Unavailability")
        with st.form("set_unavailability_form"):
            # Always use the first barber in the list
            bu_barber_id = barbers_df.iloc[0]['id']
            bu_date = sel_date
            st.markdown(f"<b>Date:</b> {bu_date.strftime('%d/%m/%Y')}", unsafe_allow_html=True)
            full_day = st.checkbox("Full day unavailable", value=True, key='unav_full_day')
            bu_start = None
            bu_end = None
            if not full_day:
                bu_start = st.time_input("Start time", value=time(8,30), key='unav_start')
                bu_end = st.time_input("End time", value=time(20,30), key='unav_end')
            bu_reason = st.text_input("Reason (optional)", key='unav_reason')
            submit_unav = st.form_submit_button("Add Unavailability")
            if submit_unav:
                if not full_day and (bu_start is None or bu_end is None or bu_start >= bu_end):
                    st.error("Please provide a valid time range.")
                else:
                    conn = get_conn()
                    cur = conn.cursor()
                    cur.execute('''INSERT INTO barber_unavailability (id, barber_id, date, start_time, end_time, reason) VALUES (?, ?, ?, ?, ?, ?)''',
                        (str(uuid.uuid4()), bu_barber_id, bu_date.isoformat(),
                         None if full_day else bu_start.strftime('%H:%M'),
                         None if full_day else bu_end.strftime('%H:%M'),
                         bu_reason.strip()))
                    conn.commit()
                    conn.close()
                    st.success("Unavailability added!")
                    st.rerun()
        # List and manage unavailability for selected barber/date
        st.write("#### Unavailability Entries for Selected Date")
        for idx, row in get_barber_unavailability(bu_barber_id, sel_date).iterrows():
            st.markdown(f"- {row['date']} | "
                        f"{'Full day' if not row['start_time'] else row['start_time'] + '-' + row['end_time']} | "
                        f"{row['reason'] if row['reason'] else ''}", unsafe_allow_html=True)
            if st.button("Delete", key=f"del_unav_{row['id']}"):
                conn = get_conn()
                conn.execute("DELETE FROM barber_unavailability WHERE id=?", (row['id'],))
                conn.commit()
                conn.close()
                st.success("Unavailability deleted.")
                st.rerun()
        # --- Existing admin booking/waitlist code ...
        st.markdown(f"#### Bookings & Waitlist for {sel_date.strftime('%A, %d/%m/%y')}")
        # Fetch all appointments for all barbers on selected date
        df = fetch_df(
            '''SELECT a.id, a.appt_date, a.customer_name, a.customer_phone, a.start_time, a.end_time, s.name as service FROM appointments a JOIN services s ON s.id=a.service_id WHERE a.appt_date=? ORDER BY a.start_time''',
            (sel_date.isoformat(),)
        )
        # Fetch waitlist for this date
        waitlist_df = fetch_df(
            '''SELECT id, name, phone, notes, requested_date, created_at FROM waitlist WHERE requested_date=? ORDER BY created_at''',
            (sel_date.isoformat(),)
        )
        # Render as Streamlit table with action buttons
        st.write('### Bookings')
        for idx, row in df.iterrows():
            cols = st.columns([2, 2, 2, 1, 1])
            phone_display = f"{html.escape(str(row['customer_phone']))} <a href='tel:{''.join([c for c in str(row['customer_phone']) if c.isdigit() or c=='+'])}' target='_blank' style='text-decoration:none;'>📞</a>"
            cols[0].markdown(f"<b>{html.escape(str(row['customer_name']))}</b>", unsafe_allow_html=True)
            cols[1].markdown(phone_display, unsafe_allow_html=True)
            cols[2].markdown(f"{row['start_time']} - {row['end_time']}", unsafe_allow_html=True)
            if cols[3].button('Change', key=f'change_appt_{row["id"]}'):
                st.session_state['change_appt_id'] = row['id']
            if cols[4].button('Delete', key=f'delete_appt_{row["id"]}'):
                delete_appointment(row['id'])
                st.success('Booking deleted!')
                st.rerun()
        st.write('### Waitlist')
        for idx, row in waitlist_df.iterrows():
            cols = st.columns([2, 2, 2, 1, 1])
            cols[0].markdown(f"<b>{html.escape(str(row['name']))}</b>", unsafe_allow_html=True)
            cols[1].markdown(f"{html.escape(str(row['phone']))} <a href='tel:{''.join([c for c in str(row['phone']) if c.isdigit() or c=='+'])}' target='_blank'>📞</a>", unsafe_allow_html=True)
            cols[2].markdown(f"{html.escape(str(row['notes']))}", unsafe_allow_html=True)
            if cols[3].button('Change', key=f'change_waitlist_{row["id"]}'):
                st.session_state['change_waitlist_id'] = row['id']
            if cols[4].button('Delete', key=f'delete_waitlist_{row["id"]}'):
                conn = get_conn()
                conn.execute("DELETE FROM waitlist WHERE id=?", (row['id'],))
                conn.commit()
                conn.close()
                st.success('Waitlist entry deleted!')
                st.rerun()
        # Handle change actions
        change_appt_id = st.session_state.get('change_appt_id', None)
        change_waitlist_id = st.session_state.get('change_waitlist_id', None)
        if change_appt_id:
            appt_row = fetch_df("SELECT * FROM appointments WHERE id=?", (change_appt_id,)).iloc[0]
            new_date = st.date_input("New date", value=datetime.strptime(appt_row['appt_date'], '%Y-%m-%d').date(), key='change_appt_date')
            slots = available_start_times(appt_row['barber_id'], appt_row['service_id'], new_date)
            slot_labels = [s.strftime('%H:%M') for s in slots]
            new_time = st.selectbox("New time", slot_labels, key='change_appt_time')
            if st.button("Update Booking", key='update_appt_btn'):
                services = get_services()
                duration = int(services.loc[services['id'] == appt_row['service_id'], 'duration_min'].iloc[0])
                new_end = (datetime.combine(new_date, datetime.strptime(new_time, '%H:%M').time()) + timedelta(minutes=duration)).time()
                conn = get_conn()
                cur = conn.cursor()
                cur.execute("UPDATE appointments SET appt_date=?, start_time=?, end_time=? WHERE id=?", (new_date.isoformat(), new_time, new_end.strftime('%H:%M'), change_appt_id))
                conn.commit()
                conn.close()
                st.success(f"Booking updated to {new_date.strftime('%d/%m/%y')} at {new_time}!")
                st.session_state['change_appt_id'] = None
                st.rerun()
        if change_waitlist_id:
            wait_row = fetch_df("SELECT * FROM waitlist WHERE id=?", (change_waitlist_id,)).iloc[0]
            new_date = st.date_input("New requested date", value=datetime.strptime(wait_row['requested_date'], '%Y-%m-%d').date(), key='change_waitlist_date')
            new_notes = st.text_area("Notes (optional, can include time)", value=wait_row['notes'], key='change_waitlist_notes')
            if st.button("Update Waitlist Entry", key='update_waitlist_btn'):
                conn = get_conn()
                cur = conn.cursor()
                cur.execute("UPDATE waitlist SET requested_date=?, notes=? WHERE id=?", (new_date.isoformat(), new_notes, change_waitlist_id))
                conn.commit()
                conn.close()
                st.success(f"Waitlist entry updated to {new_date.strftime('%d/%m/%y')}!")
                st.session_state['change_waitlist_id'] = None
                st.rerun()
