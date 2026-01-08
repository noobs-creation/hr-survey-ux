import os
import psycopg2
# Handle dotenv import for local development vs production
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def add_caching_column():
    print("Connecting to database...")
    db_url = os.environ.get('DATABASE_URL')
    
    if not db_url:
        print("Error: DATABASE_URL not found in environment variables.")
        return

    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        
        # SQL Command to add the column if it doesn't exist
        print("Checking/Adding 'ai_analysis_text' column...")
        cur.execute("""
            ALTER TABLE survey_responses 
            ADD COLUMN IF NOT EXISTS ai_analysis_text TEXT;
        """)
        
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Success! Database updated. You can now use caching.")
        
    except Exception as e:
        print(f"❌ Error updating database: {e}")

if __name__ == "__main__":
    add_caching_column()