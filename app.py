import sqlite3
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

# مسار قاعدة البيانات الموجودة مسبقاً
DATABASE = "/storage/emulated/0/Termux-Backup/kasherr/kasher22/data/database.db"

def get_db_connection():
    # الاتصال بقاعدة البيانات مع تعطيل check_same_thread إذا لزم الأمر
    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# صفحة HTML متكاملة مع CSS وجافاسكريبت (تصميم متجاوب لتحسين تجربة الاستخدام على الأجهزة المحمولة)
index_html = """
<!DOCTYPE html>
<html lang="ar" data-theme="light">
<head>
  <meta charset="UTF-8">
  <title>إدارة المستخدمين والصلاحيات</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <style>
    :root {
      --main-color: #2196f3;
      --bg-light: #e3f2fd;
      --bg-dark: #1e1f26;
      --text-light: #000;
      --text-dark: #fff;
      --card-light: #fff;
      --card-dark: #2d2e35;
    }
    [data-theme="light"] {
      background: var(--bg-light);
      color: var(--text-light);
    }
    [data-theme="dark"] {
      background: var(--bg-dark);
      color: var(--text-dark);
    }
    body {
      font-family: 'Cairo', sans-serif;
      margin: 0;
      padding: 10px;
      transition: all 0.3s;
    }
    .card {
      background: var(--card-light);
      border-radius: 12px;
      padding: 15px;
      margin: 10px auto;
      box-shadow: 0 0 10px rgba(0,0,0,0.1);
      max-width: 480px;
      transition: all 0.3s;
    }
    [data-theme="dark"].card {
      background: var(--card-dark);
    }
    .field { margin-bottom: 12px; }
    .field label {
      display: block;
      font-weight: bold;
      margin-bottom: 4px;
    }
    .field input, .field select {
      width: 100%;
      padding: 8px;
      border: 1px solid #999;
      border-radius: 8px;
      font-size: 14px;
    }
    h2 {
      text-align: center;
      margin-top: 10px;
      color: var(--main-color);
    }
    .actions {
      text-align: center;
      margin-top: 10px;
    }
    .actions button {
      background: var(--main-color);
      color: white;
      padding: 8px 14px;
      margin: 4px;
      border: none;
      border-radius: 10px;
      cursor: pointer;
      font-weight: bold;
    }
    .tabs {
      display: flex;
      justify-content: center;
      gap: 10px;
      margin-bottom: 14px;
    }
    .tabs button {
      flex: 1;
      background-color: var(--main-color);
      border: none;
      color: white;
      padding: 8px;
      border-radius: 20px;
      font-weight: bold;
    }
    .toggle-theme {
      position: fixed;
      top: 10px;
      left: 10px;
      background: #555;
      color: white;
      padding: 6px 10px;
      border: none;
      border-radius: 20px;
      cursor: pointer;
      z-index: 999;
    }
    .section { display: none; }
    .section.active { display: block; }
    table {
      border-collapse: collapse;
      width: 100%;
      margin-top: 10px;
    }
    th, td {
      padding: 6px;
      border-bottom: 1px solid #ccc;
      text-align: center;
    }
  </style>
</head>
<body onload="loadUsers()">
  <button class="toggle-theme" onclick="toggleTheme()">🌓</button>
  <h2>نظام إدارة المستخدمين</h2>

  <div class="tabs">
    <button onclick="switchSection('user')">👤 المستخدم</button>
    <button onclick="switchSection('permissions')">🔐 الصلاحيات</button>
    <button onclick="switchSection('activate-permission')">🧩 تفعيل الصلاحيات</button>
  </div>

  <!-- قسم المستخدم -->
  <div id="user" class="card section active">
    <div class="field">
      <label>رقم المستخدم</label>
      <input id="user_id" placeholder="مثال: 1">
    </div>
    <div class="field">
      <label>اسم المستخدم</label>
      <input id="username" placeholder="مثال: احمد">
    </div>
    <div class="field">
      <label>كلمة المرور</label>
      <input id="password" type="password" placeholder="كلمة المرور">
    </div>
    <div class="field">
      <label>الكيان</label>
      <input id="entity_id" placeholder="مثال: 100">
    </div>
    <div class="field">
      <label>نشط؟</label>
      <select id="is_active">
        <option value="1">نعم</option>
        <option value="0">لا</option>
      </select>
    </div>
    <div class="actions">
      <button onclick="saveUser()">💾 حفظ</button>
      <button onclick="queryUserPermissions()">🔍 استعلام صلاحيات</button>
    </div>

    <div class="users-table">
      <h3 style="text-align:center;">📋 المستخدمون المسجلون</h3>
      <table id="usersTable">
        <thead>
          <tr>
            <th>الرقم</th>
            <th>الاسم</th>
            <th>الكيان</th>
            <th>نشط؟</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  </div>

  <!-- قسم الصلاحيات -->
  <div id="permissions" class="card section">
    <div class="field">
      <label>رقم الصلاحية</label>
      <input id="perm_id" placeholder="مثال: 10">
    </div>
    <div class="field">
      <label>اسم الصلاحية</label>
      <input id="perm_name" placeholder="مثال: تعديل">
    </div>
    <div class="field">
      <label>الوصف</label>
      <input id="perm_desc" placeholder="مثال: تعديل البيانات">
    </div>
    <div class="field">
      <label>الوحدة</label>
      <input id="perm_module" placeholder="مثال: مستخدم">
    </div>
    <div class="field">
      <label>الإجراء</label>
      <select id="perm_action">
        <option>عرض</option>
        <option>إضافة</option>
        <option>تعديل</option>
        <option>حذف</option>
      </select>
    </div>
    <div class="field">
      <label>اسم الشاشة</label>
      <input id="perm_screen" placeholder="مثال: شاشة المستخدم">
    </div>
    <div class="actions">
      <button onclick="savePermission()">💾 حفظ</button>
    </div>
  </div>

  <!-- قسم تفعيل الصلاحيات -->
  <div id="activate-permission" class="card section">
    <div class="field">
      <label>🔁 رقم المستخدم</label>
      <input id="ref_user_id" placeholder="رقم المستخدم">
    </div>
    <div class="field">
      <label>رقم الصلاحية</label>
      <input id="map_perm_id" placeholder="رقم الصلاحية">
    </div>
    <div class="actions">
      <button onclick="saveUserPermission()">💾 حفظ</button>
      <button onclick="deleteUserPermission()">🗑 حذف</button>
      <button onclick="queryUserPermissionMapping()">🔍 استعلام</button>
    </div>
    <div id="userPermissionsResult"></div>
  </div>

  <script>
    // تبديل الثيم بين الفاتح والداكن
    function toggleTheme() {
      const html = document.documentElement;
      html.dataset.theme = html.dataset.theme === 'dark' ? 'light' : 'dark';
    }

    // تبديل الأقسام المعروضة
    function switchSection(id) {
      document.querySelectorAll('.section').forEach(div => div.classList.remove('active'));
      document.getElementById(id).classList.add('active');
    }

    // حفظ المستخدم عبر واجهة API
    async function saveUser() {
      const data = {
        user_id: document.getElementById('user_id').value,
        username: document.getElementById('username').value,
        password: document.getElementById('password').value,
        entity_id: document.getElementById('entity_id').value,
        is_active: document.getElementById('is_active').value
      };
      const res = await fetch('/api/user', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      if (res.ok) {
        alert('✅ تم حفظ المستخدم');
        loadUsers();
      } else {
        alert('❌ خطأ في حفظ المستخدم');
      }
    }

    // حفظ الصلاحية عبر API
    async function savePermission() {
      const data = {
        permission_id: document.getElementById('perm_id').value,
        permission_name: document.getElementById('perm_name').value,
        description: document.getElementById('perm_desc').value,
        module: document.getElementById('perm_module').value,
        action_type: document.getElementById('perm_action').value,
        screen_name: document.getElementById('perm_screen').value
      };
      const res = await fetch('/api/permission', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      if (res.ok) {
        alert('✅ تم حفظ الصلاحية');
      } else {
        alert('❌ خطأ في حفظ الصلاحية');
      }
    }

    // تحميل واستعراض قائمة المستخدمين في الجدول
    async function loadUsers() {
      const res = await fetch('/api/users');
      const users = await res.json();
      const table = document.querySelector("#usersTable tbody");
      table.innerHTML = "";
      users.forEach(u => {
        const row = document.createElement('tr');
        row.innerHTML = `<td>${u.user_id}</td>
                         <td>${u.username}</td>
                         <td>${u.entity_id}</td>
                         <td>${u.is_active == 1 ? 'نعم' : 'لا'}</td>`;
        table.appendChild(row);
      });
    }

    // حفظ علاقة صلاحيات المستخدم عبر API
    async function saveUserPermission() {
      const data = {
        user_id: document.getElementById('ref_user_id').value,
        permission_id: document.getElementById('map_perm_id').value
      };
      const res = await fetch('/api/user_permission', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      if (res.ok) {
        alert('✅ تم حفظ صلاحية المستخدم');
      } else {
        alert('❌ خطأ في حفظ صلاحية المستخدم');
      }
    }

    // حذف علاقة صلاحيات المستخدم عبر API
    async function deleteUserPermission() {
      const data = {
        user_id: document.getElementById('ref_user_id').value,
        permission_id: document.getElementById('map_perm_id').value
      };
      const res = await fetch('/api/user_permission', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      if (res.ok) {
        alert('✅ تم حذف صلاحية المستخدم');
      } else {
        alert('❌ خطأ في حذف صلاحية المستخدم');
      }
    }

    // استعلام وعرض صلاحيات المستخدم عبر واجهة API
    async function queryUserPermissionMapping() {
      const userId = document.getElementById('ref_user_id').value;
      const res = await fetch('/api/user_permission?user_id=' + userId);
      const result = await res.json();
      let html = "<h4>الصلاحيات المفعلة:</h4><ul>";
      result.forEach(item => {
         html += `<li>رقم الصلاحية: ${item.permission_id}</li>`;
      });
      html += "</ul>";
      document.getElementById('userPermissionsResult').innerHTML = html;
    }
    // استخدام نفس الدالة للاستعلام عن صلاحيات المستخدم
    function queryUserPermissions() {
      queryUserPermissionMapping();
    }
  </script>
</body>
</html>
"""

