from pymongo import MongoClient
from config import Config

client = MongoClient(Config.MONGODB_URI)
db = client.college_helpdesk

class User:
    def __init__(self, enrollment_number, password, name, email, department):
        self.enrollment_number = enrollment_number
        self.password = password
        self.name = name
        self.email = email
        self.department = department

class Admin:
    def __init__(self, username, password, email):
        self.username = username
        self.password = password
        self.email = email

class KnowledgeDocument:
    def __init__(self, title, content, file_type, file_path, uploaded_by, tags):
        self.title = title
        self.content = content
        self.file_type = file_type
        self.file_path = file_path
        self.uploaded_by = uploaded_by
        self.tags = tags
        self.created_at = None

class UnansweredQuestion:
    def __init__(self, question, asked_by, timestamp, status="pending"):
        self.question = question
        self.asked_by = asked_by
        self.timestamp = timestamp
        self.status = status

class Conversation:
    def __init__(self, user_id, messages):
        self.user_id = user_id
        self.messages = messages
        self.last_updated = None