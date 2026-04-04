from flask import Flask, render_template, request, jsonify
from datetime import datetime
import requests
import time

app = Flask(__name__)

# ========== НАСТРОЙКИ SUPABASE ==========
SUPABASE_URL = "https://vxtjirpwhuqjwhlybqkh.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ4dGppcnB3aHVxandobHlicWtoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUyMzEzNTUsImV4cCI6MjA5MDgwNzM1NX0.4pyOcy73aEVDLVIHk1Hu0XLWZkaCKKXRmL9DFkYQfhE"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

active_users = {}
ACTIVE_TIMEOUT = 60

def supabase_get(table, select="*", eq_column=None, eq_value=None, limit=None, order=None):
    url = f"{SUPABASE_URL}/rest/v1/{table}?select={select}"
    if eq_column and eq_value:
        url += f"&{eq_column}=eq.{eq_value}"
    if order:
        url += f"&order={order}"
    if limit:
        url += f"&limit={limit}"
    response = requests.get(url, headers=HEADERS)
    return response.json()

def supabase_post(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    response = requests.post(url, headers=HEADERS, json=data)
    return response.json() if response.status_code == 201 else None

def supabase_patch(table, eq_column, eq_value, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}?{eq_column}=eq.{eq_value}"
    response = requests.patch(url, headers=HEADERS, json=data)
    return response.status_code == 200

def supabase_delete(table, eq_column, eq_value):
    url = f"{SUPABASE_URL}/rest/v1/{table}?{eq_column}=eq.{eq_value}"
    response = requests.delete(url, headers=HEADERS)
    return response.status_code == 204

# Автоудаление неактивных пользователей (запускается при каждом запросе, но не чаще раза в час)
last_cleanup = 0
CLEANUP_INTERVAL = 3600  # 1 час

def cleanup_inactive_users():
    global last_cleanup
    now = time.time()
    if now - last_cleanup < CLEANUP_INTERVAL:
        return
    last_cleanup = now
    
    try:
        # Находим пользователей, которые зарегистрировались, но НИ РАЗУ не заходили (last_seen = 0)
        # И прошло больше 15 минут с момента регистрации
        fifteen_min_ago = int((now - 900) * 1000)  # 15 минут в миллисекундах
        
        users = supabase_get("users", select="username,last_seen,timestamp", eq_column=None, eq_value=None)
        if users and isinstance(users, list):
            for user in users:
                username = user.get("username")
                if username == "admin":
                    continue
                last_seen = user.get("last_seen", 0)
                # Проверяем, есть ли у пользователя поле created_at или используем last_seen
                # Если last_seen == 0, значит пользователь ни разу не заходил
                if last_seen == 0:
                    # Проверяем время регистрации (если есть) или просто удаляем
                    supabase_delete("users", "username", username)
                    print(f"Удалён неактивный пользователь: {username}")
    except Exception as e:
        print(f"Ошибка при очистке: {e}")

@app.route('/')
def index():
    cleanup_inactive_users()
    return render_template('index.html')

@app.route('/private')
def private():
    cleanup_inactive_users()
    return render_template('private.html')

@app.route('/api/users')
def get_users():
    users = supabase_get("users", select="username,color,last_active,theme,last_seen", eq_column=None, eq_value=None)
    if isinstance(users, dict) and "error" in users:
        return jsonify([])
    
    for user in users:
        username = user.get("username")
        if username in active_users and time.time() - active_users[username] < ACTIVE_TIMEOUT:
            user["online"] = True
        else:
            user["online"] = False
            if username in active_users:
                del active_users[username]
    
    return jsonify(users)

@app.route('/api/active', methods=['POST'])
def update_active():
    data = request.json
    username = data.get('username')
    if username:
        active_users[username] = time.time()
        now_ms = int(time.time() * 1000)
        supabase_patch("users", "username", username, {"last_active": now_ms, "last_seen": now_ms})
    return jsonify({'success': True})

@app.route('/api/update_theme', methods=['POST'])
def update_theme():
    data = request.json
    username = data.get('username')
    theme = data.get('theme')
    if username and theme:
        supabase_patch("users", "username", username, {"theme": theme})
    return jsonify({'success': True})

@app.route('/api/private_messages', methods=['POST'])
def get_private_messages():
    data = request.json
    user1 = data.get('user1')
    user2 = data.get('user2')
    
    messages = supabase_get("private_messages", select="*", order="timestamp.asc", limit=200)
    if isinstance(messages, dict) and "error" in messages:
        return jsonify([])
    
    filtered = [m for m in messages if (m["from_user"] == user1 and m["to_user"] == user2) or (m["from_user"] == user2 and m["to_user"] == user1)]
    
    users = supabase_get("users", select="username,color", eq_column=None, eq_value=None)
    user_colors = {u["username"]: u.get("color", "#0066cc") for u in users if isinstance(u, dict)}
    
    for msg in filtered:
        msg["author_color"] = user_colors.get(msg["from_user"], "#0066cc")
    
    return jsonify(filtered)

@app.route('/api/send_private', methods=['POST'])
def send_private():
    try:
        data = request.json
        result = supabase_post("private_messages", {
            "from_user": data.get('from_user'),
            "to_user": data.get('to_user'),
            "text": data.get('text'),
            "time": data.get('time'),
            "timestamp": data.get('timestamp'),
            "is_read": False
        })
        return jsonify({'success': True, 'message_id': result.get('id') if result else None})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/delete_private_message', methods=['POST'])
def delete_private_message():
    try:
        data = request.json
        message_id = data.get('message_id')
        supabase_delete("private_messages", "id", message_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/mark_read', methods=['POST'])
def mark_read():
    try:
        data = request.json
        from_user = data.get('from_user')
        to_user = data.get('to_user')
        
        messages = supabase_get("private_messages", select="id", eq_column="from_user", eq_value=from_user)
        if messages:
            for msg in messages:
                supabase_patch("private_messages", "id", msg["id"], {"is_read": True})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/unread_count', methods=['POST'])
def unread_count():
    data = request.json
    username = data.get('username')
    messages = supabase_get("private_messages", select="*", eq_column="to_user", eq_value=username)
    if isinstance(messages, dict) and "error" in messages:
        return jsonify({'count': 0})
    unread = [m for m in messages if not m.get("is_read", False)]
    return jsonify({'count': len(unread), 'unread_from': list(set([m["from_user"] for m in unread]))})

@app.route('/api/messages')
def get_messages():
    messages = supabase_get("messages", select="*", order="timestamp.desc", limit=100)
    if isinstance(messages, dict) and "error" in messages:
        return jsonify([])
    messages.sort(key=lambda x: x.get("timestamp", 0))
    
    users = supabase_get("users", select="username,color", eq_column=None, eq_value=None)
    user_colors = {u["username"]: u.get("color", "#0066cc") for u in users if isinstance(u, dict)}
    
    for msg in messages:
        msg["author_color"] = user_colors.get(msg["author"], "#0066cc")
    
    return jsonify(messages)

@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        color = data.get('color', '#0066cc')
        
        existing = supabase_get("users", select="username", eq_column="username", eq_value=username)
        if existing and len(existing) > 0:
            return jsonify({'success': False, 'error': 'Пользователь уже существует'})
        
        now_ms = int(time.time() * 1000)
        supabase_post("users", {
            "username": username, 
            "password": password, 
            "is_approved": 1, 
            "color": color, 
            "last_active": 0,
            "last_seen": 0,
            "theme": "light"
        })
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        
        users = supabase_get("users", select="*", eq_column="username", eq_value=username)
        
        if users and len(users) > 0:
            user = users[0]
            if user.get("password") == password:
                active_users[username] = time.time()
                now_ms = int(time.time() * 1000)
                supabase_patch("users", "username", username, {"last_active": now_ms, "last_seen": now_ms})
                return jsonify({'success': True, 'color': user.get("color", "#0066cc"), 'theme': user.get("theme", "light")})
        
        return jsonify({'success': False, 'error': 'Неверный логин или пароль'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/delete_user', methods=['POST'])
def delete_user():
    try:
        data = request.json
        username = data.get('username')
        
        messages = supabase_get("messages", select="id", eq_column="author", eq_value=username)
        if messages and len(messages) > 0:
            for msg in messages:
                supabase_delete("messages", "id", msg["id"])
        
        private = supabase_get("private_messages", select="id")
        if private:
            for msg in private:
                supabase_delete("private_messages", "id", msg["id"])
        
        supabase_delete("users", "username", username)
        if username in active_users:
            del active_users[username]
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/delete_message', methods=['POST'])
def delete_message():
    try:
        data = request.json
        message_id = data.get('message_id')
        supabase_delete("messages", "id", message_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/clear_chat', methods=['POST'])
def clear_chat():
    try:
        messages = supabase_get("messages", select="id")
        if messages:
            for msg in messages:
                supabase_delete("messages", "id", msg["id"])
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/send_message', methods=['POST'])
def send_message():
    try:
        data = request.json
        result = supabase_post("messages", {
            "author": data.get('author'),
            "text": data.get('text'),
            "time": data.get('time'),
            "timestamp": data.get('timestamp')
        })
        return jsonify({'success': True, 'message_id': result.get('id') if result else None})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
