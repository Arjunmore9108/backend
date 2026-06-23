from flask import request, jsonify
import bcrypt
import jwt
import datetime
from config import Config
from database import users_collection, admin_collection


# =========================
# 🔐 GENERATE TOKEN
# =========================
def generate_token(user_id, role='user'):
    payload = {
        'user_id': str(user_id),
        'role': role,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }

    token = jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm='HS256')
    return token


# =========================
# 🔍 VERIFY TOKEN (CLEAN)
# =========================
def verify_token_from_request():
    auth_header = request.headers.get("Authorization")

    if not auth_header:
        return None, "No token provided"

    try:
        # Remove "Bearer "
        token = auth_header.split(" ")[1]
    except IndexError:
        return None, "Invalid token format"

    try:
        payload = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=['HS256'])
        return payload, None

    except jwt.ExpiredSignatureError:
        return None, "Token expired"

    except jwt.InvalidTokenError:
        return None, "Invalid token"


# =========================
# 👤 AUTHENTICATE USER
# =========================
def authenticate_user(enrollment_number, password):
    user = users_collection.find_one({"enrollment_number": enrollment_number})

    if user and bcrypt.checkpw(password.encode('utf-8'), user['password']):
        return user

    return None


# =========================
# 👨‍💼 AUTHENTICATE ADMIN
# =========================
def authenticate_admin(username, password):
    admin = admin_collection.find_one({"username": username})

    if admin and bcrypt.checkpw(password.encode('utf-8'), admin['password']):
        return admin

    return None


# =========================
# 📝 REGISTER USER
# =========================
def register_user(enrollment_number, password, name, email, department):
    if users_collection.find_one({"enrollment_number": enrollment_number}):
        return None

    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

    user_data = {
        "enrollment_number": enrollment_number,
        "password": hashed_password,
        "name": name,
        "email": email,
        "department": department,
        "created_at": datetime.datetime.utcnow()
    }

    result = users_collection.insert_one(user_data)
    return str(result.inserted_id)

def verify_token_from_header(auth_header):
    try:
        if not auth_header:
            return None

        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header.split(" ")[1]

        payload = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=['HS256'])
        return payload

    except jwt.ExpiredSignatureError:
        print("❌ Token expired")
        return None
    except jwt.InvalidTokenError as e:
        print(f"❌ Invalid token: {e}")
        return None

def verify_token(token):
    try:
        payload = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        print("❌ Token expired")
        return None
    except jwt.InvalidTokenError as e:
        print(f"❌ Invalid token: {e}")
        return None