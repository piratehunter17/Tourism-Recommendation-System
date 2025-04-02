from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import sqlite3
import os
import requests
import subprocess
import json
from bs4 import BeautifulSoup
import re
from recommendation import recommend_destinations  # Import the recommendation function

app = Flask(__name__)
app.secret_key = 'your_secret_key'

from flask_mail import Mail, Message

# SQLite database connection function
def get_db_connection():
    conn = sqlite3.connect('tourism_website.db')
    conn.row_factory = sqlite3.Row
    return conn

# Create the database and tables if they don't exist
def create_tables():
    if not os.path.exists('tourism_website.db'):
        conn = get_db_connection()
        conn.execute('''CREATE TABLE IF NOT EXISTS user (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            username TEXT UNIQUE NOT NULL,
                            email TEXT UNIQUE NOT NULL,
                            password TEXT NOT NULL
                        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS search_history (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            search_term TEXT NOT NULL,
                            FOREIGN KEY (user_id) REFERENCES user (id)
                        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS reviews (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER,
                            username TEXT,
                            rating INTEGER NOT NULL,
                            review_text TEXT,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (user_id) REFERENCES user (id)
                        )''')
        conn.commit()
        conn.close()

# Run table creation
create_tables()

# Home Route (Main Page)
@app.route('/')
@app.route('/index')
def index():
    if 'loggedin' in session:
        user_id = session['user_id']
        recommendations = recommend_destinations(user_id)
    else:
        recommendations = recommend_destinations()

    # Store recommendations in session so it remains the same for the map
    session['recommendations'] = recommendations  

    # Fetch images for each recommendation
    for destination in recommendations:
        image_url = fetch_image_urls(destination['dest_name'])
        if image_url:
            destination['image_url'] = image_url[0]

    # Fetch reviews from the database
    conn = get_db_connection()
    reviews = conn.execute('SELECT * FROM reviews').fetchall()
    conn.close()

    return render_template('index.html', username=session.get('username'),
                           recommended_destinations=recommendations, reviews=reviews)

# Function to fetch image URLs from Google Images
def fetch_image_urls(query, num_images=1):
    url = f"https://www.google.com/search?hl=en&tbm=isch&q={query}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
    }
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        img_tags = soup.find_all("img", {"src": re.compile('^https://')})
        
        img_urls = []
        for img_tag in img_tags[:num_images]:
            img_url = img_tag.get("src")
            if img_url:
                img_urls.append(img_url)
        return img_urls
    else:
        print(f"Failed to retrieve page, status code: {response.status_code}")
        return []

# Function to run geocode.py and get hotel details
def get_hotel_details(query):
    result = subprocess.run(
        ['python', 'geocode.py', query], capture_output=True, text=True
    )
    output = result.stdout
    hotels = json.loads(output)
    
    # Extract hotel name, price, and rating (assuming these fields exist in the JSON)
    hotel_details = []
    for hotel in hotels:
        name = hotel['hotel_name']
        price = hotel.get('price', 'N/A')  # If price isn't available, use 'N/A'
        rating = hotel.get('hotel_rating', 'N/A')  # If rating isn't available, use 'N/A'
        hotel_details.append({'name': name, 'price': price, 'rating': rating})
    
    return hotel_details

# Search Route (For Hotel Search and Image Fetching)
@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('query')
    if query:
        # Get hotel details by running geocode.py
        hotel_details = get_hotel_details(query)
        
        # Fetch images for each hotel name
        for hotel in hotel_details:
            image_url = fetch_image_urls(hotel['name'])
            if image_url:
                hotel['image_url'] = image_url[0]  # Get the first image URL for each hotel
        
        # Log user search term if logged in
        if 'loggedin' in session:
            user_id = session['user_id']
            conn = get_db_connection()
            conn.execute('INSERT INTO search_history (user_id, search_term) VALUES (?, ?)', (user_id, query))
            conn.commit()
            conn.close()

        return render_template('search.html', query=query, hotels=hotel_details)
    else:
        return render_template('search.html')

