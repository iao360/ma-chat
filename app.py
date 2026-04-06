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

def supabase_get(table, select="*", eq_column=None, eq_value=None, eq_column2=None, eq_value2=None, operator=None, limit=None, order=None):
    url = f"{SUPABASE_URL}/rest/v1/{table}?select={select}"
    if eq_column and eq_value:
        url += f"&{eq_column}=eq.{eq_value}"
    if eq_column2 and eq_value2 and operator:
        url += f"&{eq_column2}={operator}.{eq_value2}"
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

def supabase_patch(table, eq_column, eq_value, eq_column2, eq_value2, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}?{eq_column}=eq.{eq_value}&{eq_column2}=eq.{eq_value2}"
    response = requests.patch(url, headers=HEADERS, json=data)
    return response.status_code == 200

def supabase_delete(table, eq_column, eq_value, eq_column2=None, eq_value2=None):
    url = f"{SUPABASE_URL}/rest/v1/{table}?{eq_column}=eq.{eq_value}"
    if eq_column2 and eq_value2:
        url += f"&{eq_column2}=eq.{eq_value2}"
    response = requests.delete(url, headers=HEADERS)
    return response.status_code == 204

# ========== АВТОУДАЛЕНИЕ (ОТКЛЮЧЕНО) ==========
def cleanup_inactive_users():
    pass

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/private')
def private():
    return render_template('private.html')

@app.route('/groups')
def groups():
    return render_template('groups.html')

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
        supabase_patch("users", "username", username, "last_seen", "last_seen", {"last_active": now_ms, "last_seen": now_ms})
    return jsonify({'success': True})

@app.route('/api/update_theme', methods=['POST'])
def update_theme():
    data = request.json
    username = data.get('username')
    theme = data.get('theme')
    if username and theme:
        supabase_patch("users", "username", username, "theme", "theme", {"theme": theme})
    return jsonify({'success': True})

# ========== ГРУППОВЫЕ ЧАТЫ API ==========

@app.route('/api/groups', methods=['GET'])
def get_groups():
    username = request.args.get('username')
    if not username:
        return jsonify([])
    members = supabase_get("group_members", select="group_id", eq_column="username", eq_value=username)
    if isinstance(members, dict) and "error" in members:
        return jsonify([])
    group_ids = [m["group_id"] for m in members]
    if not group_ids:
        return jsonify([])
    groups = []
    for gid in group_ids:
        group_data = supabase_get("groups", select="*", eq_column="id", eq_value=gid)
        if group_data and len(group_data) > 0:
            groups.append(group_data[0])
    return jsonify(groups)

