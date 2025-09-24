from flask import Flask, render_template, request, redirect, session, url_for, flash
import pymysql.cursors
import hashlib
import re
from datetime import datetime, timedelta
import uuid

app = Flask(__name__)
app.secret_key = 'your_secret_key'

conn = pymysql.connect(
    host='localhost',
    port=8889,
    user='root',
    password='root',
    db='ATRS',
    charset='utf8mb4',
    cursorclass=pymysql.cursors.DictCursor
)

@app.route("/", methods=["GET"])
def index():
    cursor = conn.cursor()
    cursor.execute('SELECT airport_name, city FROM Airport')
    airports = cursor.fetchall()

    source = request.args.get('source')
    destination = request.args.get('destination')
    depart_date = request.args.get('depart_date')

    query = 'SELECT * FROM Flight WHERE departure_date_time > NOW()'
    params = []
    if source:
        query += ' AND departure_airport = %s'
        params.append(source)
    if destination:
        query += ' AND arrival_airport = %s'
        params.append(destination)
    if depart_date:
        query += ' AND DATE(departure_date_time) = %s'
        params.append(depart_date)

    cursor.execute(query, params)
    flights = cursor.fetchall()
    cursor.close()

    return render_template(
        'index.html',
        flights=flights,
        airports=airports,
        selected_source=source,
        selected_destination=destination,
        selected_date=depart_date
    )

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        password = hashlib.md5(request.form["password"].encode()).hexdigest()
        is_email = re.match(r"[^@]+@[^@]+\.[^@]+", username)
        cursor = conn.cursor()
        try:
            if is_email:
                cursor.execute("SELECT * FROM Customer WHERE email=%s", (username,))
                if cursor.fetchone():
                    return render_template("signup.html", error="Email already registered.")
                cursor.execute(
                    "INSERT INTO Customer (email, password_, first_name, last_name, building_number, street, city, state_, passport_number, passport_expiration, passport_country, date_of_birth) VALUES (%s, %s, '', '', '', '', '', '', '', '2000-01-01', '', '2000-01-01')",
                    (username, password)
                )
            else:
                cursor.execute("SELECT * FROM Staff WHERE username=%s", (username,))
                if cursor.fetchone():
                    return render_template("signup.html", error="Username already registered.")
                cursor.execute(
                    "INSERT INTO Staff (username, password_, first_name, last_name, date_of_birth, email, airline_name) VALUES (%s, %s, '', '', '2000-01-01', '', '')",
                    (username, password)
                )
            conn.commit()
            return redirect("/login")
        except Exception as e:
            return render_template("signup.html", error="Registration failed: " + str(e))
    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = hashlib.md5(request.form["password"].encode()).hexdigest()
        is_email = re.match(r"[^@]+@[^@]+\.[^@]+", username)
        cursor = conn.cursor()
        if is_email:
            cursor.execute("SELECT * FROM Customer WHERE email=%s AND password_=%s", (username, password))
            user = cursor.fetchone()
            if user:
                session["user"] = username
                session["role"] = "customer"
                return redirect("/customer_home")
        else:
            cursor.execute("SELECT * FROM Staff WHERE username=%s AND password_=%s", (username, password))
            user = cursor.fetchone()
            if user:
                session["user"] = username
                session["role"] = "staff"
                session["airline"] = user.get("airline_name", "")
                return redirect("/staff_home")
        return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")

@app.route("/customer_home")
def customer_home():
    if "user" in session and session.get("role") == "customer":
        return render_template("customer_homepage.html")
    return redirect("/login")

@app.route("/staff_home")
def staff_home():
    if "user" in session and session.get("role") == "staff":
        return render_template("staff_dashboard.html")
    return redirect("/login")

@app.route("/logout")
def logout():
    session.clear()
    return render_template("goodbye.html")

@app.route('/search_flights', methods=['GET', 'POST'])
def search_flights():
    if "user" not in session or session.get("role") != "customer":
        return redirect("/login")
    name = request.args.get('name')
    category = request.args.get('category')
    flights = []
    cursor = conn.cursor()
    valid_categories = ['departure_airport', 'arrival_airport', 'departure_date_time', 'arrival_date_time']
    if name and category and category in valid_categories:
        sql = f"SELECT * FROM Flight WHERE {category} = %s AND departure_date_time > NOW()"
        cursor.execute(sql, (name,))
    else:
        cursor.execute("SELECT * FROM Flight WHERE departure_date_time > NOW()")
    flights = cursor.fetchall()
    cursor.close()
    return render_template('search_flights_page.html', flights=flights)