@app.route('/apply_filter', methods=['GET'])
def apply_filter():
    # Get filter criteria from the request
    star_rating = request.args.get('star_rating')
    price_range = request.args.get('price_range')

    print(f"Star Rating: {star_rating}, Price Range: {price_range}")  # Debug: Check if filters are received

    # Get the hotel query (in case there's a hotel search query to apply filters on)
    query = request.args.get('query', 'sample_query')  # Use 'sample_query' as fallback if no query is provided

    # Fetch hotel details using geocode.py (via subprocess)
    hotel_details = get_hotel_details(query)
    print(f"Original Hotel Details: {hotel_details}")  # Debug: Check hotel details fetched from geocode.py

    # Filter hotels based on star rating
    if star_rating:
        try:
            star_rating = int(star_rating)
            hotel_details = [hotel for hotel in hotel_details if hotel.get('rating') == star_rating]
            print(f"Hotels after Star Rating Filter: {hotel_details}")  # Debug: Check hotels after star rating filter
        except ValueError:
            print("Invalid star rating received.")

    # Filter hotels based on price range
    if price_range:
        try:
            # Define min and max price for the selected price range
            if price_range == '0-50':
                min_price, max_price = 0, 50
            elif price_range == '50-100':
                min_price, max_price = 50, 100
            elif price_range == '100-200':
                min_price, max_price = 100, 200
            elif price_range == '200+':
                min_price, max_price = 200, float('inf')
            else:
                min_price, max_price = 0, float('inf')

            # Filter hotels within the selected price range
            hotel_details = [hotel for hotel in hotel_details if isinstance(hotel.get('price'), (int, float)) and min_price <= hotel['price'] <= max_price]
            print(f"Hotels after Price Filter: {hotel_details}")  # Debug: Check hotels after price filter
        except Exception as e:
            print(f"Error filtering by price: {e}")

    # Fetch images for each hotel name after filtering
    for hotel in hotel_details:
        image_url = fetch_image_urls(hotel['name'])
        if image_url:
            hotel['image_url'] = image_url[0]  # Get the first image URL for each hotel

    # Return the filtered hotels to the search.html template
    return render_template('search.html', query=query, hotels=hotel_details)



# Registration Route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO user (username, email, password) VALUES (?, ?, ?)', 
                         (username, email, password))
            conn.commit()
            flash('Registration successful! You can now log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username or email already exists. Please try again.', 'danger')
        finally:
            conn.close()

    return render_template('register.html')

# Login Route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']  # Get the selected role from the form

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM user WHERE username = ? AND password = ?', 
                            (username, password)).fetchone()
        conn.close()

        if user:
            session['loggedin'] = True
            session['user_id'] = user['id']
            session['username'] = user['username']

            # Check the role and redirect accordingly
            if role == 'admin':
                return redirect(url_for('admin_dashboard'))  # Redirect to admin dashboard
            else:
                return redirect(url_for('index'))  # Redirect to the user dashboard (main page)
        else:
            flash('Invalid credentials. Please try again.', 'danger')

    return render_template('login.html')

# Logout Route
@app.route('/logout')
def logout():
    session.clear()  # Clears session data
    return redirect(url_for('index'))

# Route to handle review submission
@app.route('/submit_review', methods=['POST'])
def submit_review():
    rating = request.form['rating']
    review_text = request.form['review_text']
    user_id = session.get('user_id', None)  # Get from session if logged in
    username = session.get('username', 'Anonymous')  # Get username from session, default to 'Anonymous'

    if user_id:  # Only allow review submission if logged in
        conn = get_db_connection()
        conn.execute('INSERT INTO reviews (user_id, username, rating, review_text) VALUES (?, ?, ?, ?)',
                     (user_id, username, rating, review_text))
        conn.commit()
        conn.close()
    else:
        flash('You need to log in to submit a review.', 'danger')

    return redirect(url_for('index'))

