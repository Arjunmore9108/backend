from pymongo import MongoClient
from config import Config
import bcrypt

client = MongoClient(Config.MONGODB_URI)
db = client.college_helpdesk

users_collection = db.users
admin_collection = db.admins
knowledge_base = db.knowledge_base
unanswered_questions = db.unanswered_questions
conversations = db.conversations
total_articles = knowledge_base.count_documents({})

def init_db():
    try:
        admin_exists = admin_collection.find_one({"username": "admin"})
        if not admin_exists:
            hashed_password = bcrypt.hashpw("admin123".encode('utf-8'), bcrypt.gensalt())
            admin_collection.insert_one({
                "username": "admin",
                "password": hashed_password,
                "email": "admin@college.edu",
                "role": "admin"
            })
            print("Default admin created: admin/admin123")
        
        client.admin.command('ping')
        print("Database connected successfully")
    except Exception as e:
        print(f"Database connection failed: {e}")

init_db()