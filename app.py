from flask import Flask, render_template, request, redirect, session, url_for, jsonify
import pyodbc
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_study_2024'

DB_PATH = os.path.join(os.path.dirname(__file__), 'Database21.accdb')
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def get_db_connection():
    return pyodbc.connect(r'DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};' rf'DBQ={DB_PATH};')


@app.context_processor
def inject_user():
    address = session.get('delivery_address', '')
    return dict(user=session, current_address=address)


@app.route('/')
def index():
    category = request.args.get('category', 'Все')
    search_query = request.args.get('search', '')
    restaurant = request.args.get('restaurant', 'Все')

    conn = get_db_connection()
    cursor = conn.cursor()

    # Достаем категории
    cursor.execute("SELECT DISTINCT Category FROM Dishes WHERE Available = 'Да'")
    categories = [row[0] for row in cursor.fetchall()]

    # ЖЕСТКАЯ СОРТИРОВКА КАТЕГОРИЙ
    order_dict = {'Бургеры': 1, 'Напитки': 2, 'Пицца': 3, 'Роллы': 4, 'Суши': 5, 'Снеки': 6}
    categories.sort(key=lambda x: order_dict.get(x, 99))

    # Достаем рестораны
    cursor.execute("SELECT DISTINCT Restaurant FROM Dishes WHERE Available = 'Да' AND Restaurant IS NOT NULL")
    restaurants = [str(row[0]).strip() for row in cursor.fetchall() if row[0]]

    query = "SELECT Id_Dish, Name, Price, Category, Image, Restaurant FROM Dishes WHERE Available = 'Да'"
    params = []

    if category != 'Все':
        query += " AND Category = ?"
        params.append(category)

    if restaurant != 'Все':
        query += " AND Restaurant = ?"
        params.append(restaurant)

    if search_query:
        query += " AND Name LIKE ?"
        params.append(f'%{search_query}%')

    cursor.execute(query, tuple(params))
    dishes = cursor.fetchall()
    conn.close()

    return render_template('index.html', dishes=dishes, categories=categories, restaurants=restaurants,
                           current_category=category, current_restaurant=restaurant, search_query=search_query)


@app.route('/api/dish/<int:dish_id>')
def api_dish(dish_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT Name, Description, Calories, Proteins, Fats, Carbs, Image, Category, Price, Restaurant FROM Dishes WHERE Id_Dish = ?",
        (dish_id,))
    dish = cursor.fetchone()

    if not dish:
        conn.close()
        return jsonify({'error': 'Not found'}), 404

    cursor.execute("SELECT Id_Size, Size_Name, Price FROM DishSizes WHERE Id_Dish = ?", (dish_id,))
    sizes = cursor.fetchall()
    conn.close()

    sizes_data = [{'id': s[0], 'name': s[1], 'price': float(s[2])} for s in sizes]

    return jsonify({
        'id': dish_id,
        'name': dish[0],
        'description': dish[1] if dish[1] else 'Вкусное блюдо для отличного настроения.',
        'calories': dish[2],
        'proteins': dish[3],
        'fats': dish[4],
        'carbs': dish[5],
        'image': dish[6],
        'category': dish[7],
        'price': float(dish[8]),
        'restaurant': dish[9] if dish[9] else 'Ресторан',
        'sizes': sizes_data
    })


@app.route('/update_address', methods=['POST'])
def update_address():
    if 'user_id' not in session or session['user_id'] == 0:
        return redirect(url_for('login'))
    new_address = request.form.get('address', '').strip()
    if new_address:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE Users SET Delivery_Address = ? WHERE Id_User = ?", (new_address, session['user_id']))
            conn.commit()
            conn.close()
        except Exception:
            pass
        session['delivery_address'] = new_address
    return redirect(request.referrer or url_for('index'))


@app.route('/cart')
def view_cart():
    if 'user_id' not in session or session['user_id'] == 0:
        return redirect(url_for('login'))
    cart = session.get('cart', [])
    total = sum(float(item['price']) * int(item['quantity']) for item in cart)
    return render_template('cart.html', cart=cart, total=total)


@app.route('/cart/remove/<int:index>')
def remove_from_cart(index):
    cart = session.get('cart', [])
    if 0 <= index < len(cart):
        cart.pop(index)
        session['cart'] = cart
    return redirect(url_for('view_cart'))


