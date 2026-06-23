# chat_handler.py
import requests
import datetime
import time
import re
import hashlib
from difflib import SequenceMatcher
from collections import Counter
from config import Config
from database import knowledge_base, unanswered_questions

class ChatHandler:
    def __init__(self):
        self.api_key = Config.OPENROUTER_API_KEY
        self.base_url = Config.OPENROUTER_BASE_URL
        self.cache = {}  # Simple cache: {query_hash: (response, expiry_time)}
        
        # Initialize knowledge base indexes
        self.init_indexes()
        
        # Common college abbreviations and expansions
        self.abbreviations = {
            'cs': 'computer science',
            'cse': 'computer science engineering',
            'ece': 'electronics and communication engineering',
            'ee': 'electrical engineering',
            'me': 'mechanical engineering',
            'ce': 'civil engineering',
            'ai': 'artificial intelligence',
            'ml': 'machine learning',
            'ds': 'data science',
            'cgpa': 'cumulative grade point average',
            'sgpa': 'semester grade point average',
            'hod': 'head of department',
            'ac': 'academic calendar',
            'fees': 'fee structure',
            'admissions': 'admission process'
        }
        
        # Question pattern detection
        self.question_patterns = {
            'what': r'\bwhat\b',
            'when': r'\bwhen\b',
            'where': r'\bwhere\b',
            'who': r'\bwho\b',
            'why': r'\bwhy\b',
            'how': r'\bhow\b',
            'can': r'\bcan\b',
            'is': r'\bis\b',
            'are': r'\bare\b',
            'does': r'\bdoes\b'
        }

    def init_indexes(self):
        """Initialize database indexes for better search performance."""
        try:
            # Text index for full-text search
            knowledge_base.create_index([
                ("title", "text"), 
                ("content", "text"),
                ("keywords", "text")
            ])
            
            # Regular indexes for faster queries
            knowledge_base.create_index("content_type")
            knowledge_base.create_index("created_at")
        except Exception as e:
            print(f"Index creation error: {e}")

    # ---------------- Advanced Knowledge Base Search ----------------
    def search_knowledge_base(self, query, max_results=5):
        """Enhanced search with multiple strategies and relevance scoring."""
        
        # Clean and expand query
        clean_query = self.preprocess_query(query)
        
        # Try multiple search strategies in order of effectiveness
        results = []
        
        # Strategy 1: Semantic text search with textScore
        results = self.text_search(clean_query, max_results)
        if results and self.calculate_relevance(results[0], clean_query) > 0.5:
            return results
        
        # Strategy 2: Keyword expansion with abbreviations
        expanded_query = self.expand_query(clean_query)
        if expanded_query != clean_query:
            results = self.text_search(expanded_query, max_results)
            if results:
                return results
        
        # Strategy 3: Fuzzy matching on titles
        results = self.fuzzy_title_search(clean_query, max_results)
        if results:
            return results
        
        # Strategy 4: Multi-keyword search with scoring
        results = self.keyword_scoring_search(clean_query, max_results)
        if results:
            return results
        
        # Strategy 5: Partial matching as last resort
        return self.partial_match_search(clean_query, max_results)

    def preprocess_query(self, query):
        """Clean and normalize query for better matching."""
        # Convert to lowercase
        query = query.lower()
        
        # Remove special characters but keep important punctuation
        query = re.sub(r'[^\w\s\?]', ' ', query)
        
        # Remove extra whitespace
        query = ' '.join(query.split())
        
        # Expand common abbreviations
        words = query.split()
        expanded_words = []
        for word in words:
            if word in self.abbreviations:
                expanded_words.append(self.abbreviations[word])
            else:
                expanded_words.append(word)
        
        return ' '.join(expanded_words)

    def expand_query(self, query):
        """Expand query with synonyms and related terms."""
        expansions = []
        words = query.split()
        
        # Add common variations
        for word in words:
            if word.endswith('s'):  # Plural to singular
                expansions.append(word[:-1])
            if word in ['fee', 'fees']:
                expansions.append('fee structure')
                expansions.append('cost')
                expansions.append('payment')
            if word in ['admission', 'admissions']:
                expansions.append('admission process')
                expansions.append('enrollment')
                expansions.append('application')
            if word in ['exam', 'exams']:
                expansions.append('examination')
                expansions.append('test')
                expansions.append('assessment')
        
        if expansions:
            return query + ' ' + ' '.join(expansions)
        return query

    def text_search(self, query, max_results):
        """Full-text search with MongoDB text index."""
        try:
            docs = list(knowledge_base.find(
                {"$text": {"$search": query}},
                {"score": {"$meta": "textScore"}}
            ).sort([("score", {"$meta": "textScore"})]).limit(max_results * 2))
            
            # Filter by relevance threshold
            if docs:
                avg_score = sum(d['score'] for d in docs) / len(docs)
                return [d for d in docs if d['score'] >= avg_score * 0.5][:max_results]
        except:
            pass
        return []

    def fuzzy_title_search(self, query, max_results):
        """Search using fuzzy matching on titles."""
        all_docs = list(knowledge_base.find().limit(100))
        scored_docs = []
        
        for doc in all_docs:
            title = doc.get('title', '').lower()
            # Calculate similarity ratio
            similarity = SequenceMatcher(None, query, title).ratio()
            
            # Check if title contains significant parts of query
            query_words = set(query.split())
            title_words = set(title.split())
            word_overlap = len(query_words & title_words) / max(len(query_words), 1)
            
            score = (similarity * 0.6) + (word_overlap * 0.4)
            
            if score > 0.3:  # Threshold for relevance
                scored_docs.append((score, doc))
        
        scored_docs.sort(reverse=True, key=lambda x: x[0])
        return [doc for score, doc in scored_docs[:max_results]]

    def keyword_scoring_search(self, query, max_results):
        """Search with intelligent keyword scoring."""
        # Extract important keywords (skip common words)
        stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'what', 'when', 
                     'where', 'who', 'why', 'how', 'can', 'do', 'does', 'for', 'to',
                     'in', 'on', 'at', 'by', 'with', 'about', 'like'}
        
        keywords = [w for w in query.split() 
                   if w not in stop_words and len(w) > 2]
        
        if not keywords:
            keywords = query.split()
        
        # Get all documents (limit for performance)
        all_docs = list(knowledge_base.find().limit(200))
        scored_docs = []
        
        for doc in all_docs:
            # Combine title and content for searching
            title = doc.get('title', '').lower()
            content = doc.get('content', '').lower()[:2000]  # Limit content length
            full_text = title + ' ' + content
            
            # Calculate keyword scores
            keyword_score = 0
            exact_matches = 0
            partial_matches = 0
            
            for keyword in keywords:
                if keyword in full_text:
                    # Higher score for exact matches
                    keyword_score += 2
                    exact_matches += full_text.count(keyword)
                elif any(keyword in word for word in full_text.split()):
                    # Partial matches
                    keyword_score += 1
                    partial_matches += 1
            
            # Bonus for title matches
            title_matches = sum(1 for k in keywords if k in title)
            keyword_score += title_matches * 3
            
            # Calculate relevance percentage
            if keywords:
                max_possible_score = len(keywords) * 5  # Max score per keyword
                relevance = (keyword_score / max_possible_score) * 100
                
                if relevance > 15:  # Minimum relevance threshold
                    scored_docs.append((relevance, exact_matches, partial_matches, doc))
        
        # Sort by relevance (primary), exact matches (secondary)
        scored_docs.sort(reverse=True, key=lambda x: (x[0], x[1], x[2]))
        return [doc for rel, exact, partial, doc in scored_docs[:max_results]]

    def partial_match_search(self, query, max_results):
        """Fallback search using partial matching."""
        pattern = '.*' + '.*'.join(query.split()) + '.*'
        try:
            docs = list(knowledge_base.find({
                "$or": [
                    {"title": {"$regex": pattern, "$options": "i"}},
                    {"content": {"$regex": pattern, "$options": "i"}}
                ]
            }).limit(max_results))
            return docs
        except:
            return []

    def calculate_relevance(self, doc, query):
        """Calculate relevance score for a document."""
        title = doc.get('title', '').lower()
        content = doc.get('content', '').lower()[:1000]
        
        query_words = set(query.split())
        title_words = set(title.split())
        content_words = set(content.split())
        
        # Title relevance (higher weight)
        title_overlap = len(query_words & title_words) / max(len(query_words), 1)
        
        # Content relevance
        content_overlap = len(query_words & content_words) / max(len(query_words), 1)
        
        # Combined score
        relevance = (title_overlap * 0.7) + (content_overlap * 0.3)
        
        return relevance

    # ---------------- Enhanced College Detection ----------------
    def is_college_related(self, query):
        """Intelligently detect college-related queries with context awareness."""
        query_lower = query.lower()
        
        # Comprehensive college keywords with categories
        college_keywords = {
            'academic': ['course', 'subject', 'semester', 'credit', 'grade', 'cgpa', 'sgpa', 
                        'attendance', 'assignment', 'project', 'thesis', 'dissertation'],
            'administrative': ['admission', 'registration', 'enrollment', 'fee', 'scholarship', 
                              'document', 'certificate', 'transcript', 'application'],
            'facility': ['library', 'lab', 'laboratory', 'hostel', 'canteen', 'sports', 
                        'gym', 'auditorium', 'classroom'],
            'exam': ['exam', 'test', 'quiz', 'assessment', 'result', 'grade', 'mark', 
                    'score', 'pass', 'fail'],
            'staff': ['teacher', 'professor', 'faculty', 'instructor', 'hod', 'dean', 
                     'principal', 'staff', 'mentor'],
            'event': ['fest', 'event', 'workshop', 'seminar', 'conference', 'webinar', 
                     'cultural', 'technical'],
            'placement': ['placement', 'internship', 'job', 'company', 'recruitment', 
                         'interview', 'career', 'training'],
            'time': ['schedule', 'timetable', 'time', 'date', 'deadline', 'calendar', 
                    'holiday', 'vacation']
        }
        
        # Check for college-related terms
        for category, keywords in college_keywords.items():
            if any(k in query_lower for k in keywords):
                return True
        
        # Check for question patterns about college
        college_indicators = [
            r'how (?:to|do|can) (?:i|we) (?:get|apply|register)',
            r'what (?:is|are) the (?:process|procedure|requirement)',
            r'when (?:is|will|does)',
            r'where (?:is|are|can)',
            r'who (?:is|are)'
        ]
        
        for pattern in college_indicators:
            if re.search(pattern, query_lower) and any(w in query_lower for w in ['college', 'university', 'course']):
                return True
        
        return False

    # ---------------- Improved Caching ----------------
    def get_cache_key(self, query, context=None):
        """Generate cache key based on query and context."""
        key_string = query.lower()
        if context:
            # Include context summary in cache key
            context_summary = hashlib.md5(str(context).encode()).hexdigest()[:10]
            key_string += context_summary
        return hashlib.md5(key_string.encode()).hexdigest()

    def get_cached(self, query, context=None):
        """Get cached response with context awareness."""
        cache_key = self.get_cache_key(query, context)
        data = self.cache.get(cache_key)
        if data and data[1] > time.time():
            return data[0]
        elif data:
            del self.cache[cache_key]
        return None

    def set_cache(self, query, response, context=None, expiry=600):  # Increased to 10 minutes
        """Cache response with context."""
        cache_key = self.get_cache_key(query, context)
        self.cache[cache_key] = (response, time.time() + expiry)

    # ---------------- Admin Forwarding with Smart Decision ----------------
    def should_forward_to_admin(self, query, docs, response_text, response_quality):
        """Intelligently decide whether to forward to admin based on multiple factors."""
        query_lower = query.lower()
        
        # 1️⃣ Check if the response already contains information that answers the question
        # If response is helpful and contains specific info, don't forward
        helpful_indicators = [
            "fee structure", "admission process", "last date", "deadline",
            "requirements", "eligibility", "procedure", "steps to", "how to",
            "is located", "timings", "schedule", "contact", "email", "phone",
            "website", "office", "department"
        ]
        
        # Check if response contains specific helpful information
        if any(indicator in response_text.lower() for indicator in helpful_indicators):
            # If we have documents and quality is good, don't forward
            if docs and response_quality > 0.4:
                return False, "answer_contains_specific_info"
        
        # 2️⃣ Check if user explicitly asks for human/admin
        explicit_human_keywords = ['talk to human', 'talk to person', 'connect to admin', 
                                   'speak to someone', 'human agent', 'real person']
        if any(k in query_lower for k in explicit_human_keywords):
            return True, "user_requested_human"
        
        # 3️⃣ Check for urgent keywords
        urgent_keywords = ['urgent', 'emergency', 'immediately', 'asap', 'help', 'problem', 'issue']
        if any(k in query_lower for k in urgent_keywords):
            # Only forward urgent if no good answer found
            if not docs or response_quality < 0.5:
                return True, "urgent_query_no_answer"
        
        # 4️⃣ Check for personal/case-specific questions
        personal_keywords = ['my', 'me', 'i have', 'i am', 'i need', 'my account', 'my application']
        if any(k in query_lower for k in personal_keywords) and len(query.split()) > 3:
            # Check if response addresses the personal aspect
            if not any(word in response_text.lower() for word in ['your', 'you can', 'please']):
                return True, "personal_query_needs_human"
        
        # 5️⃣ No relevant documents found AND question is college-related
        if (not docs or len(docs) == 0) and self.is_college_related(query):
            # Check if response acknowledges lack of information
            if any(phrase in response_text.lower() for phrase in [
                'not sure', "don't know", "can't find", "no information", 
                "not available", "couldn't find"
            ]):
                return True, "no_knowledge_found"
        
        # 6️⃣ Low confidence in response AND question is complex
        is_complex = len(query.split()) > 5 and any(k in query_lower for k in ['how', 'why', 'explain'])
        if response_quality < 0.3 and is_complex:
            return True, "low_confidence_complex_query"
        
        # 7️⃣ Question is unanswered in KB (no docs) AND user seems confused
        confusion_indicators = ['?', 'help', 'confused', 'understand', 'clarify']
        if not docs and any(c in query_lower for c in confusion_indicators):
            return True, "unanswered_confused_user"
        
        # Default: Don't forward if none of the conditions are met
        return False, "answered_satisfactorily"

    # ---------------- Enhanced AI Response ----------------
    def generate_ai_response(self, query, context_docs=None):
        """Generate intelligent AI response with context and quality assessment."""
        
        # Check cache first
        cached = self.get_cached(query, context_docs)
        if cached:
            return cached, 1.0  # Return cached response with full confidence
        
        # Prepare context with ranking
        context_text = ""
        response_quality = 0.0
        
        if context_docs:
            # Rank and format context documents
            ranked_docs = []
            for doc in context_docs:
                relevance = self.calculate_relevance(doc, query)
                ranked_docs.append((relevance, doc))
            
            ranked_docs.sort(reverse=True, key=lambda x: x[0])
            
            # Use top relevant documents
            top_docs = ranked_docs[:3]  # Limit to top 3 most relevant
            response_quality = sum(rel for rel, _ in top_docs) / len(top_docs) if top_docs else 0
            
            # Format context with clear separation
            context_parts = []
            for relevance, doc in top_docs:
                title = doc.get('title', 'Information')
                content = doc.get('content', '')[:1000]  # Limit content length
                context_parts.append(f"[Source: {title} (Relevance: {relevance:.0%})]\n{content}")
            
            context_text = "\n\n---\n\n".join(context_parts)
        
        # Determine query type for better prompting
        query_type = self.identify_query_type(query)
        
        # System prompt with specific instructions based on query type
        system_prompts = {
            'factual': "You are a knowledgeable college assistant. Provide accurate, factual information based on the context. If the information isn't in the context, say so politely.",
            'procedural': "You are a helpful college guide. Explain procedures step by step. If you're unsure about any step, mention that and suggest where to get accurate information.",
            'definition': "You are a clear educator. Define terms simply and accurately. Use examples from the context when available.",
            'comparison': "You are an analytical advisor. Compare options objectively based on the provided information. Highlight pros and cons.",
            'casual': "You are a friendly college friend. Respond conversationally but helpfully. If you don't know something, be honest about it.",
            'default': "You are a helpful AI assistant for college students. Be friendly, accurate, and concise. Use the provided context when relevant."
        }
        
        system_prompt = system_prompts.get(query_type, system_prompts['default'])
        
        # Add context usage instruction
        if context_text:
            system_prompt += "\n\nIMPORTANT: Base your answer primarily on the provided context. If the context doesn't contain relevant information, acknowledge this and provide general guidance."
        
        # User prompt with clear structure
        if context_text:
            user_prompt = f"""Question: {query}

Relevant Information from College Knowledge Base:
{context_text}

Please provide a helpful answer based on the information above."""
        else:
            user_prompt = f"""Question: {query}

Please provide a helpful response. If this is a college-related question and you don't have specific information, let me know and suggest where to find accurate information."""

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": "deepseek/deepseek-chat",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 800,
                    "top_p": 0.9
                },
                timeout=20
            )
            
            if response.status_code == 200:
                answer = response.json()["choices"][0]["message"]["content"]
                
                # Enhance answer with source attribution if context was used
                if context_docs and len(context_docs) > 0:
                    # Add subtle source indication without being intrusive
                    answer += "\n\n📚 *This answer is based on information from our knowledge base.*"
                
                # Cache the response
                self.set_cache(query, answer, context_docs)
                
                return answer, response_quality
            else:
                print(f"API Error: {response.status_code} - {response.text}")
                
        except requests.exceptions.Timeout:
            print("API timeout")
        except Exception as e:
            print(f"API error: {e}")
        
        # Fallback response
        if context_docs:
            first_doc = context_docs[0]
            content = first_doc.get('content', '')
            title = first_doc.get('title', 'Information')
            
            # Extract a meaningful preview
            sentences = re.split(r'[.!?]+', content)
            preview = '. '.join(sentences[:3]) + '.'
            
            return f"📘 From our knowledge base ({title}):\n\n{preview}", 0.3
        
        return "I'm not sure about that. 🤔 Would you like me to connect you with someone who can help?", 0.0

    def identify_query_type(self, query):
        """Identify the type of query for better response generation."""
        query_lower = query.lower()
        
        # Definition queries
        if any(w in query_lower for w in ['what is', 'define', 'meaning of', 'explain']):
            return 'definition'
        
        # How-to/procedural queries
        if any(w in query_lower for w in ['how to', 'how do i', 'steps to', 'process of']):
            return 'procedural'
        
        # Comparison queries
        if any(w in query_lower for w in ['vs', 'versus', 'difference between', 'compare']):
            return 'comparison'
        
        # Factual queries
        if any(w in query_lower for w in ['when', 'where', 'who', 'what time', 'what date']):
            return 'factual'
        
        # Short casual queries
        if len(query.split()) <= 3:
            return 'casual'
        
        return 'default'

    # ---------------- Main Query Handler ----------------
    def handle_query(self, query, user_id):
        """Enhanced main handler with intelligent processing."""
        try:
            # Preprocess query
            clean_query = self.preprocess_query(query)
            
            # Detect if question is college-related
            college_related = self.is_college_related(clean_query)
            
            # Search KB with enhanced strategy for college questions
            docs = []
            if college_related:
                docs = self.search_knowledge_base(clean_query, max_results=5)
                print(f"Found {len(docs)} relevant documents for college query")
            
            # Generate AI response with quality assessment
            response, response_quality = self.generate_ai_response(query, docs)
            
            # Decide whether to forward to admin
            should_forward, reason = self.should_forward_to_admin(query, docs, response, response_quality)
            
            # Forward to admin if needed
            if should_forward:
                success = self.forward_to_admin(query, user_id, reason, college_related)
                if success:
                    response += "\n\n👨‍🏫 I've also notified the admin about your question. They'll get back to you if needed!"
            
            return response
            
        except Exception as e:
            print(f"Error in handle_query: {e}")
            return "I'm having trouble processing your request right now. Please try again later or contact the admin directly."

    # ---------------- Admin Forwarding ----------------
    def forward_to_admin(self, query, user_id, reason, college_related):
        """Forward query to admin for manual handling."""
        try:
            doc = {
                "question": query,
                "user_id": user_id,
                "timestamp": datetime.datetime.utcnow(),
                "status": "pending",
                "category": "college_related" if college_related else "general",
                "reason": reason,
                "priority": self.calculate_priority(reason)
            }
            result = unanswered_questions.insert_one(doc)
            return bool(result.inserted_id)
        except Exception as e:
            print(f"Error forwarding to admin: {e}")
            return False

    def calculate_priority(self, reason):
        """Calculate priority for admin queue."""
        priority_map = {
            'user_requested_human': 'high',
            'urgent_query_no_answer': 'high',
            'personal_query_needs_human': 'high',
            'no_knowledge_found': 'medium',
            'low_confidence_complex_query': 'medium',
            'unanswered_confused_user': 'medium',
            'answer_contains_specific_info': 'low',
            'answered_satisfactorily': 'low'
        }
        return priority_map.get(reason, 'medium')