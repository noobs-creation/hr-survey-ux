import os
import psycopg2
import random
import string
from dotenv import load_dotenv

# Load environment variables
try:
    load_dotenv()
except ImportError:
    pass

def get_db_connection():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        print("❌ Error: DATABASE_URL not found.")
        return None
    return psycopg2.connect(db_url)

def create_token_table():
    conn = get_db_connection()
    if not conn: return

    try:
        cur = conn.cursor()
        print("⚙️  Creating 'survey_tokens' table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS survey_tokens (
                id SERIAL PRIMARY KEY,
                token_code VARCHAR(10) UNIQUE NOT NULL,
                is_used BOOLEAN DEFAULT FALSE,
                used_at TIMESTAMP
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Table 'survey_tokens' ready.")
    except Exception as e:
        print(f"❌ Database Error: {e}")

def generate_tokens(count=50):
    conn = get_db_connection()
    if not conn: return

    new_tokens = []
    
    # Generate requested number of unique tokens
    # Format: 4 Uppercase Letters + 4 Digits (e.g., ABCD1234)
    while len(new_tokens) < count:
        letters = ''.join(random.choices(string.ascii_uppercase, k=4))
        numbers = ''.join(random.choices(string.digits, k=4))
        token = letters + numbers
        new_tokens.append(token)

    try:
        cur = conn.cursor()
        print(f"🎲 Generating {count} new tokens...")
        
        # Insert efficiently
        # ON CONFLICT DO NOTHING ensures we don't crash if a duplicate random token is generated (rare)
        for token in new_tokens:
            cur.execute("""
                INSERT INTO survey_tokens (token_code) 
                VALUES (%s) 
                ON CONFLICT (token_code) DO NOTHING
            """, (token,))
            
        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ Successfully added {count} tokens to the database.")
        
    except Exception as e:
        print(f"❌ Error generating tokens: {e}")

if __name__ == "__main__":
    create_token_table()
    
    # You can change this number to generate more or fewer tokens
    generate_tokens(50)