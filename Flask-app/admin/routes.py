from flask import Blueprint, render_template, request, redirect, url_for, flash, session, Response
from werkzeug.security import check_password_hash
from datetime import datetime
from psycopg2.extras import DictCursor
import psycopg2
import csv
from io import StringIO
from calendar import monthrange
import pytz
from app import get_db, close_db  # ✅ Only import these
from psycopg2 import Error as PGError

from . import admin  # ✅ Use the blueprint defined in __init__.py

local_tz = pytz.timezone('Africa/Johannesburg')

@admin.route('/dashboard')
def admin_dashboard():
    """Admin dashboard route"""
    if 'user_id' not in session or not session.get('is_admin'):
        flash('Unauthorized access!', 'danger')
        return redirect(url_for('main.login'))
    return render_template('dashboard/admin.html')

@admin.route('/users')
def manage_users():
    """User management route"""
    if 'user_id' not in session or not session.get('is_admin'):
        flash('Unauthorized access!', 'danger')
        return redirect(url_for('main.login'))
    
    conn = get_db()
    cursor = conn.cursor(cursor_factory=DictCursor)
    try:
        cursor.execute("""
            SELECT id, username, email, unit_number, created_at 
            FROM users
            ORDER BY created_at DESC
        """)
        users = [dict(row) for row in cursor.fetchall()]
    except PGError as e:
        flash(f"Error fetching users: {e}", 'danger')
        users = []
    finally:
        close_db(conn)
    
    return render_template('admin_users.html', users=users)

@admin.route('/history')
def admin_history():
    """Admin meter readings history route"""
    if 'user_id' not in session or not session.get('is_admin'):
        flash('Unauthorized access!', 'danger')
        return redirect(url_for('main.login'))

    conn = get_db()
    cursor = conn.cursor(cursor_factory=DictCursor)
    all_readings = []
    month = request.args.get('month', type=int)
    year = request.args.get('year', type=int)

    try:
        query = """
            SELECT mr.id, mr.reading, mr.notes, mr.created_at,
                   u.username, u.unit_number
            FROM meter_readings mr
            JOIN users u ON mr.user_id = u.id
        """
        params = []
        where_clauses = []

        if month and year:
            start_of_month_local = datetime(year, month, 1, 0, 0, 0, tzinfo=local_tz)
            end_day = monthrange(year, month)[1]
            end_of_month_local = datetime(year, month, end_day, 23, 59, 59, tzinfo=local_tz)

            start_date_utc = start_of_month_local.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
            end_date_utc = end_of_month_local.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')

            where_clauses.append("mr.created_at BETWEEN %s AND %s")
            params.extend([start_date_utc, end_date_utc])

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        query += " ORDER BY u.unit_number::integer ASC, mr.created_at DESC"
        cursor.execute(query, params)

        for row in cursor.fetchall():
            reading = dict(row)
            created_at_utc = row['created_at'].replace(tzinfo=pytz.UTC)
            created_at_local = created_at_utc.astimezone(local_tz)
            
            reading.update({
                'formatted_date': created_at_local.strftime('%Y-%m-%d %H:%M'),
                'date': created_at_local.strftime('%Y-%m-%d'),
                'time': created_at_local.strftime('%H:%M:%S')
            })
            all_readings.append(reading)

    except PGError as e:
        flash(f"Error fetching history: {e}", 'danger')
    finally:
        close_db(conn)

    return render_template('admin_history.html',
                           readings=all_readings,
                           selected_month=month,
                           selected_year=year)

@admin.route('/unit_pincode', methods=['GET', 'POST'])
def unit_pincode():
    """Unit pincode management route"""
    if 'user_id' not in session or not session.get('is_admin'):
        flash('Unauthorized access!', 'danger')
        return redirect(url_for('main.login'))

    conn = get_db()
    cursor = conn.cursor(cursor_factory=DictCursor)

    if request.method == 'POST':
        unit_number = request.form.get('unit_number')
        pin_code = request.form.get('pin_code')

        if not unit_number or not pin_code:
            flash('Unit Number and Pin Code are required!', 'danger')
        else:
            try:
                cursor.execute(
                    "SELECT id FROM unit_pincode WHERE unit_number = %s",
                    (unit_number,)
                )
                if cursor.fetchone():
                    flash(f'Unit {unit_number} already exists!', 'warning')
                else:
                    cursor.execute(
                        "INSERT INTO unit_pincode (unit_number, pin_code) VALUES (%s, %s)",
                        (unit_number, pin_code)
                    )
                    conn.commit()
                    flash(f'Pincode added for Unit {unit_number}!', 'success')
            except PGError as e:
                conn.rollback()
                flash(f'Database error: {str(e)}', 'danger')
            finally:
                close_db(conn)
                return redirect(url_for('admin.unit_pincode'))

    try:
        cursor.execute("SELECT * FROM unit_pincode ORDER BY unit_number")
        unit_pincodes = [dict(row) for row in cursor.fetchall()]
    except PGError as e:
        flash(f"Error fetching pincodes: {e}", 'danger')
        unit_pincodes = []
    finally:
        close_db(conn)

    return render_template('unit_pincode.html', unit_pincodes=unit_pincodes)

@admin.route('/download_readings')
def download_readings():
    """Download meter readings CSV route"""
    if 'user_id' not in session or not session.get('is_admin'):
        flash("Permission denied", "danger")
        return redirect(url_for('main.login'))

    conn = get_db()
    cursor = conn.cursor(cursor_factory=DictCursor)
    
    try:
        cursor.execute('''
            SELECT mr.created_at, u.username, u.unit_number, mr.reading, mr.notes
            FROM meter_readings mr
            JOIN users u ON mr.user_id = u.id
            ORDER BY mr.created_at DESC
        ''')
        
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Date', 'Time', 'Username', 'Unit', 'Reading', 'Notes'])
        
        for row in cursor.fetchall():
            dt_utc = row['created_at'].replace(tzinfo=pytz.UTC)
            dt_local = dt_utc.astimezone(local_tz)
            
            writer.writerow([
                dt_local.strftime('%Y-%m-%d'),
                dt_local.strftime('%H:%M:%S'),
                row['username'],
                row['unit_number'],
                row['reading'],
                row['notes'] or ''
            ])
        
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={"Content-Disposition": "attachment;filename=meter_readings.csv"}
        )
        
    except PGError as e:
        flash(f"Database error: {e}", 'danger')
        return redirect(url_for('admin.admin_history'))
    finally:
        close_db(conn)