@app.route('/purchase', methods=['POST'])
def purchase():
    if "user" not in session or session.get("role") != "customer":
        return redirect("/login")
    email = session["user"]
    flight_number = request.form['flight_number']
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Flight WHERE flight_number = %s", (flight_number,))
    flight = cursor.fetchone()
    if not flight:
        return "Flight not found."
    cursor.execute("""
        SELECT * FROM Ticket 
        JOIN Purchase ON Ticket.id_number = Purchase.id_number
        WHERE Purchase.email = %s AND Ticket.flight_number = %s
    """, (email, flight_number))
    if cursor.fetchone():
        return f"You've already purchased Flight {flight_number}. <a href='/view_flights'>View My Flights</a>"
    ticket_id = str(uuid.uuid4())[:8]
    now = datetime.now()
    cursor.execute("""
        INSERT INTO Ticket (id_number, airline_name, flight_number, departure_date_time)
        VALUES (%s, %s, %s, %s)
    """, (ticket_id, flight['airline_name'], flight_number, flight['departure_date_time']))
    cursor.execute("""
        INSERT INTO Purchase (
            email, id_number, date_time, sold_price, 
            name_on_card, card_number, card_expiration, card_type
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        email, ticket_id, now, flight['base_price'],
        'Test User', '1234567890123456', '12/26', 'credit'
    ))
    conn.commit()
    cursor.close()
    return f"Flight {flight_number} purchased! <a href='/view_flights'>Go to My Flights</a>"

@app.route('/view_flights')
def view_flights():
    if "user" not in session or session.get("role") != "customer":
        return redirect("/login")
    email = session["user"]
    now = datetime.now()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT F.flight_number, F.departure_airport, F.arrival_airport,
               F.departure_date_time, F.arrival_date_time, F.base_price,
               T.id_number, F.airline_name
        FROM Flight F
        JOIN Ticket T ON F.flight_number = T.flight_number
                     AND F.airline_name = T.airline_name
                     AND F.departure_date_time = T.departure_date_time
        JOIN Purchase P ON T.id_number = P.id_number
        WHERE P.email = %s
        ORDER BY F.departure_date_time DESC
    """, (email,))
    flights = cursor.fetchall()
    for f in flights:
        if f['departure_date_time'] > now:
            f['rating_status'] = 'future'
        else:
            cursor.execute("""
                SELECT 1 FROM Rating
                WHERE email = %s AND airline_name = %s AND flight_number = %s AND departure_date_time = %s
            """, (email, f['airline_name'], f['flight_number'], f['departure_date_time']))
            if cursor.fetchone():
                f['rating_status'] = 'already'
            else:
                f['rating_status'] = 'rate'
    cursor.close()
    return render_template('view_flights_page.html', flights=flights)

@app.route('/rate_flight')
def rate_flight_form():
    if "user" not in session or session.get("role") != "customer":
        return redirect("/login")
    airline_name = request.args.get('airline_name')
    flight_number = request.args.get('flight_number')
    departure_date_time = request.args.get('departure_date_time')
    return render_template('rate_form.html',
                           airline_name=airline_name,
                           flight_number=flight_number,
                           departure_date_time=departure_date_time)

@app.route('/submit_rating', methods=['POST'])
def submit_rating():
    if "user" not in session or session.get("role") != "customer":
        return redirect("/login")
    email = session["user"]
    airline_name = request.form['airline_name']
    flight_number = request.form['flight_number']
    departure_date_time = request.form['departure_date_time']
    rating = int(request.form['rating'])
    comment = request.form['comment']
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO Rating (email, airline_name, flight_number, departure_date_time, rating, comment)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (email, airline_name, flight_number, departure_date_time, rating, comment))
    conn.commit()
    cursor.close()
    return "Thank you for your rating! <a href='/view_flights'>Back to My Flights</a>"