# تقديم الصفحة الرئيسية
@app.route("/")
def index():
    return render_template_string(index_html)

# API لحفظ المستخدم (يستخدم INSERT OR REPLACE لتحديث البيانات إذا كانت موجودة)
@app.route("/api/user", methods=["POST"])
def api_save_user():
    data = request.get_json()
    if not data or 'user_id' not in data:
        return jsonify({"error": "Invalid data"}), 400
    user_id   = data.get("user_id")
    username  = data.get("username")
    password  = data.get("password")
    entity_id = data.get("entity_id")
    is_active = int(data.get("is_active"))
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO users (user_id, username, password, entity_id, is_active) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, password, entity_id, is_active)
        )
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500
    conn.close()
    return jsonify({"message": "User saved"}), 200

# API لاسترجاع قائمة المستخدمين
@app.route("/api/users", methods=["GET"])
def api_get_users():
    conn = get_db_connection()
    users_rows = conn.execute("SELECT * FROM users").fetchall()
    conn.close()
    users_list = [dict(row) for row in users_rows]
    return jsonify(users_list), 200

# API لحفظ الصلاحية
@app.route("/api/permission", methods=["POST"])
def api_save_permission():
    data = request.get_json()
    if not data or "permission_id" not in data:
        return jsonify({"error": "Invalid data"}), 400
    permission_id   = data.get("permission_id")
    permission_name = data.get("permission_name")
    description     = data.get("description")
    module          = data.get("module")
    action_type     = data.get("action_type")
    screen_name     = data.get("screen_name")
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO permissions (permission_id, permission_name, description, module, action_type, screen_name) VALUES (?, ?, ?, ?, ?, ?)",
            (permission_id, permission_name, description, module, action_type, screen_name)
        )
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500
    conn.close()
    return jsonify({"message": "Permission saved"}), 200