@app.route('/cart/update/<int:index>', methods=['POST'])
def update_cart(index):
    cart = session.get('cart', [])
    if 0 <= index < len(cart):
        new_qty = int(request.form.get('quantity', 1))
        if new_qty > 0:
            cart[index]['quantity'] = new_qty
            session['cart'] = cart
    return redirect(url_for('view_cart'))


@app.route('/order/submit', methods=['POST'])
def order_submit():
    if 'user_id' not in session or session['user_id'] == 0:
        return redirect(url_for('login'))
    size_id = request.form.get('size_id')
    quantity = int(request.form.get('quantity', 1))
    dish_id = int(request.form['dish_id'])
    conn = get_db_connection()
    cursor = conn.cursor()
    if size_id == 'none':
        cursor.execute("SELECT Price, Name FROM Dishes WHERE Id_Dish = ?", (dish_id,))
        row = cursor.fetchone()
        price = float(row[0]) if row else 0
        name = row[1] if row else "Блюдо"
        size_name = "Стандарт"
    else:
        cursor.execute("SELECT Price, Size_Name FROM DishSizes WHERE Id_Size = ?", (size_id,))
        row = cursor.fetchone()
        price = float(row[0]) if row else 0
        size_name = row[1] if row else "Стандарт"
        cursor.execute("SELECT Name FROM Dishes WHERE Id_Dish = ?", (dish_id,))
        name_row = cursor.fetchone()
        name = name_row[0] if name_row else "Блюдо"
    conn.close()

    if 'cart' not in session:
        session['cart'] = []
    cart = session['cart']
    found = False
    for item in cart:
        if item['dish_id'] == dish_id and item['size_id'] == size_id:
            item['quantity'] += quantity
            found = True
            break
    if not found:
        cart.append({'dish_id': dish_id, 'size_id': size_id, 'name': name, 'size_name': size_name, 'price': price,
                     'quantity': quantity})
    session['cart'] = cart
    return redirect(url_for('index'))


@app.route('/checkout', methods=['POST'])
def checkout():
    if 'user_id' not in session or session['user_id'] == 0:
        return redirect(url_for('login'))
    cart = session.get('cart', [])
    if not cart:
        return redirect(url_for('view_cart'))
    address = request.form.get('address', '').strip()
    if len(address) < 8 or not any(char.isdigit() for char in address) or not any(char.isalpha() for char in address):
        return "Ошибка: некорректный адрес. <a href='/cart'>Назад в корзину</a>"
    total_price = sum(float(item['price']) * int(item['quantity']) for item in cart)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO Orders (Id_User, Price, Status, [Date], Delivery_Address) VALUES (?, ?, 'Новый', Now(), ?)",
        (session['user_id'], total_price, address))
    cursor.execute("SELECT @@IDENTITY")
    order_id = cursor.fetchone()[0]
    for item in cart:
        cursor.execute("INSERT INTO Orders_Items (id_Order, id_Dish, Quantity) VALUES (?, ?, ?)",
                       (order_id, item['dish_id'], item['quantity']))
    conn.commit()
    conn.close()
    session['delivery_address'] = address
    session['cart'] = []
    return redirect(url_for('profile', tab='orders'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        phone = request.form['phone']
        email = request.form['email']
        password = request.form['password']
        errors = []
        if not phone.isdigit() or len(phone) != 11:
            errors.append("Некорректный формат номера телефона! Введите 11 цифр.")
        if '@' not in email or '.' not in email.split('@')[-1]:
            errors.append("Некорректный адрес почты! Пример: name@mail.ru")
        if errors:
            return render_template('register.html', error="<br>".join(errors))
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Users WHERE Phone = ?", (phone,))
        if cursor.fetchone():
            conn.close()
            return render_template('register.html', error="Этот номер уже зарегистрирован.")
        cursor.execute("INSERT INTO Users (Phone, Email, Password, Nickname) VALUES (?, ?, ?, ?)",
                       (phone, email, password, "Новый клиент"))
        conn.commit()
        conn.close()
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_input = request.form['login_input']
        password = request.form['password']
        if login_input == 'admin' and password == 'admin':
            session['user_id'] = 0
            session['nickname'] = 'Главный Админ'
            session['is_admin'] = True
            session['avatar'] = None
            session['delivery_address'] = 'Офис'
            return redirect(url_for('admin_panel'))
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT Id_User, Nickname, Avatar, Delivery_Address FROM Users WHERE (Phone = ? OR Email = ?) AND Password = ?",
            (login_input, login_input, password))
        user = cursor.fetchone()
        conn.close()
        if user:
            session['user_id'] = user[0]
            session['nickname'] = user[1]
            session['is_admin'] = False
            session['avatar'] = user[2]
            session['delivery_address'] = user[3] if user[3] else ''
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="Неверный номер телефона, почта или пароль.")
    return render_template('login.html')