@app.route('/staff/view_flights', methods=['GET', 'POST'])
def staff_view_flights():
    if 'role' not in session or session['role'] != 'staff':
        return redirect(url_for('login'))
    airline = session['airline']
    cursor = conn.cursor()
    base_query = """
        SELECT flight_number, departure_airport, arrival_airport,
               departure_date_time, arrival_date_time, status_, airplane_id
        FROM Flight 
        WHERE airline_name = %s
    """
    params = [airline]
    if request.method == 'POST':
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        from_airport = request.form.get('from_airport')
        to_airport = request.form.get('to_airport')
        if start_date and end_date:
            base_query += " AND departure_date_time BETWEEN %s AND %s"
            start_dt = start_date + " 00:00:00"
            end_dt = end_date + " 23:59:59"
            params.extend([start_dt, end_dt])
        if from_airport:
            base_query += " AND departure_airport = %s"
            params.append(from_airport)
        if to_airport:
            base_query += " AND arrival_airport = %s"
            params.append(to_airport)
    else:
        today = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        future = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
        base_query += " AND departure_date_time BETWEEN %s AND %s"
        params.extend([today, future])
    base_query += " ORDER BY departure_date_time"
    cursor.execute(base_query, params)
    flights = cursor.fetchall()
    cursor.close()
    return render_template('view_flights.html', flights=flights)

@app.route('/staff/view_customers')
def view_customers():
    if 'role' not in session or session['role'] != 'staff':
        return redirect(url_for('login'))
    flight_number = request.args.get('flight_number')
    departure_date_time = request.args.get('departure_date_time')
    cursor = conn.cursor()
    query = '''
    SELECT C.first_name, C.last_name, C.email, T.id_number, P.sold_price
    FROM Purchase P
    JOIN Customer C ON P.email = C.email
    JOIN Ticket T ON P.id_number = T.id_number
    WHERE T.flight_number = %s AND T.departure_date_time = %s
    '''
    cursor.execute(query, (flight_number, departure_date_time))
    customers = cursor.fetchall()
    cursor.close()
    return render_template('view_customers.html', customers=customers, flight_number=flight_number)

@app.route('/staff/create_flight', methods=['GET', 'POST'])
def create_flight():
    if 'role' not in session or session['role'] != 'staff':
        return redirect(url_for('login'))
    airline = session['airline']
    cursor = conn.cursor()
    if request.method == 'POST':
        flight_number = request.form['flight_number']
        departure_airport = request.form['departure_airport']
        arrival_airport = request.form['arrival_airport']
        departure_time = request.form['departure_time']
        arrival_time = request.form['arrival_time']
        airplane_id = request.form['airplane_id']
        base_price = request.form['base_price']
        status = request.form['status']
        insert_query = '''
            INSERT INTO Flight (
                airline_name, flight_number, departure_date_time, arrival_date_time,
                departure_airport, arrival_airport, airplane_id, base_price, status_
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        '''
        cursor.execute(insert_query, (
            airline, flight_number, departure_time, arrival_time,
            departure_airport, arrival_airport, airplane_id, base_price, status
        ))
        conn.commit()
    today = datetime.today().strftime('%Y-%m-%d')
    view_query = '''
        SELECT * FROM Flight
        WHERE airline_name = %s AND departure_date_time BETWEEN %s AND DATE_ADD(%s, INTERVAL 30 DAY)
        ORDER BY departure_date_time
    '''
    cursor.execute(view_query, (airline, today, today))
    flights = cursor.fetchall()
    cursor.close()
    return render_template('create_flight.html', flights=flights)

@app.route('/staff/change_status', methods=['GET', 'POST'])
def change_flight_status():
    if 'role' not in session or session['role'] != 'staff':
        return redirect(url_for('login'))
    airline = session['airline']
    cursor = conn.cursor()
    if request.method == 'POST':
        flight_number = request.form.get('flight_number')
        departure_time = request.form.get('departure_time')
        new_status = request.form.get('new_status')
        update_query = """
            UPDATE Flight
            SET status_ = %s
            WHERE flight_number = %s AND departure_date_time = %s AND airline_name = %s
        """
        cursor.execute(update_query, (new_status, flight_number, departure_time, airline))
        conn.commit()
    cursor.execute("""
        SELECT flight_number, departure_date_time, status_
        FROM Flight
        WHERE airline_name = %s AND departure_date_time >= NOW()
        ORDER BY departure_date_time
    """, (airline,))
    flights = cursor.fetchall()
    cursor.close()
    return render_template('change_status.html', flights=flights)

