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
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)

# Fix CORS for all origins during development
CORS(app, resources={r"/api/*": {"origins": "*"}})
# Initialize chat handler
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
        except Exception as e:
            logger.error(f"Token verification error: {e}")
            return jsonify({'success': False, 'message': 'Invalid token'}), 401
        
        return f(*args, **kwargs)
    return decorated_function

# Health Check
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        'success': True, 
        'message': 'Backend is healthy',
        'timestamp': datetime.datetime.utcnow().isoformat()
    })

# Admin Authentication
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'success': False, 'message': 'Username and password required'}), 400
        
        admin = authenticate_admin(username, password)
        if admin:
            token = generate_token(str(admin['_id']), 'admin')
            return jsonify({
                'success': True,
                'token': token,
                'admin': {
                    'username': admin['username'],
                    'email': admin.get('email', 'admin@college.edu')
                }
            })
        
        return jsonify({'success': False, 'message': 'Invalid credentials'}), 401
    except Exception as e:
        logger.error(f"Admin login error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# Admin Stats Dashboard
@app.route('/api/admin/stats', methods=['GET'])
def get_admin_stats():
    try:
        logger.info("Fetching admin stats...")
        
        # Get counts with error handling
        total_knowledge = knowledge_base.count_documents({})
        logger.info(f"Total knowledge: {total_knowledge}")
        
        # Try different possible field names for pending questions
        try:
            pending_questions = unanswered_questions.count_documents({'status': 'pending'})
        except:
            try:
                pending_questions = unanswered_questions.count_documents({'answered': False})
            except:
                try:
                    pending_questions = unanswered_questions.count_documents({})
                except:
                    pending_questions = 0
        
        logger.info(f"Pending questions: {pending_questions}")
        
        total_users = users_collection.count_documents({})
        logger.info(f"Total users: {total_users}")
        
        # Handle conversations collection (might not exist yet)
        try:
            total_chats = conversations.count_documents({})
        except Exception as e:
            logger.warning(f"Conversations collection error: {e}")
            total_chats = 0
        
        logger.info(f"Total chats: {total_chats}")

        return jsonify({
            "success": True,
            "stats": {
                "knowledge_items": total_knowledge,
                "total_knowledge": total_knowledge,
                "pending_questions": pending_questions,
                "total_users": total_users,
                "total_chats": total_chats
            }
        })

    except Exception as e:
        logger.error(f"Error in get_admin_stats: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# Admin Profile
@app.route('/api/admin/profile', methods=['GET'])
@admin_required
def admin_profile():
    try:
        total_articles = knowledge_base.count_documents({})
        answered_questions = unanswered_questions.count_documents({'status': 'answered'})
        pending_questions = unanswered_questions.count_documents({'status': 'pending'})
        total_users = users_collection.count_documents({})

        return jsonify({
            'success': True,
            'profile': {
                'total_articles': total_articles,
                'answered_questions': answered_questions,
                'pending_questions': pending_questions,
                'total_users': total_users
            }
        })
    except Exception as e:
        logger.error(f"Admin profile error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# Knowledge Base Management
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
            
            # Add updated_at if exists
            if 'updated_at' in item:
                knowledge_item['updated_at'] = item['updated_at'].isoformat() if hasattr(item['updated_at'], 'isoformat') else str(item['updated_at'])
            
            knowledge_items.append(knowledge_item)
        
        return jsonify({
            'success': True,
            'knowledge_items': knowledge_items
        })
    except Exception as e:
        logger.error(f"Error fetching knowledge: {e}")
        return jsonify({
            'success': False,
            'message': f'Error fetching knowledge: {str(e)}'
        }), 500

@app.route('/api/admin/knowledge/<item_id>', methods=['GET'])
@admin_required
def get_knowledge_item(item_id):
    try:
        # Validate ObjectId
        if not ObjectId.is_valid(item_id):
            return jsonify({
                'success': False,
                'message': 'Invalid item ID'
            }), 400
        
        # Get the item
        item = knowledge_base.find_one({'_id': ObjectId(item_id)})
        
        if not item:
            return jsonify({
                'success': False,
                'message': 'Knowledge article not found'
            }), 404
        
        # Format the response
        knowledge_item = {
            'id': str(item['_id']),
            'title': item.get('title', 'Untitled'),
            'content': item.get('content', ''),
            'content_type': item.get('content_type', 'text'),
            'file_name': item.get('file_name', 'Direct Input'),
            'created_at': item.get('created_at', datetime.datetime.utcnow()).isoformat() if hasattr(item.get('created_at'), 'isoformat') else str(item.get('created_at')),
            'updated_at': item.get('updated_at', datetime.datetime.utcnow()).isoformat() if hasattr(item.get('updated_at'), 'isoformat') else str(item.get('updated_at'))
        }
        
        return jsonify({
            'success': True,
            'item': knowledge_item
        })
        
    except Exception as e:
        logger.error(f"Error fetching knowledge item: {e}")
        return jsonify({
            'success': False,
            'message': f'Error fetching knowledge article: {str(e)}'
        }), 500

@app.route('/api/admin/knowledge/<item_id>', methods=['PUT'])
@admin_required
def update_knowledge_item(item_id):
    try:
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
        if 'title' in data and data['title']:
            update_fields['title'] = data['title']
        if 'content' in data and data['content']:
            update_fields['content'] = data['content']
        if 'content_type' in data and data['content_type']:
            update_fields['content_type'] = data['content_type']
        if 'file_name' in data and data['file_name']:
            update_fields['file_name'] = data['file_name']
        
        # Update the document
        result = knowledge_base.update_one(
            {'_id': ObjectId(item_id)},
            {'$set': update_fields}
        )
        
        if result.matched_count == 0:
            return jsonify({
                'success': False,
                'message': 'Knowledge article not found'
            }), 404
        
        if result.modified_count > 0 or result.matched_count > 0:
            # Get updated document
            updated_item = knowledge_base.find_one({'_id': ObjectId(item_id)})
            
            # Prepare response
            response_item = {
                'id': str(updated_item['_id']),
                'title': updated_item.get('title', 'Untitled'),
                'content': updated_item.get('content', ''),
                'content_preview': (updated_item.get('content', '')[:200] + '...') if len(updated_item.get('content', '')) > 200 else updated_item.get('content', ''),
                'content_type': updated_item.get('content_type', 'text'),
                'file_name': updated_item.get('file_name', 'Direct Input'),
                'created_at': updated_item.get('created_at', datetime.datetime.utcnow()).isoformat() if hasattr(updated_item.get('created_at'), 'isoformat') else str(updated_item.get('created_at')),
                'updated_at': updated_item.get('updated_at', datetime.datetime.utcnow()).isoformat() if hasattr(updated_item.get('updated_at'), 'isoformat') else str(updated_item.get('updated_at'))
            }
            
            return jsonify({
                'success': True,
                'message': 'Article updated successfully',
                'item': response_item
            })
        else:
            return jsonify({
                'success': True,
                'message': 'No changes made to the article',
                'item': {
                    'id': item_id
                }
            })
            
    except Exception as e:
        logger.error(f"Error updating article: {e}")
        return jsonify({
            'success': False,
            'message': f'Error updating article: {str(e)}'
        }), 500

@app.route('/api/admin/knowledge/<item_id>', methods=['DELETE'])
@admin_required
def delete_knowledge_item(item_id):
    try:
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
        logger.error(f"Error deleting knowledge article: {e}")
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
        logger.error(f"Error deleting all knowledge: {e}")
        return jsonify({
            'success': False,
            'message': f'Error deleting knowledge: {str(e)}'
        }), 500
# File Upload and Processing
def process_file_content(file, content_type):
    """Process uploaded file and extract text content"""
    try:
        if content_type == 'pdf':
            # Extract text from PDF
            pdf_reader = PyPDF2.PdfReader(file)
            text = ''
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
            return text if text else "No text could be extracted from PDF"
        
        elif content_type == 'image':
            # Use OCR for images
            try:
                image = Image.open(file)
                text = pytesseract.image_to_string(image)
                return text if text else "No text could be extracted from image"
            except Exception as e:
                logger.error(f"OCR error: {e}")
                return f"OCR processing error: {str(e)}"
        
        elif content_type == 'text':
            # For text files
            try:
                return file.read().decode('utf-8', errors='ignore')
            except:
                # Try different encoding
                file.seek(0)
                return file.read().decode('latin-1', errors='ignore')
        
        elif content_type == 'document':
            # For Word documents - basic text extraction
            try:
                return file.read().decode('utf-8', errors='ignore')
            except:
                return "Document processing - text extraction limited"
        
        else:
            return f"Content type {content_type} not supported for processing"
            
    except Exception as e:
        logger.error(f"Error processing file: {e}")
        return f"Error processing file: {str(e)}"

@app.route('/api/admin/upload', methods=['POST'])
@admin_required
def upload_file():
    try:
        # Get form data
        content_type = request.form.get('content_type')
        file = request.files.get('file')
        custom_title = request.form.get('title', '')
        
        if not file:
            return jsonify({'success': False, 'message': 'No file provided'}), 400
        
        if not content_type:
            return jsonify({'success': False, 'message': 'Content type required'}), 400
        
        # Secure filename
        filename = secure_filename(file.filename)
        
        # Process file content
        content = process_file_content(file, content_type)
        
        # Use custom title if provided, otherwise use filename
        title = custom_title if custom_title else filename
        
        # Save to database
        knowledge_item = {
            'title': title,
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
        logger.error(f"Upload failed: {e}")
        return jsonify({
            'success': False,
            'message': f'Upload failed: {str(e)}'
        }), 500

# Questions Management
@app.route('/api/admin/unanswered', methods=['GET'])
@admin_required
def get_unanswered_questions():
    try:
        # Get pending questions - try different possible status fields
        try:
            questions = list(unanswered_questions.find({'status': 'pending'}).sort('created_at', -1))
        except:
            try:
                questions = list(unanswered_questions.find({'answered': False}).sort('created_at', -1))
            except:
                questions = list(unanswered_questions.find().sort('created_at', -1).limit(50))
        
        question_list = []
        for q in questions:
            # Handle different possible field names
            student_name = q.get('student_name') or q.get('name') or q.get('user_name') or 'Student'
            enrollment = q.get('enrollment_number') or q.get('enrollment') or q.get('student_id') or 'Unknown'
            question_text = q.get('question') or q.get('text') or q.get('message') or ''
            status = q.get('status') or ('pending' if not q.get('answered', True) else 'answered')
            
            # Format date
            created_at = q.get('created_at') or q.get('timestamp') or datetime.datetime.utcnow()
            
            question_item = {
                'id': str(q['_id']),
                'student_name': student_name,
                'enrollment_number': enrollment,
                'question': question_text,
                'status': status,
                'created_at': created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at)
            }
            question_list.append(question_item)
        
        return jsonify({
            'success': True,
            'questions': question_list
        })
    except Exception as e:
        logger.error(f"Error fetching questions: {e}")
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
        
        # Validate ObjectId
        if not ObjectId.is_valid(question_id):
            return jsonify({'success': False, 'message': 'Invalid question ID'}), 400
        
        # Try to update with different field names
        try:
            # Try status field first
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
        except:
            try:
                # Try answered boolean field
                result = unanswered_questions.update_one(
                    {'_id': ObjectId(question_id)},
                    {
                        '$set': {
                            'answered': True,
                            'answered_at': datetime.datetime.utcnow(),
                            'answered_by': 'admin'
                        }
                    }
                )
            except:
                return jsonify({
                    'success': False,
                    'message': 'Could not update question status'
                }), 500
        
        if result.modified_count > 0:
            return jsonify({
                'success': True,
                'message': 'Question marked as answered'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Question not found or already answered'
            }), 404
            
    except Exception as e:
        logger.error(f"Error updating question: {e}")
        return jsonify({
            'success': False,
            'message': f'Error updating question: {str(e)}'
        }), 500

# User Authentication
@app.route('/api/user/login', methods=['POST'])
def user_login():
    try:
        data = request.get_json()
        enrollment_number = data.get('enrollment_number')
        password = data.get('password')
        
        if not enrollment_number or not password:
            return jsonify({'success': False, 'message': 'Enrollment number and password required'}), 400
        
        user = authenticate_user(enrollment_number, password)
        if user:
            token = generate_token(str(user['_id']), 'user')
            return jsonify({
                'success': True,
                'token': token,
                'user': {
                    'name': user.get('name', 'Student'),
                    'enrollment_number': user.get('enrollment_number', enrollment_number),
                    'department': user.get('department', 'Unknown')
                }
            })
        
        return jsonify({'success': False, 'message': 'Invalid credentials'}), 401
    except Exception as e:
        logger.error(f"User login error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/user/register', methods=['POST'])
def user_register():
    try:
        data = request.get_json()
        enrollment_number = data.get('enrollment_number')
        password = data.get('password')
        name = data.get('name')
        email = data.get('email')
        department = data.get('department')
        
        # Validate required fields
        if not all([enrollment_number, password, name]):
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400
        
        user_id = register_user(enrollment_number, password, name, email, department)
        if user_id:
            return jsonify({'success': True, 'message': 'Registration successful'})
        
        return jsonify({'success': False, 'message': 'Enrollment number already exists'}), 400
    except Exception as e:
        logger.error(f"User registration error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/user/profile', methods=['GET'])
def get_user_profile():
    try:
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'success': False, 'message': 'Token required'}), 401
        
        payload = verify_token(token.replace('Bearer ', ''))
        if not payload or payload.get('role') != 'user':
            return jsonify({'success': False, 'message': 'Invalid token'}), 401
        
        user = users_collection.find_one({'_id': ObjectId(payload['user_id'])})
        if user:
            return jsonify({
                'success': True,
                'user': {
                    'name': user.get('name', 'Student'),
                    'enrollment_number': user.get('enrollment_number', ''),
                    'email': user.get('email', ''),
                    'department': user.get('department', '')
                }
            })
        
        return jsonify({'success': False, 'message': 'User not found'}), 404
    except Exception as e:
        logger.error(f"User profile error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# Chat Endpoints
@app.route('/api/chat/send', methods=['POST', 'OPTIONS'])
def send_message():
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        return '', 200

    try:
        print("\n" + "="*50)
        print("📨 New chat message received")
        
        token = request.headers.get('Authorization')
        if not token:
            print("❌ No token provided")
            return jsonify({'success': False, 'message': 'Token required'}), 401
        
        print(f"Token: {token[:20]}...")
        
        payload = verify_token(token.replace('Bearer ', ''))
        if not payload or payload.get('role') != 'user':
            print(f"❌ Invalid token payload: {payload}")
            return jsonify({'success': False, 'message': 'Invalid token'}), 401
        
        user_id = payload['user_id']
        print(f"✅ User authenticated: {user_id}")
        
        data = request.get_json()
        message = data.get('message')
        if not message:
            print("❌ No message provided")
            return jsonify({'success': False, 'message': 'Message required'}), 400
        
        print(f"💬 User message: {message}")
        
        # Get response from chat handler (this will automatically save unanswered)
        print("🤖 Calling chat handler...")
        response = chat_handler.handle_query(message, user_id)
        print(f"✅ Chat handler response: {response[:100]}...")
        
        # Store in conversations
        try:
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
            print("✅ Conversation saved")
        except Exception as e:
            logger.warning(f"Could not save conversation: {e}")
        
        print("="*50 + "\n")
        return jsonify({'success': True, 'response': response})
        
    except Exception as e:
        print(f"❌ Chat error: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
@app.route('/api/chat/history/<user_id>', methods=['GET'])
def get_chat_history(user_id):
    try:
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'success': False, 'message': 'Token required'}), 401
        token = request.headers.get('Authorization')
        payload = verify_token(token.replace('Bearer ', ''))
        if not payload or payload.get('role') != 'user':
            return jsonify({'success': False, 'message': 'Invalid token'}), 401
        
        # Get conversation
        conversation = conversations.find_one({'user_id': user_id})
        
        if conversation and 'messages' in conversation:
            return jsonify({
                'success': True,
                'history': conversation['messages']
            })
        
        return jsonify({
            'success': True,
            'history': []
        })
    except Exception as e:
        logger.error(f"Chat history error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
# NEW: Manual Answer Feature - Add this at the end of your app.py
@app.route('/api/admin/manual_answer', methods=['POST'])
@admin_required
def manual_answer():
    """
    New endpoint for admin to manually answer questions
    This works alongside the existing AI answer feature
    """
    try:
        data = request.get_json()
        question_id = data.get('question_id')
        answer_text = data.get('answer')
        
        if not question_id or not answer_text:
            return jsonify({
                'success': False, 
                'message': 'Question ID and answer text required'
            }), 400
        
        # Validate ObjectId
        if not ObjectId.is_valid(question_id):
            return jsonify({'success': False, 'message': 'Invalid question ID'}), 400
        
        # Get the original question
        question = unanswered_questions.find_one({'_id': ObjectId(question_id)})
        
        if not question:
            return jsonify({
                'success': False, 
                'message': 'Question not found'
            }), 404
        
        # Extract student info
        student_id = question.get('user_id') or question.get('student_id')
        student_name = question.get('student_name') or question.get('name') or 'Student'
        enrollment = question.get('enrollment_number') or question.get('enrollment') or 'Unknown'
        
        # Store the manual answer
        answer_record = {
            'question_id': question_id,
            'original_question': question.get('question') or question.get('text') or '',
            'answer': answer_text,
            'answered_by': 'admin',
            'answered_at': datetime.datetime.utcnow(),
            'method': 'manual',
            'user_id': student_id,
            'enrollment': enrollment
        }
        
        # Save to a new collection for answered questions
        from database import db
        if 'manual_answers' not in db.list_collection_names():
            db.create_collection('manual_answers')
        
        db.manual_answers.insert_one(answer_record)
        
        # Also save to the student's conversation history
        if student_id:
            try:
                conversations.update_one(
                    {'user_id': student_id},
                    {
                        '$push': {'messages': {
                            'user_message': question.get('question') or question.get('text') or '',
                            'bot_response': answer_text,
                            'timestamp': datetime.datetime.utcnow(),
                            'answer_type': 'manual'
                        }},
                        '$set': {'last_updated': datetime.datetime.utcnow()}
                    },
                    upsert=True
                )
            except Exception as e:
                logger.warning(f"Could not save to conversations: {e}")
        
        # Mark the question as answered in the original collection
        try:
            unanswered_questions.update_one(
                {'_id': ObjectId(question_id)},
                {
                    '$set': {
                        'status': 'answered',
                        'answered': True,
                        'answered_at': datetime.datetime.utcnow(),
                        'answered_by': 'admin',
                        'answer_method': 'manual',
                        'manual_answer': answer_text
                    }
                }
            )
        except Exception as e:
            logger.error(f"Could not update original question: {e}")
        
        return jsonify({
            'success': True,
            'message': 'Answer sent successfully',
            'data': {
                'question_id': question_id,
                'student_name': student_name,
                'enrollment': enrollment
            }
        })
        
    except Exception as e:
        logger.error(f"Error in manual answer: {e}")
        return jsonify({
            'success': False,
            'message': f'Error sending answer: {str(e)}'
        }), 500

@app.route('/api/admin/manual_answers', methods=['GET'])
@admin_required
def get_manual_answers():
    """
    Get all manually answered questions (optional)
    """
    try:
        from database import db
        
        # Get all manual answers from the new collection
        if 'manual_answers' in db.list_collection_names():
            answers = list(db.manual_answers.find().sort('answered_at', -1))
            
            result = []
            for ans in answers:
                result.append({
                    'id': str(ans['_id']),
                    'question_id': ans.get('question_id', ''),
                    'original_question': ans.get('original_question', ''),
                    'answer': ans.get('answer', ''),
                    'answered_at': ans.get('answered_at', datetime.datetime.utcnow()).isoformat() if hasattr(ans.get('answered_at'), 'isoformat') else str(ans.get('answered_at')),
                    'method': ans.get('method', 'manual')
                })
            
            return jsonify({
                'success': True,
                'answers': result
            })
        
        return jsonify({
            'success': True,
            'answers': []
        })
        
    except Exception as e:
        logger.error(f"Error fetching manual answers: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/admin/question/<question_id>', methods=['GET'])
@admin_required
def get_question_details(question_id):
    """
    Get detailed information about a specific question
    """
    try:
        if not ObjectId.is_valid(question_id):
            return jsonify({'success': False, 'message': 'Invalid question ID'}), 400
        
        question = unanswered_questions.find_one({'_id': ObjectId(question_id)})
        
        if not question:
            return jsonify({'success': False, 'message': 'Question not found'}), 404
        
        # Format the response
        question_data = {
            'id': str(question['_id']),
            'student_name': question.get('student_name') or question.get('name') or 'Student',
            'enrollment_number': question.get('enrollment_number') or question.get('enrollment') or 'Unknown',
            'question': question.get('question') or question.get('text') or '',
            'status': question.get('status', 'pending'),
            'created_at': question.get('created_at', datetime.datetime.utcnow()).isoformat() if hasattr(question.get('created_at'), 'isoformat') else str(question.get('created_at'))
        }
        
        # Add any additional fields that might exist
        if 'user_id' in question:
            question_data['user_id'] = question['user_id']
        if 'email' in question:
            question_data['email'] = question['email']
        
        return jsonify({
            'success': True,
            'question': question_data
        })
        
    except Exception as e:
        logger.error(f"Error fetching question details: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

# ============================================
# NEW: User Question Endpoints
# ============================================

@app.route('/api/user/ask', methods=['POST', 'OPTIONS'])
def ask_question():
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', 'http://localhost:8080')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'POST,OPTIONS')
        return response

    try:
        # Verify token
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'success': False, 'message': 'Token required'}), 401
        token = request.headers.get('Authorization')
        payload = verify_token(token.replace('Bearer ', ''))
        if not payload or payload.get('role') != 'user':
            return jsonify({'success': False, 'message': 'Invalid token'}), 401
        
        user_id = payload['user_id']
        
        # Get request data
        data = request.get_json()
        question = data.get('question')
        student_name = data.get('student_name', 'Student')
        enrollment_number = data.get('enrollment_number', '')
        
        if not question:
            return jsonify({'success': False, 'message': 'Question required'}), 400
        
        # Save to unanswered_questions collection
        question_doc = {
            'user_id': user_id,
            'student_name': student_name,
            'enrollment_number': enrollment_number,
            'question': question,
            'status': 'pending',
            'created_at': datetime.datetime.utcnow(),
            'answered': False
        }
        
        result = unanswered_questions.insert_one(question_doc)
        
        return jsonify({
            'success': True,
            'message': 'Question submitted successfully',
            'question_id': str(result.inserted_id)
        })
        
    except Exception as e:
        logger.error(f"Error submitting question: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/user/pending', methods=['GET', 'OPTIONS'])
def get_user_pending_questions():
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', 'http://localhost:8080')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET,OPTIONS')
        return response

    try:
        # Verify token
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'success': False, 'message': 'Token required'}), 401
        token = request.headers.get('Authorization')
        payload = verify_token(token.replace('Bearer ', ''))
        if not payload or payload.get('role') != 'user':
            return jsonify({'success': False, 'message': 'Invalid token'}), 401
        
        user_id = payload['user_id']
        
        # Get ALL questions for this user (both pending and answered)
        questions = list(unanswered_questions.find({
            'user_id': user_id
        }).sort('created_at', -1))
        
        print(f"Found {len(questions)} total questions for user {user_id}")
        
        question_list = []
        for q in questions:
            # Check if this question has been answered (look in manual_answers)
            answer = None
            from database import db
            
            # Try to find manual answer
            if 'manual_answers' in db.list_collection_names():
                manual_answer = db.manual_answers.find_one({'question_id': str(q['_id'])})
                if manual_answer:
                    answer = manual_answer.get('answer')
            
            # Determine status
            status = 'answered' if answer else 'pending'
            
            question_list.append({
                'id': str(q['_id']),
                'question': q.get('question', q.get('text', '')),
                'status': status,
                'created_at': q.get('created_at', datetime.datetime.utcnow()).isoformat(),
                'answer': answer
            })
        
        return jsonify({
            'success': True,
            'questions': question_list
        })
        
    except Exception as e:
        logger.error(f"Error fetching user questions: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
# ============================================
# NEW: User Answer Endpoints
# ============================================

@app.route('/api/user/answers', methods=['GET', 'OPTIONS'])
def get_user_answers():
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', 'http://localhost:8080')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET,OPTIONS')
        return response

    try:
        # Verify token
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'success': False, 'message': 'Token required'}), 401
        token = request.headers.get('Authorization')
        payload = verify_token(token.replace('Bearer ', ''))
        if not payload or payload.get('role') != 'user':
            return jsonify({'success': False, 'message': 'Invalid token'}), 401
        
        user_id = payload['user_id']
        
        # Get user's enrollment number from users collection
        user = users_collection.find_one({'_id': ObjectId(user_id)})
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        
        enrollment = user.get('enrollment_number')
        
        # Find all answers for this user
        from database import db
        answers = []
        
        # Check if manual_answers collection exists
        if 'manual_answers' in db.list_collection_names():
            # Find answers by user_id or enrollment number
            cursor = db.manual_answers.find({
                '$or': [
                    {'user_id': user_id},
                    {'enrollment': enrollment}
                ]
            }).sort('answered_at', -1)
            
            for ans in cursor:
                # Check if this answer has been read by user
                read_status = None
                if 'answer_read_status' in db.list_collection_names():
                    read_status = db.answer_read_status.find_one({
                        'answer_id': str(ans['_id']),
                        'user_id': user_id
                    })
                
                answers.append({
                    'id': str(ans['_id']),
                    'question_id': ans.get('question_id', ''),
                    'original_question': ans.get('original_question', ''),
                    'answer': ans.get('answer', ''),
                    'answered_at': ans.get('answered_at', datetime.datetime.utcnow()).isoformat(),
                    'answered_by': ans.get('answered_by', 'admin'),
                    'is_read': read_status is not None
                })
        
        return jsonify({
            'success': True,
            'answers': answers
        })
        
    except Exception as e:
        logger.error(f"Error fetching user answers: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/user/answers/<answer_id>/read', methods=['PUT', 'OPTIONS'])
def mark_answer_read(answer_id):
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', 'http://localhost:8080')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'PUT,OPTIONS')
        return response

    try:
        # Verify token
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'success': False, 'message': 'Token required'}), 401
        token = request.headers.get('Authorization')
        payload = verify_token(token.replace('Bearer ', ''))
        if not payload or payload.get('role') != 'user':
            return jsonify({'success': False, 'message': 'Invalid token'}), 401
        
        user_id = payload['user_id']
        
        # Validate answer_id
        if not ObjectId.is_valid(answer_id):
            return jsonify({'success': False, 'message': 'Invalid answer ID'}), 400
        
        # Create read status record
        from database import db
        
        # Create collection if it doesn't exist
        if 'answer_read_status' not in db.list_collection_names():
            db.create_collection('answer_read_status')
        
        # Insert read status
        db.answer_read_status.update_one(
            {
                'answer_id': answer_id,
                'user_id': user_id
            },
            {
                '$set': {
                    'answer_id': answer_id,
                    'user_id': user_id,
                    'read_at': datetime.datetime.utcnow()
                }
            },
            upsert=True
        )
        
        return jsonify({
            'success': True,
            'message': 'Answer marked as read'
        })
        
    except Exception as e:
        logger.error(f"Error marking answer as read: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/user/answers/unread/count', methods=['GET', 'OPTIONS'])
def get_unread_answer_count():
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', 'http://localhost:8080')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET,OPTIONS')
        return response

    try:
        # Verify token
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'success': False, 'message': 'Token required'}), 401
        token = request.headers.get('Authorization')
        payload = verify_token(token.replace('Bearer ', ''))
        if not payload or payload.get('role') != 'user':
            return jsonify({'success': False, 'message': 'Invalid token'}), 401
        
        user_id = payload['user_id']
        
        # Get user's enrollment
        user = users_collection.find_one({'_id': ObjectId(user_id)})
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        
        enrollment = user.get('enrollment_number')
        
        # Count unread answers
        from database import db
        unread_count = 0
        
        if 'manual_answers' in db.list_collection_names():
            # Get all answers for this user
            answers = db.manual_answers.find({
                '$or': [
                    {'user_id': user_id},
                    {'enrollment': enrollment}
                ]
            })
            
            # Count those not read
            for ans in answers:
                read = None
                if 'answer_read_status' in db.list_collection_names():
                    read = db.answer_read_status.find_one({
                        'answer_id': str(ans['_id']),
                        'user_id': user_id
                    })
                if not read:
                    unread_count += 1
        
        return jsonify({
            'success': True,
            'count': unread_count
        })
        
    except Exception as e:
        logger.error(f"Error counting unread answers: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
    
# Temporary
@app.route('/api/debug/user-questions/<user_id>', methods=['GET'])
def debug_user_questions(user_id):
    """Temporary debug endpoint to check user questions"""
    try:
        # Get all questions for this user
        questions = list(unanswered_questions.find({'user_id': user_id}))
        
        result = []
        for q in questions:
            # Check for manual answers
            from database import db
            answer = None
            if 'manual_answers' in db.list_collection_names():
                manual = db.manual_answers.find_one({'question_id': str(q['_id'])})
                if manual:
                    answer = manual.get('answer')
            
            result.append({
                'id': str(q['_id']),
                'user_id': q.get('user_id'),
                'question': q.get('question'),
                'status': q.get('status'),
                'answered': q.get('answered'),
                'has_manual_answer': answer is not None,
                'created_at': str(q.get('created_at'))
            })
        
        return jsonify({
            'success': True,
            'total': len(result),
            'questions': result
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
# ============================================
# Main Entry Point
# ============================================
if __name__ == '__main__':
    # Create upload directory if it doesn't exist
    upload_dir = os.path.join(os.path.dirname(__file__), 'uploads')
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
        logger.info(f"Created upload directory: {upload_dir}")
    
    logger.info("Starting Flask server on port 5000...")
    app.run(debug=True, port=5000, host='0.0.0.0')