import requests
import json
import datetime
import re
from config import Config
from database import knowledge_base, unanswered_questions

class ChatHandler:
    def __init__(self):
        self.api_key = Config.OPENROUTER_API_KEY
        self.base_url = Config.OPENROUTER_BASE_URL

    def search_knowledge_base(self, query):
        documents = knowledge_base.find({
            "$text": {"$search": query}
        })
        return list(documents)

    def is_college_related_question(self, query):
        college_keywords = [
            'college', 'university', 'campus', 'faculty', 'professor', 'lecturer',
            'admission', 'enrollment', 'registration', 'course', 'subject', 'syllabus',
            'exam', 'examination', 'test', 'assignment', 'homework', 'project',
            'library', 'laboratory', 'lab', 'hostel', 'dormitory', 'accommodation',
            'scholarship', 'fee', 'tuition', 'payment', 'finance', 'financial',
            'timetable', 'schedule', 'calendar', 'academic', 'semester', 'trimester',
            'department', 'faculty', 'dean', 'principal', 'director', 'administration',
            'student', 'undergraduate', 'postgraduate', 'graduate', 'alumni',
            'degree', 'diploma', 'certificate', 'graduation', 'convocation',
            'attendance', 'leave', 'absence', 'medical', 'health',
            'sports', 'gym', 'cultural', 'fest', 'event', 'activity',
            'canteen', 'cafeteria', 'food', 'mess', 'transport', 'bus', 'parking',
            'id card', 'identity', 'card', 'document', 'certificate',
            'result', 'grade', 'mark', 'cgpa', 'gpa', 'transcript',
            'internship', 'placement', 'job', 'career', 'company', 'recruitment',
            'workshop', 'seminar', 'conference', 'lecture', 'tutorial',
            'deadline', 'submission', 'application', 'form', 'procedure'
        ]
        
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in college_keywords)

    def generate_ai_response(self, query, context_docs=None):
        # System prompt to make the bot act like a helpful college assistant
        system_prompt = """You are DeepSeek College Assistant, a friendly and helpful AI chatbot for college students. You should:

1. Act like a normal, conversational person - be warm, friendly, and approachable
2. For college-related questions, first check if you have specific information
3. If you don't have specific college information, provide helpful general advice based on common knowledge
4. Use natural, conversational language - avoid robotic responses
5. Show empathy and understanding for student concerns
6. For academic questions, provide practical advice and suggestions
7. Keep responses concise but helpful
8. Use appropriate emojis occasionally to make it friendly
9. If you're unsure about specific college policies, admit it but still try to help
10. Always maintain a positive and supportive tone

Remember: You're talking to college students who might be stressed or need quick help. Be their friendly guide!"""

        # Build context from knowledge base if available
        context = ""
        if context_docs:
            context = "Here is some specific college information that might be relevant:\n"
            for doc in context_docs[:2]:  # Use top 2 most relevant documents
                context += f"Title: {doc['title']}\nContent: {doc['content'][:300]}...\n\n"

        user_prompt = f"""Student Question: {query}

{context}
Please provide a helpful response as a friendly college assistant. If this is about specific college procedures I don't have information about, I'll forward it to admin, but still try to be helpful."""

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://college-helpdesk.com",
                    "X-Title": "College Helpdesk Chatbot"
                },
                json={
                    "model": "deepseek/deepseek-chat",  # Using DeepSeek model for realistic responses
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "max_tokens": 500,
                    "temperature": 0.7,
                    "top_p": 0.9,
                },
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content']
            else:
                return "I'm having trouble processing your request right now. Please try again in a moment! 😊"
                
        except Exception as e:
            print(f"OpenRouter API error: {e}")
            return "I'm currently experiencing some technical difficulties. Please try again shortly! ⚡"

    def handle_query(self, query, user_id):
        # First, check if it's a college-related question
        is_college_related = self.is_college_related_question(query)
        
        # Always search knowledge base for relevant information
        context_docs = self.search_knowledge_base(query)
        
        if is_college_related:
            # For college-related questions, check if we have specific info
            if not context_docs:
                # No specific info found - forward to admin but still try to help
                unanswered_questions.insert_one({
                    "question": query,
                    "asked_by": user_id,
                    "timestamp": datetime.datetime.utcnow(),
                    "status": "pending",
                    "category": "college_related"
                })
                
                # Still generate a helpful AI response
                response = self.generate_ai_response(query, [])
                return response + "\n\n📝 *Note: I've forwarded your specific question to the college admin for detailed information.*"
            else:
                # We have college info - generate AI response with context
                response = self.generate_ai_response(query, context_docs)
                return response
        else:
            # For general/non-college questions, always generate AI response
            response = self.generate_ai_response(query, context_docs)
            return response