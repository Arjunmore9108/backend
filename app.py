from flask import Flask, request, jsonify
from flask_cors import CORS
from functools import wraps
import datetime
from config import Config
from database import users_collection, admin_collection, knowledge_base, unanswered_questions, conversations
from auth import authenticate_user, authenticate_admin, generate_token, verify_token, register_user
from chat_handler import ChatHandler
from werkzeug.utils import secure_filename
import PyPDF2
from PIL import Image
import pytesseract
import os
from bson import ObjectId

app = Flask(__name__)
app.config.from_object(Config)

# Fix CORS for Flutter web
CORS(app, resources={
    r"/api/*": {
        "origins": ["http://localhost:9000", "http://127.0.0.1:5000", 
                   "http://localhost:8080", "http://127.0.0.1:8080",
                   "http://localhost:8000", "http://127.0.0.1:8000",
                   "http://localhost:3000", "http://127.0.0.1:3000"],
        "methods": ["GET", "POST", "PUT", "DELETE"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

chat_handler = ChatHandler()

# Add a decorator for admin authentication
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth = request.headers.get('Authorization')
        if not auth:
            # For testing, allow without token in development
            if app.config.get('DEBUG', False):
                return f(*args, **kwargs)
            return jsonify({'success': False, 'message': 'Authorization token required'}), 401
        
        try:
            token = auth.replace('Bearer ', '')
            payload = verify_token(token)
            if not payload or payload.get('role') != 'admin':
                return jsonify({'success': False, 'message': 'Admin access required'}), 403
        except:
            return jsonify({'success': False, 'message': 'Invalid token'}), 401
        
        return f(*args, **kwargs)
    return decorated_function

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'success': True, 'message': 'Backend is healthy'})

@app.route('/api/admin/knowledge/<item_id>', methods=['DELETE'])
@admin_required
def delete_knowledge_item(item_id):
    try:
        from bson import ObjectId
        
        # Validate ObjectId
        if not ObjectId.is_valid(item_id):
            return jsonify({
                'success': False,
                'message': 'Invalid item ID'
            }), 400
        
        # Delete the document
        result = knowledge_base.delete_one({'_id': ObjectId(item_id)})
        
        if result.deleted_count > 0:
            return jsonify({
                'success': True,
                'message': 'Knowledge article deleted successfully'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Knowledge article not found'
            }), 404
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error deleting knowledge article: {str(e)}'
        }), 500
    
@app.route('/api/admin/knowledge/delete_all', methods=['DELETE'])
@admin_required
def delete_all_knowledge():
    try:
        # Get count before deletion
        count_before = knowledge_base.count_documents({})
        
        if count_before == 0:
            return jsonify({
                'success': False,
                'message': 'No knowledge articles to delete'
            }), 400
        
        # Delete all documents
        result = knowledge_base.delete_many({})
        
        return jsonify({
            'success': True,
            'message': f'Deleted all knowledge articles',
            'deleted_count': result.deleted_count,
            'count_before': count_before
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error deleting knowledge: {str(e)}'
        }), 500
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    admin = authenticate_admin(username, password)
    if admin:
        token = generate_token(str(admin['_id']), 'admin')
        return jsonify({
            'success': True,
            'token': token,
            'admin': {
                'username': admin['username'],
                'email': admin['email']
            }
        })
    
    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/api/admin/stats', methods=['GET'])
@admin_required
def get_stats():
    try:
        # Get counts from database
        total_users = users_collection.count_documents({})
        total_knowledge = knowledge_base.count_documents({})
        pending_questions = unanswered_questions.count_documents({'status': 'pending'})
        
        # Count total chats from conversations
        total_chats = conversations.count_documents({})
        
        return jsonify({
            'success': True,
            'stats': {
                'total_users': total_users,
                'total_knowledge': total_knowledge,
                'pending_questions': pending_questions,
                'total_chats': total_chats
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error fetching stats: {str(e)}'
        }), 500

@app.route('/api/admin/knowledge', methods=['GET'])
@admin_required
def get_knowledge():
    try:
        # Get all knowledge items with proper field mapping
        items = list(knowledge_base.find().sort('created_at', -1))
        
        knowledge_items = []
        for item in items:
            # Check different possible field names
            title = item.get('title') or item.get('file_name') or 'Untitled'
            content = item.get('content') or item.get('text') or item.get('data') or ''
            file_name = item.get('file_name') or item.get('filename') or 'Direct Input'
            content_type = item.get('content_type') or item.get('type') or 'text'
            
            # Create preview (first 200 characters)
            content_preview = content[:200] + '...' if len(content) > 200 else content
            
            # Format date
            created_at = item.get('created_at') or item.get('timestamp') or datetime.datetime.utcnow()
            
            knowledge_item = {
                'id': str(item['_id']),
                'title': title,
                'content': content,
                'content_preview': content_preview,
                'content_type': content_type,
                'file_name': file_name,
                'created_at': created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at)
            }
            knowledge_items.append(knowledge_item)
        
        return jsonify({
            'success': True,
            'knowledge_items': knowledge_items
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error fetching knowledge: {str(e)}'
        }), 500
    
    
