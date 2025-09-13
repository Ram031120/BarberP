Barber Booking App - README
==========================

Overview
--------
This is a Streamlit-based web application for managing a local barber shop's appointment bookings. It is designed to be simple, fast, and mobile-friendly, with both customer and admin features. The app uses a local SQLite database for all data storage and can be run on any machine with Python and Streamlit installed.

Features
--------
- **Customer Calendar:**
  - View a monthly calendar with available days for booking.
  - See available 1-hour time slots for each day (with business hours and breaks respected).
  - Book an appointment by selecting a time and entering your details.
  - If no suitable slot is available, join a waitlist for your preferred date and leave remarks.

- **Waitlist:**
  - Customers can join a waitlist if no slots are available or if they can't find a suitable time.
  - Waitlist entries include name, phone, preferred time/remarks, and are visible to the admin.

- **Admin Panel:**
  - Secure login for the shop owner/admin.
  - View all appointments and waitlist entries for any selected date in a single table.
  - Waitlist entries are clearly marked and show customer remarks.
  - Clickable phone icons to call customers directly from the table.
  - Change appointment times for any booking by selecting a new available slot.

- **Mobile Friendly:**
  - Responsive design with larger touch targets and scrollable tables for easy use on phones and tablets.

- **Service & Price List:**
  - Sidebar displays the full list of services and prices, including combo deals.

- **No User Registration:**
  - Customers only need to provide their name and phone number to book or join the waitlist.

How to Run
----------
1. Install Python 3.8+ and Streamlit (`pip install streamlit pandas`)
2. Place `Appointment.py` and `barber_shop.db` in the same folder (the database will be created automatically if missing).
3. Run the app:
   
   ```bash
   streamlit run Appointment.py
   ```
4. Open the provided local URL in your browser.

Admin Login
-----------
- Default admin password: `admin123` (can be changed in Streamlit secrets)

Customization
-------------
- Working hours, breaks, and services can be changed in the code.
- The app is designed for local/small business use and does not require cloud hosting.

Support
-------
For questions or improvements, contact the developer or open an issue in your project repository.