# API لإدارة علاقة صلاحيات المستخدم (POST: إضافة، DELETE: حذف، GET: استعلام)
@app.route("/api/user_permission", methods=["POST", "DELETE", "GET"])
def api_user_permission():
    if request.method == "POST":
        data = request.get_json()
        if not data or "user_id" not in data or "permission_id" not in data:
            return jsonify({"error": "Invalid data"}), 400
        user_id = data.get("user_id")
        perm_id = data.get("permission_id")
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO user_permissions (user_id, permission_id) VALUES (?, ?)",
                (user_id, perm_id)
            )
            conn.commit()
        except Exception as e:
            conn.close()
            return jsonify({"error": str(e)}), 500
        conn.close()
        return jsonify({"message": "User Permission mapping saved"}), 200

    elif request.method == "DELETE":
        data = request.get_json()
        if not data or "user_id" not in data or "permission_id" not in data:
            return jsonify({"error": "Invalid data"}), 400
        user_id = data.get("user_id")
        perm_id = data.get("permission_id")
        conn = get_db_connection()
        try:
            cur = conn.execute(
                "DELETE FROM user_permissions WHERE user_id = ? AND permission_id = ?",
                (user_id, perm_id)
            )
            conn.commit()
            if cur.rowcount == 0:
                conn.close()
                return jsonify({"error": "Mapping not found"}), 404
        except Exception as e:
            conn.close()
            return jsonify({"error": str(e)}), 500
        conn.close()
        return jsonify({"message": "User Permission mapping deleted"}), 200

    else:  # GET: استعلام صلاحيات المستخدم بناءً على user_id
        user_id = request.args.get("user_id")
        if not user_id:
            return jsonify({"error": "User ID required"}), 400
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT permission_id FROM user_permissions WHERE user_id = ?",
            (user_id,)
        ).fetchall()
        conn.close()
        perms = [{"permission_id": row["permission_id"]} for row in rows]
        return jsonify(perms), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
