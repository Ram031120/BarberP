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
            return True
        unav_start = datetime.strptime(row['start_time'], '%H:%M').time()
        unav_end = datetime.strptime(row['end_time'], '%H:%M').time()
        if not (end <= unav_start or start >= unav_end):
            return True
    return False

# -----------------------------
# Scheduling Logic
# -----------------------------

WORKING_HOURS = {
    'Mon': (time(8, 30), time(20, 30)),
    'Tue': None,
    'Wed': (time(8, 30), time(20, 30)),
    'Thu': (time(8, 30), time(20, 30)),
    'Fri': (time(8, 30), time(20, 30)),
    'Sat': (time(8, 30), time(18, 0)),
    'Sun': (time(8, 30), time(15, 0)),
}

SLOT_INTERVAL_MIN = 60

def weekday_key(d: date) -> str:
    return d.strftime('%a')

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
        if (lunch_start <= cur_dt < lunch_end) or (break_start <= cur_dt < break_end):
            cur_dt += timedelta(minutes=SLOT_INTERVAL_MIN)
            continue
        slots.append(cur_dt.time())
        cur_dt += timedelta(minutes=SLOT_INTERVAL_MIN)
    return slots

def available_start_times(barber_id: str, service_id: str, d: date) -> List[time]:
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
        if is_barber_unavailable(barber_id, d, s, end_dt.time()):
            continue
        if not has_conflict(barber_id, d, s, end_dt.time()):
            free.append(s)
    return free

# -----------------------------
# Streamlit App
# -----------------------------

st.set_page_config(page_title="The Groom Room", page_icon="✂️", layout="wide")

init_db()

barbers_df = get_barbers()
services_df = get_services()

st.title("The Groom Room Booking System")

st.subheader("Quick Booking")
customer_name = st.text_input("Your name")
customer_phone = st.text_input("Phone", placeholder="e.g., +2305xxxxxx")

# Multi-select for services
service_options = list(services_df['name'])
selected_services = st.multiselect("Select service(s)", service_options, default=[])

# FIX: Calculate total using database prices
if selected_services:
    st.markdown("**Selected services and prices:**")
    total_price = 0
    for s in selected_services:
        price = services_df.loc[services_df['name'] == s, 'price'].values[0]
        st.write(f"- {s} (Rs {price})")
        total_price += price
    st.markdown(f"### **Total: Rs {total_price}**")
else:
    st.markdown("<span style='color:#bbb;'>No service selected.</span>", unsafe_allow_html=True)