@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session or session['user_id'] == 0:
        return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        new_nickname = request.form['nickname']
        new_email = request.form.get('email', '')
        new_address = request.form.get('address', '')
        old_password = request.form.get('old_password', '')
        new_password = request.form.get('new_password', '')
        avatar_file = request.files.get('avatar')
        if new_email:
            cursor.execute("UPDATE Users SET Nickname = ?, Email = ?, Delivery_Address = ? WHERE Id_User = ?",
                           (new_nickname, new_email, new_address, session['user_id']))
            session['email'] = new_email
        else:
            cursor.execute("UPDATE Users SET Nickname = ?, Delivery_Address = ? WHERE Id_User = ?",
                           (new_nickname, new_address, session['user_id']))
        session['nickname'] = new_nickname
        session['delivery_address'] = new_address
        if new_password:
            cursor.execute("SELECT Password FROM Users WHERE Id_User = ?", (session['user_id'],))
            current_db_password = cursor.fetchone()[0]
            if old_password != current_db_password:
                conn.close()
                return render_template('profile.html', error="Старый пароль введен неверно!", orders=[])
            cursor.execute("UPDATE Users SET Password = ? WHERE Id_User = ?", (new_password, session['user_id']))
        if avatar_file and avatar_file.filename != '':
            if session.get('avatar'):
                old_avatar_path = os.path.join(app.config['UPLOAD_FOLDER'], session['avatar'])
                if os.path.exists(old_avatar_path): os.remove(old_avatar_path)
            filename = secure_filename(f"avatar_{session['user_id']}_{avatar_file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            avatar_file.save(filepath)
            cursor.execute("UPDATE Users SET Avatar = ? WHERE Id_User = ?", (filename, session['user_id']))
            session['avatar'] = filename
        conn.commit()
        conn.close()
        return redirect(url_for('profile'))
    cursor.execute("SELECT Email, Phone, Delivery_Address FROM Users WHERE Id_User = ?", (session['user_id'],))
    user_data = cursor.fetchone()
    if user_data:
        session['email'] = user_data[0] if user_data[0] else ''
        session['phone'] = user_data[1] if user_data[1] else ''
        session['delivery_address'] = user_data[2] if user_data[2] else ''
    cursor.execute(
        "SELECT Id_Order, Price, [Date], Status, Delivery_Address FROM Orders WHERE Id_User = ? ORDER BY [Date] DESC",
        (session['user_id'],))
    orders_raw = cursor.fetchall()
    user_orders = []
    for o in orders_raw:
        cursor.execute(
            "SELECT d.Name, oi.Quantity FROM Orders_Items oi INNER JOIN Dishes d ON oi.id_Dish = d.Id_Dish WHERE oi.id_Order = ?",
            (o[0],))
        dishes_in_order = cursor.fetchall()
        dishes_str = ", ".join(
            [f"{row[0]} (x{row[1]})" for row in dishes_in_order]) if dishes_in_order else "Разные блюда"
        price_val = float(o[1]) if o[1] else 0.0
        user_orders.append((o[0], dishes_str, price_val, o[2], o[3], o[4]))
    conn.close()
    return render_template('profile.html', orders=user_orders)


@app.route('/order/<int:order_id>')
def order_details(order_id):
    if 'user_id' not in session and not session.get('is_admin'):
        return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT Id_Order, Price, [Date], Status, Delivery_Address FROM Orders WHERE Id_Order = ?",
                   (order_id,))
    order = cursor.fetchone()
    if not order:
        conn.close()
        return "Заказ не найден. <a href='/profile'>Назад</a>"
    cursor.execute("SELECT id_Dish, Quantity FROM Orders_Items WHERE id_Order = ?", (order_id,))
    cart_items = cursor.fetchall()
    items = []
    for item in cart_items:
        dish_id = item[0]
        qty = item[1]
        cursor.execute("SELECT Name, Image, Price, Restaurant FROM Dishes WHERE Id_Dish = ?", (dish_id,))
        dish_info = cursor.fetchone()
        if dish_info:
            dish_name = dish_info[0]
            dish_image = dish_info[1]
            dish_price = float(dish_info[2]) if dish_info[2] else 0.0
            rest_name = dish_info[3] if dish_info[3] else "Ресторан"
            cursor.execute("SELECT Size_Name, Price FROM DishSizes WHERE Id_Dish = ?", (dish_id,))
            size_info = cursor.fetchone()
            if size_info:
                size_name = size_info[0]
                dish_price = float(size_info[1]) if size_info[1] else 0.0
            else:
                size_name = "Стандарт"
            items.append((dish_name, dish_image, size_name, qty, dish_price, rest_name))
    conn.close()
    price_float = float(order[1]) if order[1] else 0.0
    order_fixed = (order[0], price_float, order[2], order[3], order[4])
    return render_template('order_detail.html', order=order_fixed, items=items)