# Profile Route
@app.route('/profile')
def profile():
    if 'loggedin' not in session:
        flash('You need to log in to view your profile.', 'danger')
        return redirect(url_for('login'))
    
    # Fetch user data from the database
    user_id = session['user_id']
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM user WHERE id = ?', (user_id,)).fetchone()

    # Fetch user search history (without created_at)
    search_history = conn.execute('SELECT search_term FROM search_history WHERE user_id = ?', (user_id,)).fetchall()

    conn.close()

    return render_template('profile.html', user=user, search_history=search_history)

# Manage Accounts and Reviews (Admin Dashboard)

# Route to display the admin dashboard with accounts and reviews
@app.route('/admin_dashboard')
def admin_dashboard():
    if 'loggedin' in session:
        conn = get_db_connection()

        # Fetch all accounts
        accounts = conn.execute('SELECT id, username, email FROM user').fetchall()

        # Fetch all reviews
        reviews = conn.execute('SELECT id, username, review_text, rating FROM reviews').fetchall()

        conn.close()

        # Render the admin dashboard page with accounts and reviews
        return render_template('admin_dashboard.html', accounts=accounts, reviews=reviews)
    else:
        flash('You need to log in as an admin to view this page.', 'danger')
        return redirect(url_for('login'))

# Route to create a new account
@app.route('/create_account', methods=['GET', 'POST'])
def create_account():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO user (username, email, password) VALUES (?, ?, ?)', 
                         (username, email, password))
            conn.commit()
            flash('Account created successfully!', 'success')
        except sqlite3.IntegrityError:
            flash('Username or email already exists. Please try again.', 'danger')
        finally:
            conn.close()

        return redirect(url_for('admin_dashboard'))

    return render_template('create_account.html')

# Route to edit an existing account
@app.route('/edit_account/<int:account_id>', methods=['GET', 'POST'])
def edit_account(account_id):
    conn = get_db_connection()

    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']

        conn.execute('UPDATE user SET username = ?, email = ? WHERE id = ?', 
                     (username, email, account_id))
        conn.commit()
        conn.close()
        flash('Account updated successfully!', 'success')
        return redirect(url_for('admin_dashboard'))

    account = conn.execute('SELECT id, username, email FROM user WHERE id = ?', (account_id,)).fetchone()
    conn.close()

    if account:
        return render_template('edit_account.html', account=account)
    else:
        flash('Account not found!', 'danger')
        return redirect(url_for('admin_dashboard'))

# Route to delete an account
@app.route('/delete_account/<int:account_id>', methods=['POST'])
def delete_account(account_id):
    conn = get_db_connection()

    conn.execute('DELETE FROM user WHERE id = ?', (account_id,))
    conn.commit()
    conn.close()

    flash('Account deleted successfully!', 'success')
    return redirect(url_for('admin_dashboard'))

# Route to delete a review
@app.route('/delete_review/<int:review_id>', methods=['POST'])
def delete_review(review_id):
    conn = get_db_connection()

    conn.execute('DELETE FROM reviews WHERE id = ?', (review_id,))
    conn.commit()
    conn.close()

    flash('Review deleted successfully!', 'success')
    return redirect(url_for('admin_dashboard')) 

# Route to map page
@app.route('/map')
def map_page():
    return render_template('map.html')


# Route to send the same recommendations to the map
@app.route('/recommend-map')
def recommend_map():
    if 'recommendations' in session:
        recommendations = session['recommendations']
    else:
        if 'loggedin' in session:
            user_id = session['user_id']
            recommendations = recommend_destinations(user_id)
        else:
            recommendations = recommend_destinations()

        session['recommendations'] = recommendations  # Store recommendations

    # Prepare JSON response
    locations = [{'name': dest['dest_name'], 'description': dest['description']} for dest in recommendations]
    return jsonify(locations)




if __name__ == '__main__':
    app.run(debug=True, port=5500)