def process_file_content(file, content_type):
    """Process uploaded file and extract text content"""
    try:
        if content_type == 'pdf':
            # Extract text from PDF
            pdf_reader = PyPDF2.PdfReader(file)
            text = ''
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                text += page.extract_text()
            return text
        
        elif content_type == 'image':
            # Use OCR for images
            image = Image.open(file)
            text = pytesseract.image_to_string(image)
            return text
        
        elif content_type == 'text':
            # For text files
            return file.read().decode('utf-8', errors='ignore')
            
    except Exception as e:
        print(f"Error processing file: {e}")
        return f"Error processing file: {str(e)}"

@app.route('/api/admin/upload', methods=['POST'])
@admin_required
def upload_file():
    try:
        # Get form data
        content_type = request.form.get('content_type')
        file = request.files.get('file')
        
        if not file:
            return jsonify({'success': False, 'message': 'No file provided'}), 400
        
        if not content_type:
            return jsonify({'success': False, 'message': 'Content type required'}), 400
        
        # Secure filename
        filename = secure_filename(file.filename)
        
        # Process file content
        content = process_file_content(file, content_type)
        
        # Save to database
        knowledge_item = {
            'title': filename,
            'content': content,
            'content_type': content_type,
            'file_name': filename,
            'created_at': datetime.datetime.utcnow(),
            'updated_at': datetime.datetime.utcnow()
        }
        
        result = knowledge_base.insert_one(knowledge_item)
        
        return jsonify({
            'success': True,
            'message': 'File uploaded and processed successfully',
            'knowledge_id': str(result.inserted_id)
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Upload failed: {str(e)}'
        }), 500

@app.route('/api/admin/unanswered', methods=['GET'])
@admin_required
def get_unanswered_questions():
    try:
        # Get pending questions
        questions = list(unanswered_questions.find({'status': 'pending'}).sort('created_at', -1))
        
        question_list = []
        for q in questions:
            question_item = {
                'id': str(q['_id']),
                'student_name': q.get('student_name', 'Student'),
                'enrollment_number': q.get('enrollment_number', 'Unknown'),
                'question': q.get('question', ''),
                'status': q.get('status', 'pending'),
                'created_at': q.get('created_at', datetime.datetime.utcnow()).isoformat()
            }
            question_list.append(question_item)
        
        return jsonify({
            'success': True,
            'questions': question_list
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error fetching questions: {str(e)}'
        }), 500

@app.route('/api/admin/mark_answered', methods=['POST'])
@admin_required
def mark_question_answered():
    try:
        data = request.get_json()
        question_id = data.get('question_id')
        
        if not question_id:
            return jsonify({'success': False, 'message': 'Question ID required'}), 400
        
        # Update question status
        result = unanswered_questions.update_one(
            {'_id': ObjectId(question_id)},
            {
                '$set': {
                    'status': 'answered',
                    'answered_at': datetime.datetime.utcnow(),
                    'answered_by': 'admin'
                }
            }
        )
        
        if result.modified_count > 0:
            return jsonify({
                'success': True,
                'message': 'Question marked as answered'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Question not found'
            }), 404
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error updating question: {str(e)}'
        }), 500
