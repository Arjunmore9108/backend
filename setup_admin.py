# setup_admin.py
from database import admin_collection
import bcrypt

def setup_admin():
    # Create default admin if not exists
    existing_admin = admin_collection.find_one({'username': 'admin'})
    
    if not existing_admin:
        password = 'admin123'  # Change this in production!
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        
        admin_collection.insert_one({
            'username': 'admin',
            'email': 'admin@college.edu',
            'password': hashed_password,
            'created_at': datetime.datetime.utcnow()
        })
        print("✅ Admin user created:")
        print(f"   Username: admin")
        print(f"   Password: admin123")
        print("\n⚠️  IMPORTANT: Change this password immediately!")
    else:
        print("✅ Admin user already exists")

if __name__ == '__main__':
    import datetime
    setup_admin()