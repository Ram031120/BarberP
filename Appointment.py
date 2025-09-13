import streamlit as st
import sqlite3
from datetime import datetime, date, time, timedelta
import pandas as pd
import uuid
from typing import List, Tuple
import calendar as cal

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
    services = get_services()
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

st.set_page_config(page_title="The Groom Room", page_icon="488", layout="wide")
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
    .stColumns > div > .stButton > button { margin: 0 !important; min-width: 32px; min-height: 20px; font-size: 0.96em; padding: 0 !important; }
    </style>
''', unsafe_allow_html=True)

init_db()
ensure_session_defaults()

# Custom header with emoji and new title
st.markdown('<div style="display:flex;align-items:center;"><span style="font-size:2.5em;">✂️🪒</span><span style="background:#465a77;padding:0.2em 0.7em;margin-left:0.5em;border-radius:4px;color:#fff;font-size:2.3em;font-weight:bold;">The Groom Room</span></div>', unsafe_allow_html=True)
st.markdown('<div style="margin-bottom:0.5em;"><em>“Book it. Own it. Style it.”</em></div>', unsafe_allow_html=True)

# Pricing sidebar toggle state
if 'show_pricing_sidebar' not in st.session_state:
    st.session_state['show_pricing_sidebar'] = False

# Show Pricing button in main area (always visible)
if st.button('Show Pricing', key='show_pricing_btn') or st.session_state.get('show_pricing_sidebar', False):
    st.session_state['show_pricing_sidebar'] = True
    with st.sidebar:
        st.markdown("""
        ### ✂️🪒 BARBER SHOP NEW PRICE LIST
        **Haircuts**
        1. Men's Haircut .................... Rs 100  
        2. Kids' Haircut (under 15) ......... Rs 75  
        3. Seniors' Cut ..................... Rs 75  
        **Beard & color**
        1. Beard Trim ....................... Rs 50  
        2. Shave Normal ..................... Rs 25  
        3. Hair color / Dry ................. Rs 25  
        **Combo Deals**
        1. Haircut + hair color/Dry ......... Rs 125  
        2. Haircut + Beard Trim ............. Rs 150  
        3. Haircut + Shave + hair color/Dry  Rs 175  
        """)
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
    st.subheader("Available times on " + st.session_state['book_date'].strftime('%A %d %B %Y'))
    today = date.today()
    book_date = st.session_state['book_date']
    if book_date < today:
        st.warning("You cannot book appointments for past dates.")
    else:
        times = available_start_times(cal_barber_id, cal_service_id, book_date)
        if not times:
            st.info("No free slots on this day — try another.")
            # Waitlist feature
            st.markdown('<div style="text-align:center; margin-top:2em;">'
                        '<p style="font-size:1.2em;">Can\'t find a suitable time for you?</p>'
                        '</div>', unsafe_allow_html=True)
            with st.form("waitlist_form"):
                w_name = st.text_input("Your name", key='waitlist_name')
                w_phone = st.text_input("Phone", placeholder="e.g., +2305xxxxxx", key='waitlist_phone')
                w_notes = st.text_area("Preferred time, notes (optional)", key='waitlist_notes')
                submit_wait = st.form_submit_button("JOIN WAITLIST  →")
                if submit_wait:
                    if not w_name or not w_phone:
                        st.error("Please enter your name and phone number.")
                    else:
                        conn = get_conn()
                        cur = conn.cursor()
                        cur.execute('''INSERT INTO waitlist (id, name, phone, notes, requested_date, created_at) VALUES (?, ?, ?, ?, ?, ?)''',
                            (str(uuid.uuid4()), w_name.strip(), ''.join([c for c in w_phone if c.isdigit() or c=='+']), w_notes.strip(), book_date.isoformat(), datetime.utcnow().isoformat()))
                        conn.commit()
                        conn.close()
                        st.success("You have been added to the waitlist! We will contact you if a slot opens up.")
        else:
            tcol = st.columns(4)
            chosen_time = None
            for i, tm in enumerate(times):
                if tcol[i % 4].button(tm.strftime('%H:%M'), key=f"tm-{tm.strftime('%H%M')}"):
                    chosen_time = tm
                    st.session_state['chosen_time'] = tm.strftime('%H:%M')
                    st.session_state['scroll_to_quick_book'] = True
            st.caption("Tip: pick a time, then fill your details below.")

        # Anchor for quick book
        st.markdown('<a name="quick-book"></a>', unsafe_allow_html=True)
        if st.session_state.get('scroll_to_quick_book', False):
            st.markdown('<script>document.getElementsByName("quick-book")[0].scrollIntoView({behavior: "smooth"});</script>', unsafe_allow_html=True)
            st.session_state['scroll_to_quick_book'] = False

        # Quick booking form right in the calendar tab
        # Only show the waitlist form if not already inside a form
        show_waitlist = True
        with st.form("quick_book_form"):
            st.write("### Quick Book")
            customer_name = st.text_input("Your name", key='cal_name')
            customer_phone = st.text_input("Phone", placeholder="e.g., +2305xxxxxx", key='cal_phone')
            notes = st.text_area("Notes (optional)", key='cal_notes')
            default_time_str = st.session_state.get('chosen_time', None)
            submit = st.form_submit_button("Confirm Booking")
            if submit:
                if not default_time_str:
                    st.error("Please choose a time above first.")
                elif not customer_name or not customer_phone:
                    st.error("Please enter your name and phone number.")
                elif book_date < today:
                    st.error("Cannot book appointments for past dates.")
                else:
                    try:
                        start_time = datetime.strptime(default_time_str, '%H:%M').time()
                        appt_id = create_appointment(
                            barber_id=cal_barber_id,
                            service_id=cal_service_id,
                            customer_name=customer_name,
                            customer_phone=''.join([c for c in customer_phone if c.isdigit() or c=='+']),
                            appt_date=book_date,
                            start_time=start_time,
                            notes=notes,
                        )
                        st.success(f"✅ Booking confirmed for {book_date.isoformat()} at {default_time_str}! Ref: {appt_id[:8]}")
                        st.balloons()
                    except ValueError as e:
                        st.error(str(e))
                    except Exception as ex:
                        st.error(f"Something went wrong: {ex}")
            # Waitlist option if user can't find a suitable slot
            if show_waitlist:
                st.markdown('<div style="text-align:center; margin-top:2em;">'
                            '<p style="font-size:1.2em;">Can\'t find a suitable time for you?</p>'
                            '</div>', unsafe_allow_html=True)
                w_name2 = st.text_input("Your name", key='waitlist_name2')
                w_phone2 = st.text_input("Phone", placeholder="e.g., +2305xxxxxx", key='waitlist_phone2')
                w_notes2 = st.text_area("Preferred time, notes (optional)", key='waitlist_notes2')
                submit_wait2 = st.form_submit_button("JOIN WAITLIST  →", key='waitlist_submit2')
                if submit_wait2:
                    if not w_name2 or not w_phone2:
                        st.error("Please enter your name and phone number.")
                    else:
                        conn = get_conn()
                        cur = conn.cursor()
                        cur.execute('''INSERT INTO waitlist (id, name, phone, notes, requested_date, created_at) VALUES (?, ?, ?, ?, ?, ?)''',
                            (str(uuid.uuid4()), w_name2.strip(), ''.join([c for c in w_phone2 if c.isdigit() or c=='+']), w_notes2.strip(), book_date.isoformat(), datetime.utcnow().isoformat()))
                        conn.commit()
                        conn.close()
                        st.success("You have been added to the waitlist! We will contact you if a slot opens up.")
with admin_tab:
    st.subheader("Owner / Admin")
    def load_secrets_admin_password() -> str:
        default_pw = "admin123"
        try:
            return st.secrets.get("ADMIN_PASSWORD", default_pw)
        except Exception:
            return default_pw

    pw = st.text_input("Password", type="password")
    if st.button("Sign in"):
        st.session_state["admin_ok"] = (pw == load_secrets_admin_password())
    if st.session_state.get("admin_ok"):
        st.success("Admin mode active")
        # --- Admin Calendar ---
        if 'admin_cal_date' not in st.session_state:
            st.session_state['admin_cal_date'] = date.today()
        st.markdown("### Calendar View")
        y, m = st.session_state['cal_year'], st.session_state['cal_month']
        month_cal = cal.Calendar(firstweekday=0).monthdatescalendar(y, m)
        header = st.columns(7)
        for i, w in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
            header[i].markdown(f"**{w}**")
        today = date.today()
        for week in month_cal:
            cols = st.columns(7)
            for i, d in enumerate(week):
                is_current_month = (d.month == m)
                if not is_current_month:
                    with cols[i]:
                        st.caption(f"{d.day}")
                    continue
                disabled = d < today
                with cols[i]:
                    if st.button(str(d.day), key=f"admin-day-{d.isoformat()}", disabled=disabled):
                        st.session_state['admin_cal_date'] = d
        st.divider()
        sel_date = st.session_state['admin_cal_date']
        st.markdown(f"#### Appointments for {sel_date.strftime('%A, %d %B %Y')}")
        # Fetch all appointments for all barbers on selected date
        df = fetch_df(
            '''SELECT a.appt_date, a.customer_name, a.customer_phone, a.start_time, a.end_time FROM appointments a WHERE a.appt_date=? ORDER BY a.start_time''',
            (sel_date.isoformat(),)
        )
        # Fetch waitlist for this date
        waitlist_df = fetch_df(
            '''SELECT name, phone, notes FROM waitlist WHERE requested_date=? ORDER BY created_at''',
            (sel_date.isoformat(),)
        )
        if df.empty and waitlist_df.empty:
            st.info("No appointments or waitlist entries on this date.")
        else:
            # Format time as 1-hour interval (start - start+1h)
            def slot_time(row):
                start_dt = datetime.strptime(row['start_time'], '%H:%M')
                end_dt = (start_dt + timedelta(hours=1)).time()
                return f"{start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}"
            if not df.empty:
                df['Time'] = df.apply(slot_time, axis=1)
                df = df.rename(columns={
                    'appt_date': 'Date',
                    'customer_name': 'Name',
                    'customer_phone': 'Phone Number'
                })
            # Display as table with phone icon link and change time button
            from html import escape
            def phone_link(number):
                clean = ''.join([c for c in str(number) if c.isdigit() or c=='+'])
                return f'{escape(str(number))} <a href="tel:{clean}" target="_blank">📞</a>'
            if not df.empty:
                df['Phone Number'] = df['Phone Number'].apply(phone_link)
            # Prepare combined table
            table_html = '<div class="mobile-table-wrapper"><table style="width:100%"><thead><tr><th>Date</th><th>Name</th><th>Phone Number</th><th>Time</th></tr></thead><tbody>'
            # Appointments
            if not df.empty:
                for _, row in df.iterrows():
                    table_html += f'<tr><td>{row["Date"]}</td><td><b>{escape(str(row["Name"]))}</b></td><td>{row["Phone Number"]}</td><td><b>{row["Time"]}</b></td></tr>'
            # Waitlist
            if not waitlist_df.empty:
                for _, row in waitlist_df.iterrows():
                    table_html += f'<tr style="background:#222;"><td>{sel_date.isoformat()}</td><td><b>{escape(str(row["name"]))}</b> <span style="color:#f39c12;">(Waitlist)</span></td><td>{phone_link(row["phone"])}</td><td><span style="color:#f39c12;">{escape(str(row["notes"])) or "-"} (waiting list)</span></td></tr>'
            table_html += '</tbody></table></div>'
            st.write('<style>td {vertical-align: middle !important;}</style>', unsafe_allow_html=True)
            st.write(table_html, unsafe_allow_html=True)
            # Show table and allow time change
            for idx, row in df.iterrows():
                st.write('<hr>', unsafe_allow_html=True)
                cols = st.columns([2,2,3,2,2])
                cols[0].markdown(f"**{row['Date']}**")
                cols[1].markdown(f"**{row['Name']}**")
                cols[2].markdown(row['Phone Number'], unsafe_allow_html=True)
                cols[3].markdown(f"**{row['Time']}**")
                if cols[4].button("Change Time", key=f"change-{idx}"):
                    st.session_state['change_appt_id'] = row['Date'] + row['Name'] + str(idx)
                    st.session_state['change_start_time'] = row['start_time']
                    st.session_state['change_idx'] = idx
            # Show change time form if triggered
            if 'change_appt_id' in st.session_state:
                change_idx = st.session_state['change_idx']
                appt_row = df.iloc[change_idx]
                # Find the appointment in the DB to get its id and barber
                appt_db = fetch_df("SELECT * FROM appointments WHERE appt_date=? AND customer_name=? AND start_time=?", (appt_row['Date'], appt_row['Name'], appt_row['start_time']))
                if not appt_db.empty:
                    appt_id = appt_db.iloc[0]['id']
                    barber_id = appt_db.iloc[0]['barber_id']
                    service_id = appt_db.iloc[0]['service_id']
                    # List available slots for this barber/date/service
                    slots = available_start_times(barber_id, service_id, sel_date)
                    slot_labels = [s.strftime('%H:%M') + ' - ' + (datetime.combine(sel_date, s) + timedelta(hours=1)).strftime('%H:%M') for s in slots]
                    with st.form("change_time_form"):
                        st.write(f"Change time for {appt_row['Name']} on {appt_row['Date']}")
                        new_time = st.selectbox("New time slot", slot_labels, key='new_time_slot')
                        submit = st.form_submit_button("Update Appointment")
                        if submit:
                            # Parse new start time
                            new_start = datetime.strptime(new_time.split(' - ')[0], '%H:%M').time()
                            # Update appointment in DB
                            conn = get_conn()
                            cur = conn.cursor()
                            # Compute new end time based on service duration
                            services = get_services()
                            duration = int(services.loc[services['id'] == service_id, 'duration_min'].iloc[0])
                            new_end = (datetime.combine(sel_date, new_start) + timedelta(minutes=duration)).time()
                            cur.execute("UPDATE appointments SET start_time=?, end_time=? WHERE id=?", (new_start.strftime('%H:%M'), new_end.strftime('%H:%M'), appt_id))
                            conn.commit()
                            conn.close()
                            st.success("Appointment time updated!")
                            del st.session_state['change_appt_id']
                            del st.session_state['change_start_time']
                            del st.session_state['change_idx']
                            st.experimental_rerun()
