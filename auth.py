from flask import jsonify
import bcrypt
import jwt
import datetime
from config import Config
from database import users_collection, admin_collection

def generate_token(user_id, role='user'):
    payload = {
        'user_id': user_id,
        'role': role,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }
    return jwt.encode(payload, Config.SECRET_KEY, algorithm='HS256')

def verify_token(token):
    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def authenticate_user(enrollment_number, password):
    user = users_collection.find_one({"enrollment_number": enrollment_number})
    if user and bcrypt.checkpw(password.encode('utf-8'), user['password']):
        return user
    return None

def authenticate_admin(username, password):
    admin = admin_collection.find_one({"username": username})
    if admin and bcrypt.checkpw(password.encode('utf-8'), admin['password']):
        return admin
    return None

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