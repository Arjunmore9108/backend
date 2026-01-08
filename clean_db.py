# cleanup_knowledge.py
from database import knowledge_base
from pymongo import DESCENDING

def cleanup_knowledge_base():
    print("Starting knowledge base cleanup...")
    
    # Get all documents
    all_docs = list(knowledge_base.find())
    print(f"Total documents before cleanup: {len(all_docs)}")
    
    # Find duplicates by title and content
    seen = {}
    duplicates = []
    
    for doc in all_docs:
        key = (doc.get('title', ''), doc.get('content', '')[:100])  # First 100 chars of content
        if key in seen:
            duplicates.append(doc['_id'])
        else:
            seen[key] = doc['_id']
    
    # Delete duplicates
    if duplicates:
        print(f"Found {len(duplicates)} duplicate documents")
        result = knowledge_base.delete_many({'_id': {'$in': duplicates}})
        print(f"Deleted {result.deleted_count} duplicate documents")
    
    # Get final count
    final_count = knowledge_base.count_documents({})
    print(f"Total documents after cleanup: {final_count}")
    
    return final_count

if __name__ == "__main__":
    cleanup_knowledge_base()