# Add this route to your Flask backend for editing articles
@app.route('/api/admin/knowledge/<item_id>', methods=['PUT'])
@admin_required
def update_knowledge_item(item_id):
    try:
        from bson import ObjectId
        
        # Validate ObjectId
        if not ObjectId.is_valid(item_id):
            return jsonify({
                'success': False,
                'message': 'Invalid item ID'
            }), 400
        
        # Get data from request
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'message': 'No data provided'
            }), 400
        
        # Prepare update fields
        update_fields = {
            'updated_at': datetime.datetime.utcnow()
        }
        
        # Only include fields that are provided
        if 'title' in data:
            update_fields['title'] = data['title']
        if 'content' in data:
            update_fields['content'] = data['content']
        if 'content_type' in data:
            update_fields['content_type'] = data['content_type']
        if 'file_name' in data:
            update_fields['file_name'] = data['file_name']
        if 'tags' in data:
            update_fields['tags'] = data['tags']
        
        # Update the document
        result = knowledge_base.update_one(
            {'_id': ObjectId(item_id)},
            {'$set': update_fields}
        )
        
        if result.modified_count > 0:
            # Get updated document
            updated_item = knowledge_base.find_one({'_id': ObjectId(item_id)})
            
            # Prepare response
            response_item = {
                'id': str(updated_item['_id']),
                'title': updated_item.get('title', 'Untitled'),
                'content': updated_item.get('content', ''),
                'content_preview': updated_item.get('content', '')[:200] + ('...' if len(updated_item.get('content', '')) > 200 else ''),
                'content_type': updated_item.get('content_type', 'text'),
                'file_name': updated_item.get('file_name', 'Direct Input'),
                'created_at': updated_item.get('created_at', datetime.datetime.utcnow()).isoformat(),
                'updated_at': updated_item.get('updated_at', datetime.datetime.utcnow()).isoformat()
            }
            
            return jsonify({
                'success': True,
                'message': 'Article updated successfully',
                'item': response_item
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Article not found or no changes made'
            }), 404
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error updating article: {str(e)}'
        }), 500

# Keep your existing user routes unchanged
@app.route('/api/user/login', methods=['POST'])
def user_login():
    data = request.get_json()
    enrollment_number = data.get('enrollment_number')
    password = data.get('password')
    
    user = authenticate_user(enrollment_number, password)
    if user:
        token = generate_token(str(user['_id']), 'user')
        return jsonify({
            'success': True,
            'token': token,
            'user': {
                'name': user['name'],
                'enrollment_number': user['enrollment_number'],
                'department': user['department']
            }
        })
    
    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/api/user/register', methods=['POST'])
def user_register():
    data = request.get_json()
    enrollment_number = data.get('enrollment_number')
    password = data.get('password')
    name = data.get('name')
    email = data.get('email')
    department = data.get('department')
    
    user_id = register_user(enrollment_number, password, name, email, department)
    if user_id:
        return jsonify({'success': True, 'message': 'Registration successful'})
    
    return jsonify({'success': False, 'message': 'Enrollment number already exists'}), 400

@app.route('/api/chat/send', methods=['POST'])
def send_message():
    token = request.headers.get('Authorization')
    if not token:
        return jsonify({'success': False, 'message': 'Token required'}), 401
    
    payload = verify_token(token.replace('Bearer ', ''))
    if not payload or payload['role'] != 'user':
        return jsonify({'success': False, 'message': 'Invalid token'}), 401
    
    data = request.get_json()
    message = data.get('message')
    user_id = payload['user_id']
    
    response = chat_handler.handle_query(message, user_id)
    
    conversations.update_one(
        {'user_id': user_id},
        {
            '$push': {'messages': {
                'user_message': message,
                'bot_response': response,
                'timestamp': datetime.datetime.utcnow()
            }},
            '$set': {'last_updated': datetime.datetime.utcnow()}
        },
        upsert=True
    )
    
    return jsonify({'success': True, 'response': response})

@app.route('/api/user/profile', methods=['GET'])
def get_user_profile():
    token = request.headers.get('Authorization')
    if not token:
        return jsonify({'success': False, 'message': 'Token required'}), 401
    
    payload = verify_token(token.replace('Bearer ', ''))
    if not payload or payload['role'] != 'user':
        return jsonify({'success': False, 'message': 'Invalid token'}), 401
    
    user = users_collection.find_one({'_id': ObjectId(payload['user_id'])})
    if user:
        return jsonify({
            'success': True,
            'user': {
                'name': user['name'],
                'enrollment_number': user['enrollment_number'],
                'email': user['email'],
                'department': user['department']
            }
        })
    
    return jsonify({'success': False, 'message': 'User not found'}), 404

if __name__ == '__main__':
    # Create upload directory if it doesn't exist
    upload_dir = os.path.join(os.path.dirname(__file__), 'uploads')
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
    
    app.run(debug=True, port=5000)

@app.route('/api/admin/profile', methods=['GET'])
@admin_required
def admin_profile():
    total_articles = knowledge_base.count_documents({})
    answered_questions = unanswered_questions.count_documents({'status': 'answered'})
    total_users = users_collection.count_documents({})

    return jsonify({
        'success': True,
        'profile': {
            'total_articles': total_articles,
            'answered_questions': answered_questions,
            'total_users': total_users
        }
    })