@app.route('/staff/add_airplane', methods=['GET', 'POST'])
def add_airplane():
    if 'role' not in session or session['role'] != 'staff':
        return redirect(url_for('login'))
    airline = session['airline']
    cursor = conn.cursor()
    if request.method == 'POST':
        airplane_id = request.form['airplane_id']
        seat_count = request.form['seat_count']
        manufacturer = request.form['manufacturer']
        age = request.form['age']
        try:
            cursor.execute(
                "INSERT INTO Airplane (airline_name, airplane_id, seat_count, manufacturer, age) "
                "VALUES (%s, %s, %s, %s, %s)",
                (airline, airplane_id, seat_count, manufacturer, age)
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            flash(f"Error: {str(e)}")
    cursor.execute("SELECT * FROM Airplane WHERE airline_name = %s", (airline,))
    airplanes = cursor.fetchall()
    cursor.close()
    return render_template('add_airplane.html', airplanes=airplanes)

@app.route('/staff/view_flight_ratings')
def view_flight_ratings():
    if 'role' not in session or session['role'] != 'staff':
        return redirect(url_for('login'))
    airline = session['airline']
    cursor = conn.cursor()
    query = """
        SELECT F.flight_number, F.departure_date_time,
               R.email, R.rating, R.comment,
               AVG(R.rating) OVER (PARTITION BY F.flight_number, F.departure_date_time) AS avg_rating
        FROM Flight F
        LEFT JOIN Rating R 
            ON F.flight_number = R.flight_number
            AND F.airline_name = R.airline_name
            AND F.departure_date_time = R.departure_date_time
        WHERE F.airline_name = %s
        ORDER BY F.departure_date_time, F.flight_number, R.email
    """
    cursor.execute(query, (airline,))
    rows = cursor.fetchall()
    cursor.close()
    grouped = {}
    for row in rows:
        key = (row['flight_number'], row['departure_date_time'], row['avg_rating'])
        if key not in grouped:
            grouped[key] = []
        grouped[key].append({
            'email': row['email'],
            'rating': row['rating'],
            'comment': row['comment']
        })
    return render_template('view_flight_ratings.html', grouped=grouped)

@app.route('/staff/view_reports')
def view_reports():
    if 'role' not in session or session['role'] != 'staff':
        return redirect(url_for('login'))
    cursor = conn.cursor()
    selected_filter = request.args.get('filter')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    query = """
        SELECT 
            YEAR(date_time) AS year,
            MONTH(date_time) AS month,
            COUNT(*) AS tickets_sold
        FROM Purchase
        WHERE 1 = 1
    """
    params = []
    if selected_filter == "last_month":
        today = datetime.today()
        first_day_last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        last_day_last_month = today.replace(day=1) - timedelta(days=1)
        query += " AND date_time BETWEEN %s AND %s"
        params += [first_day_last_month, last_day_last_month]
    elif selected_filter == "last_year":
        current_year = datetime.today().year
        last_year_start = datetime(current_year - 1, 1, 1)
        last_year_end = datetime(current_year - 1, 12, 31, 23, 59, 59)
        query += " AND date_time BETWEEN %s AND %s"
        params += [last_year_start, last_year_end]
    elif selected_filter == "custom" and start_date and end_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            query += " AND date_time BETWEEN %s AND %s"
            params += [start, end]
        except ValueError:
            pass
    query += " GROUP BY year, month ORDER BY year, month"
    try:
        cursor.execute(query, tuple(params))
        data = cursor.fetchall()
    except Exception as e:
        cursor.close()
        return f"Error in report query: {e}"
    cursor.close()
    return render_template(
        'view_reports.html',
        data=data,
        selected_filter=selected_filter,
        start_date=start_date,
        end_date=end_date
    )

if __name__ == '__main__':
    app.run()