@app.route('/api/create_group', methods=['POST'])
def create_group():
    try:
        data = request.json
        name = data.get('name')
        color = data.get('color', '#0066cc')
        creator = data.get('creator')
        now_ms = int(time.time() * 1000)
        result = supabase_post("groups", {"name": name, "color": color, "creator": creator, "created_at": now_ms})
        if result and "id" in result:
            group_id = result["id"]
            supabase_post("group_members", {"group_id": group_id, "username": creator, "joined_at": now_ms})
            supabase_post("group_unread", {"group_id": group_id, "username": creator, "last_read": now_ms})
            return jsonify({'success': True, 'group_id': group_id})
        return jsonify({'success': False, 'error': 'Не удалось создать группу'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/group_members', methods=['POST'])
def get_group_members():
    data = request.json
    group_id = data.get('group_id')
    members = supabase_get("group_members", select="username", eq_column="group_id", eq_value=group_id)
    if isinstance(members, dict) and "error" in members:
        return jsonify([])
    usernames = [m["username"] for m in members]
    users = supabase_get("users", select="username,color", eq_column=None, eq_value=None)
    user_colors = {u["username"]: u.get("color", "#0066cc") for u in users if isinstance(u, dict)}
    result = []
    for username in usernames:
        is_online = username in active_users and time.time() - active_users[username] < ACTIVE_TIMEOUT
        result.append({"username": username, "color": user_colors.get(username, "#0066cc"), "online": is_online})
    return jsonify(result)

@app.route('/api/group_messages', methods=['POST'])
def get_group_messages():
    data = request.json
    group_id = data.get('group_id')
    messages = supabase_get("group_messages", select="*", eq_column="group_id", eq_value=group_id, order="timestamp.asc", limit=200)
    if isinstance(messages, dict) and "error" in messages:
        return jsonify([])
    users = supabase_get("users", select="username,color", eq_column=None, eq_value=None)
    user_colors = {u["username"]: u.get("color", "#0066cc") for u in users if isinstance(u, dict)}
    for msg in messages:
        msg["author_color"] = user_colors.get(msg["author"], "#0066cc")
    return jsonify(messages)

@app.route('/api/send_group_message', methods=['POST'])
def send_group_message():
    try:
        data = request.json
        result = supabase_post("group_messages", {
            "group_id": data.get('group_id'),
            "author": data.get('author'),
            "text": data.get('text'),
            "time": data.get('time'),
            "timestamp": data.get('timestamp')
        })
        return jsonify({'success': True, 'message_id': result.get('id') if result else None})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/group_unread_count', methods=['POST'])
def group_unread_count():
    try:
        data = request.json
        username = data.get('username')
        members = supabase_get("group_members", select="group_id", eq_column="username", eq_value=username)
        if isinstance(members, dict) and "error" in members:
            return jsonify({'count': 0, 'groups': {}})
        unread_counts = {}
        total = 0
        for m in members:
            group_id = m["group_id"]
            unread_data = supabase_get("group_unread", select="last_read", eq_column="group_id", eq_value=group_id, eq_column2="username", eq_value2=username)
            last_read = 0
            if unread_data and len(unread_data) > 0:
                last_read = unread_data[0]["last_read"]
            messages = supabase_get("group_messages", select="id", eq_column="group_id", eq_value=group_id, eq_column2="timestamp", eq_value2=last_read, operator="gt")
            if messages and len(messages) > 0:
                count = len(messages)
                unread_counts[group_id] = count
                total += count
        return jsonify({'count': total, 'groups': unread_counts})
    except Exception as e:
        return jsonify({'count': 0, 'groups': {}})

@app.route('/api/mark_group_read', methods=['POST'])
def mark_group_read():
    try:
        data = request.json
        group_id = data.get('group_id')
        username = data.get('username')
        now_ms = int(time.time() * 1000)
        existing = supabase_get("group_unread", select="*", eq_column="group_id", eq_value=group_id, eq_column2="username", eq_value2=username)
        if existing and len(existing) > 0:
            supabase_patch("group_unread", "group_id", group_id, "username", username, {"last_read": now_ms})
        else:
            supabase_post("group_unread", {"group_id": group_id, "username": username, "last_read": now_ms})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/add_member', methods=['POST'])
def add_member():
    try:
        data = request.json
        group_id = data.get('group_id')
        username = data.get('username')
        creator = data.get('creator')
        group = supabase_get("groups", select="creator", eq_column="id", eq_value=group_id)
        if not group or len(group) == 0 or group[0]["creator"] != creator:
            return jsonify({'success': False, 'error': 'Только создатель может добавлять участников'})
        members = supabase_get("group_members", select="username", eq_column="group_id", eq_value=group_id)
        if len(members) >= 40:
            return jsonify({'success': False, 'error': 'В группе максимум 40 участников'})
        existing = [m for m in members if m["username"] == username]
        if existing:
            return jsonify({'success': False, 'error': 'Пользователь уже в группе'})
        now_ms = int(time.time() * 1000)
        supabase_post("group_members", {"group_id": group_id, "username": username, "joined_at": now_ms})
        supabase_post("group_unread", {"group_id": group_id, "username": username, "last_read": now_ms})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/remove_member', methods=['POST'])
def remove_member():
    try:
        data = request.json
        group_id = data.get('group_id')
        username = data.get('username')
        creator = data.get('creator')
        group = supabase_get("groups", select="creator", eq_column="id", eq_value=group_id)
        if not group or len(group) == 0 or group[0]["creator"] != creator:
            return jsonify({'success': False, 'error': 'Только создатель может удалять участников'})
        supabase_delete("group_members", "group_id", group_id, "username", username)
        supabase_delete("group_unread", "group_id", group_id, "username", username)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/leave_group', methods=['POST'])
def leave_group():
    try:
        data = request.json
        group_id = data.get('group_id')
        username = data.get('username')
        supabase_delete("group_members", "group_id", group_id, "username", username)
        supabase_delete("group_unread", "group_id", group_id, "username", username)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/delete_group', methods=['POST'])
def delete_group():
    try:
        data = request.json
        group_id = data.get('group_id')
        creator = data.get('creator')
        group = supabase_get("groups", select="creator", eq_column="id", eq_value=group_id)
        if not group or len(group) == 0 or group[0]["creator"] != creator:
            return jsonify({'success': False, 'error': 'Только создатель может удалить группу'})
        messages = supabase_get("group_messages", select="id", eq_column="group_id", eq_value=group_id)
        if messages:
            for msg in messages:
                supabase_delete("group_messages", "id", msg["id"])
        supabase_delete("group_members", "group_id", group_id)
        supabase_delete("group_unread", "group_id", group_id)
        supabase_delete("groups", "id", group_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/clear_group_chat', methods=['POST'])
def clear_group_chat():
    try:
        data = request.json
        group_id = data.get('group_id')
        creator = data.get('creator')
        group = supabase_get("groups", select="creator", eq_column="id", eq_value=group_id)
        if not group or len(group) == 0 or group[0]["creator"] != creator:
            return jsonify({'success': False, 'error': 'Только создатель может очистить чат'})
        messages = supabase_get("group_messages", select="id", eq_column="group_id", eq_value=group_id)
        if messages:
            for msg in messages:
                supabase_delete("group_messages", "id", msg["id"])
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ========== ОБЩИЙ ЧАТ API ==========

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
        supabase_post("users", {"username": username, "password": password, "is_approved": 1, "color": color, "last_active": now_ms, "last_seen": now_ms, "theme": "light"})
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
                supabase_patch("users", "username", username, "last_seen", "last_seen", {"last_active": now_ms, "last_seen": now_ms})
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
        if messages:
            for msg in messages:
                supabase_delete("messages", "id", msg["id"])
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

# ========== ЛИЧНЫЕ СООБЩЕНИЯ API ==========

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
                supabase_patch("private_messages", "id", msg["id"], "is_read", "is_read", {"is_read": True})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/unread_count', methods=['POST'])
def unread_count():
    data = request.json
    username = data.get('username')
    messages = supabase_get("private_messages", select="*", eq_column="to_user", eq_value=username)
    if isinstance(messages, dict) and "error" in messages:
        return jsonify({'count': 0, 'unread_from': []})
    unread = [m for m in messages if not m.get("is_read", False)]
    return jsonify({'count': len(unread), 'unread_from': list(set([m["from_user"] for m in unread]))})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