@app.route('/admin/client/<int:user_id>')
def admin_client_profile(user_id):
    if not session.get('is_admin'): return "Нет доступа"
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT Nickname, Phone, Email, Delivery_Address, Avatar FROM Users WHERE Id_User = ?", (user_id,))
    client = cursor.fetchone()
    if not client:
        conn.close()
        return "Клиент не найден. <a href='/admin'>Назад</a>"
    cursor.execute(
        "SELECT Id_Order, Price, [Date], Status, Delivery_Address FROM Orders WHERE Id_User = ? ORDER BY [Date] DESC",
        (user_id,))
    orders_raw = cursor.fetchall()
    user_orders = []
    for o in orders_raw:
        cursor.execute(
            "SELECT d.Name, oi.Quantity FROM Orders_Items oi INNER JOIN Dishes d ON oi.id_Dish = d.Id_Dish WHERE oi.id_Order = ?",
            (o[0],))
        dishes_in_order = cursor.fetchall()
        dishes_str = ", ".join(
            [f"{row[0]} (x{row[1]})" for row in dishes_in_order]) if dishes_in_order else "Разные блюда"
        price_val = float(o[1]) if o[1] else 0.0
        user_orders.append((o[0], dishes_str, price_val, o[2], o[3], o[4]))
    conn.close()
    return render_template('client_profile.html', client=client, orders=user_orders, user_id=user_id)


@app.route('/profile/cancel_order/<int:order_id>')
def profile_cancel_order(order_id):
    if 'user_id' not in session or session['user_id'] == 0: return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT Id_Order FROM Orders WHERE Id_Order = ? AND Id_User = ? AND Status = 'Новый'",
                   (order_id, session['user_id']))
    if cursor.fetchone():
        cursor.execute("UPDATE Orders SET Status = 'Отменен' WHERE Id_Order = ?", (order_id,))
        conn.commit()
    conn.close()
    return redirect(url_for('profile'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/admin')
def admin_panel():
    if not session.get('is_admin'): return "У вас нет доступа. <a href='/'>На главную</a>"
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT o.Id_Order, u.Nickname, u.Phone, o.Price, o.[Date], o.Status, o.Delivery_Address, u.Id_User FROM Orders o INNER JOIN Users u ON o.Id_User = u.Id_User ORDER BY o.[Date] DESC")
    orders_raw = cursor.fetchall()
    orders = []
    for o in orders_raw:
        cursor.execute(
            "SELECT d.Name, oi.Quantity FROM Orders_Items oi INNER JOIN Dishes d ON oi.id_Dish = d.Id_Dish WHERE oi.id_Order = ?",
            (o[0],))
        dishes_in_order = cursor.fetchall()
        dishes_str = ", ".join(
            [f"{row[0]} (x{row[1]})" for row in dishes_in_order]) if dishes_in_order else "Разные блюда"
        price_val = float(o[3]) if o[3] else 0.0
        orders.append((o[0], o[1], o[2], dishes_str, price_val, o[4], o[5], o[6] if o[6] else 'Не указан', o[7]))
    conn.close()
    return render_template('admin.html', orders=orders)


@app.route('/admin/cancel/<int:order_id>')
def cancel_order(order_id):
    if not session.get('is_admin'): return "Нет доступа"
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE Orders SET Status = 'Отменен' WHERE Id_Order = ?", (order_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_panel'))


if __name__ == '__main__':
    app.run(debug=True)