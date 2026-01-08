
"""
HR Survey Application - Main Application Entry Point
--------------------------------------------------
This Flask application handles:
1. Serving the Employee Survey interface.
2. Collecting and persisting responses to a PostgreSQL database.
3. Generating Admin Dashboards with statistical analysis.
4. Integrating Google Gemini AI for qualitative psychological profiling.
"""
import os
import json
import psycopg2
from flask import Flask, render_template, request, jsonify
from psycopg2.extras import RealDictCursor
from datetime import datetime
import pytz

# --- 1. ROBUST DOTENV IMPORT ---
# --- Configuration & Environment Setup ---
# Robust configuration pattern: 
# 1. Attempts to load local .env file for development.
# 2. Falls back to system environment variables for production (Render/AWS).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass 

# --- NEW AI LIBRARY (google-genai) ---
from google import genai
from google.genai import types

# Configure the New Gemini Client
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

app = Flask(__name__)

# Load questions
with open('final_hr_questions.json', 'r') as f:
    SURVEY_DATA = json.load(f)


def get_db_connection():
    # Establishes a connection to the PostgreSQL database.
    # Relies on the 'DATABASE_URL' environment variable for security.
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        pass 
    conn = psycopg2.connect(db_url)
    return conn

def get_ist_time():
    """Returns current time in Indian Standard Time"""
    # UTC is the standard for storage, but IST is required for
    # admin display purposes in the specific region context.
    utc_now = datetime.now(pytz.utc)
    ist_tz = pytz.timezone('Asia/Kolkata')
    return utc_now.astimezone(ist_tz)

@app.route('/')
def index():
    return render_template('survey.html', survey_data=SURVEY_DATA)

@app.route('/submit', methods=['POST'])
def submit():
    form_data = request.form.to_dict()
    # --- Data Sanitization ---
    # Convert numeric string inputs (e.g., "5") to integers for calculation.
    # Preserve text inputs (e.g., comments) as strings.
    respondent_name = form_data.pop('respondent_name', 'Anonymous') or 'Anonymous'
    
    processed_answers = {}
    for key, value in form_data.items():
        try:
            processed_answers[key] = int(value)
        except ValueError:
            processed_answers[key] = value
    
    ist_now = get_ist_time()

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO survey_responses (respondent_name, answers, submitted_at) VALUES (%s, %s, %s)",
            (respondent_name, json.dumps(processed_answers), ist_now)
        )
        conn.commit()
        cur.close()
        conn.close()
        return render_template('survey.html', survey_data=SURVEY_DATA, success=True)
    except Exception as e:
        return f"Database Error: {e}"


@app.route('/admin')
def admin():
    if request.args.get('key') != 'mysecretadminpassword':
        return "Access Denied."

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM survey_responses ORDER BY submitted_at DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    ist_tz = pytz.timezone('Asia/Kolkata')
    processed_rows = []
    
    for row in rows:
        # 1. Convert Time to IST
        utc_time = row['submitted_at']
        if utc_time:
            if utc_time.tzinfo is None:
                utc_time = pytz.utc.localize(utc_time)
            row['submitted_at'] = utc_time.astimezone(ist_tz)

        # 2. Parse Answers
        answers = row['answers']
        cat_totals = {k: [] for k in SURVEY_DATA.keys()}
        
        for key, val in answers.items():
            if isinstance(val, int) and '_' in key:
                raw_cat = key.rsplit('_', 1)[0]
                # --- Data Integrity Normalization ---
                # Resolves naming discrepancies between the Database (stores "and") 
                # and the JSON configuration (uses "&").
                # This ensures scores are correctly mapped to their categories.
                # --- Fix: Normalize 'and' to '&' ---
                if raw_cat in cat_totals:
                    category = raw_cat
                elif raw_cat.replace(' and ', ' & ') in cat_totals:
                    category = raw_cat.replace(' and ', ' & ')
                else:
                    continue

                cat_totals[category].append(val)
        # --- Statistical Calculation Engine ---
        # Calculates "Equal Weight" averages.
        # 1. Calculate average for each Category first.
        # 2. Average the Category scores to get the Overall Score.
        # This prevents categories with more questions from skewing the final result.
        # 3. Calculate Normalized Stats
        cat_averages = {}
        sum_of_category_averages = 0
        valid_categories_count = 0

        for cat, scores in cat_totals.items():
            if scores:
                avg = sum(scores) / len(scores)
                cat_averages[cat] = round(avg, 2)
                sum_of_category_averages += avg
                valid_categories_count += 1
            else:
                cat_averages[cat] = 0
        
        # 4. Calculate Overall Score
        if valid_categories_count > 0:
            overall = round(sum_of_category_averages / valid_categories_count, 2)
        else:
            overall = 0
        # --- Insight Logic & Tie-Breaker ---
        # Identifies Top Strength and Weakness.
        # Includes logic to handle "Flat Profiles" (e.g., User rated everything 5/5),
        # preventing arbitrary alphabetical sorting in tie scenarios.
        # 5. Determine Strength/Weakness (WITH TIE-BREAKER LOGIC)
        active_cats = {k:v for k,v in cat_averages.items() if v > 0}
        
        if active_cats:
            # Sort by score descending
            sorted_cats = sorted(active_cats.items(), key=lambda x: x[1], reverse=True)
            
            highest_score = sorted_cats[0][1]
            lowest_score = sorted_cats[-1][1]
            
            # --- THIS IS THE MISSING PART IN YOUR CODE ---
            # Check for Flat Profile (Variance is 0)
            if highest_score == lowest_score:
                if highest_score == 5:
                    strength = ("All Categories", 5.0)
                    weakness = ("None", 0)
                elif highest_score == 1:
                    strength = ("None", 0)
                    weakness = ("All Categories", 1.0)
                else:
                    strength = ("Balanced Profile", highest_score)
                    weakness = ("Balanced Profile", lowest_score)
            else:
                # Standard case: Variance exists
                strength = sorted_cats[0]
                weakness = sorted_cats[-1]
            # ---------------------------------------------
        else:
            strength = ("N/A", 0)
            weakness = ("N/A", 0)

        row_dict = dict(row)
        row_dict['stats'] = {
            'averages': cat_averages,
            'strength': strength,
            'weakness': weakness,
            'overall': overall,
            'categories_list': list(cat_averages.keys()),
            'scores_list': list(cat_averages.values())
        }
        processed_rows.append(row_dict)

    return render_template('admin.html', responses=processed_rows, survey_data=SURVEY_DATA)

# --- REPLACED REPORT ROUTE ---
@app.route('/report')
def report():
    if request.args.get('key') != 'mysecretadminpassword':
        return "Access Denied."

    # 1. Fetch ALL Data
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM survey_responses ORDER BY submitted_at ASC")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return "No data available to generate report."

    # --- FILTER PARAMETERS (UPDATED) ---
    selected_year = request.args.get('year')
    selected_month = request.args.get('month')
    
    # 1. Extract unique YEARS from DB (Existing logic)
    available_years = sorted(list(set([row['submitted_at'].strftime('%Y') for row in rows])), reverse=True)

    # 2. Extract unique MONTHS from DB (New Logic)
    # Get all unique month numbers (e.g., '01', '05', '12') present in the data
    present_month_nums = sorted(list(set([row['submitted_at'].strftime('%m') for row in rows])))
    
    # Create the map only for these existing months (e.g., {'01': 'January', '05': 'May'})
    month_map = {m: datetime.strptime(m, "%m").strftime("%B") for m in present_month_nums}

    # --- ENGINE 1: TREND ANALYSIS (Uses ALL Data) ---
    # Group data by YYYY-MM to calculate historical average scores
    trend_buckets = {} # Format: {'2026-01': [score1, score2]}
    
    for row in rows:
        month_key = row['submitted_at'].strftime('%Y-%m')
        
        # Calculate Individual Overall Score (Same logic as admin)
        answers = row['answers']
        cat_sums = {}
        cat_counts = {}
        
        for key, val in answers.items():
            if isinstance(val, int) and '_' in key:
                raw_cat = key.rsplit('_', 1)[0]
                # Normalize Key
                cat = raw_cat if raw_cat in SURVEY_DATA else raw_cat.replace(' and ', ' & ')
                if cat not in SURVEY_DATA: continue
                
                cat_sums[cat] = cat_sums.get(cat, 0) + val
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
        
        # Avg of Category Averages
        row_cat_avgs = []
        for cat in cat_sums:
            row_cat_avgs.append(cat_sums[cat] / cat_counts[cat])
            
        if row_cat_avgs:
            row_overall = sum(row_cat_avgs) / len(row_cat_avgs)
            if month_key not in trend_buckets: trend_buckets[month_key] = []
            trend_buckets[month_key].append(row_overall)

    # Prepare Chart Data
    trend_labels = []
    trend_data = []
    for m_key in sorted(trend_buckets.keys()):
        avg_score = sum(trend_buckets[m_key]) / len(trend_buckets[m_key])
        # Convert '2026-01' -> 'Jan 2026'
        label = datetime.strptime(m_key, '%Y-%m').strftime('%b %Y')
        trend_labels.append(label)
        trend_data.append(round(avg_score, 2))


    # --- ENGINE 2: SNAPSHOT ANALYSIS (Uses FILTERED Data) ---
    # Filter rows based on selection
    filtered_rows = []
    for row in rows:
        row_year = row['submitted_at'].strftime('%Y')
        row_month = row['submitted_at'].strftime('%m')
        
        if selected_year and row_year != selected_year: continue
        if selected_month and row_month != selected_month: continue
        
        filtered_rows.append(row)

    if not filtered_rows:
        return f"No data found for {selected_month or 'All Months'} / {selected_year or 'All Years'}."

    # Standard Calculation on Filtered Subset
    category_scores = {category: [] for category in SURVEY_DATA.keys()}
    
    for row in filtered_rows:
        answers = row['answers']
        for key, value in answers.items():
            if not isinstance(value, int): continue
            if '_' in key:
                raw_cat = key.rsplit('_', 1)[0]
                if raw_cat in category_scores:
                    category_scores[raw_cat].append(value)
                elif raw_cat.replace(' and ', ' & ') in category_scores:
                    category_scores[raw_cat.replace(' and ', ' & ')].append(value)

    final_averages = {}
    valid_categories_count = 0
    sum_of_category_averages = 0

    for cat, scores in category_scores.items():
        if scores:
            avg = sum(scores) / len(scores)
            final_averages[cat] = round(avg, 2)
            sum_of_category_averages += avg
            valid_categories_count += 1
        else:
            final_averages[cat] = 0

    if valid_categories_count > 0:
        overall_score = round(sum_of_category_averages / valid_categories_count, 2)
    else:
        overall_score = 0

    active_cats = {k:v for k,v in final_averages.items() if v > 0}
    sorted_cats = sorted(active_cats.items(), key=lambda x: x[1], reverse=True)
    
    strongest = sorted_cats[0] if sorted_cats else ("None", 0)
    weakest = sorted_cats[-1] if sorted_cats else ("None", 0)
    
    ist_now = get_ist_time()

    return render_template('report.html', 
                           # Snapshot Data
                           averages=final_averages, 
                           total=len(filtered_rows),
                           overall=overall_score,
                           strongest=strongest,
                           weakest=weakest,
                           timestamp=ist_now.strftime('%Y-%m-%d %I:%M %p'),
                           # Filter Data
                           available_years=available_years,
                           month_map=month_map,
                           selected_year=selected_year,
                           selected_month=selected_month,
                           # Trend Data
                           trend_labels=trend_labels,
                           trend_data=trend_data)

# --- NEW ROUTE: AGGREGATE ORGANIZATION ANALYSIS ---
@app.route('/analyze_aggregate')
def analyze_aggregate():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT answers FROM survey_responses")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return jsonify({"error": "No data available"}), 404

    category_scores = {category: [] for category in SURVEY_DATA.keys()}
    for row in rows:
        answers = row['answers']
        for key, value in answers.items():
            if not isinstance(value, int): continue
            if '_' in key:
                raw_cat = key.rsplit('_', 1)[0]
                # --- FIX: Normalize 'and' to '&' ---
                if raw_cat in category_scores:
                    category_scores[raw_cat].append(value)
                elif raw_cat.replace(' and ', ' & ') in category_scores:
                    category_scores[raw_cat.replace(' and ', ' & ')].append(value)

    final_averages = {}
    for cat, scores in category_scores.items():
        if scores:
            avg = sum(scores) / len(scores)
            final_averages[cat] = round(avg, 2)
        else:
            final_averages[cat] = 0

    prompt_data = "\n".join([f"{cat}: {score}/5.0" for cat, score in final_averages.items()])
    # --- Prompt Engineering ---
    # Constructs a context-aware system prompt for the LLM.
    # 1. Feeds raw quantitative data.
    # 2. Instructs the model to act as an Organizational Psychologist.
    # 3. Enforces a strict HTML output format for frontend rendering.
    system_prompt = f"""
    You are an expert Organizational Development Consultant and HR Strategist.
    You are analyzing the AGGREGATED survey results for the entire company.
    
    COMPANY WIDE SCORES (0-5 Scale):
    {prompt_data}
    
    INSTRUCTIONS:
    - Return ONLY raw HTML. Do not use Markdown backticks.
    - Tone: Strategic, executive-level, and objective.
    - Use <h3> for headers.
    
    REQUIRED OUTPUT FORMAT:
    <h3>Organizational Health Summary</h3>
    <p>(Narrative summary...)</p>
    
    <h3>Cultural Drivers</h3>
    <div style="display: flex; gap: 20px;">
        <div style="flex: 1;">
            <h4 style="color:#28a745; margin-bottom:5px;">Systemic Strengths</h4>
            <ul><li>(Analysis...)</li></ul>
        </div>
        <div style="flex: 1;">
            <h4 style="color:#d9534f; margin-bottom:5px;">Systemic Weaknesses</h4>
            <ul><li>(Analysis...)</li></ul>
        </div>
    </div>
    
    <h3>Strategic Recommendations</h3>
    <p><strong>Top 3 Priorities for Leadership:</strong></p>
    <ul>
        <li><strong>[Priority 1]:</strong> ...</li>
        <li><strong>[Priority 2]:</strong> ...</li>
        <li><strong>[Priority 3]:</strong> ...</li>
    </ul>
    """

    try:
        # --- FIX: Use Valid Model Name ---
        # Calls the Gemini API.
        # Note: Ensure the model version (e.g., 'gemini-2.5-flash-lite') is currently supported.
        response = client.models.generate_content(
            model='gemini-2.5-flash-lite', 
            contents=system_prompt
        )
        return jsonify({"analysis": response.text})
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return jsonify({"error": str(e)}), 500



# --- AI ANALYSIS ROUTE (With Caching) ---
@app.route('/analyze_response/<int:response_id>')
def analyze_response(response_id):
    # 1. Fetch Data
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM survey_responses WHERE id = %s", (response_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return jsonify({"error": "Response not found"}), 404

    # --- CACHE CHECK START ---
    # Check if we already have an analysis saved in the database
    # The .get() method handles cases where the column might be null
    if row.get('ai_analysis_text'):
        print(f"Serving cached analysis for Response ID {response_id}")
        return jsonify({"analysis": row['ai_analysis_text']})
    # --- CACHE CHECK END ---

    # 2. Construct the text prompt (If no cache found)
    answers = row['answers']
    prompt_data = ""
    
    for key, val in answers.items():
        if '_' in key and isinstance(val, int):
            parts = key.rsplit('_', 1)
            raw_cat = parts[0]
            index = int(parts[1]) - 1 

            # Normalize 'and' to '&' to match JSON keys
            if raw_cat in SURVEY_DATA:
                category = raw_cat
            elif raw_cat.replace(' and ', ' & ') in SURVEY_DATA:
                category = raw_cat.replace(' and ', ' & ')
            else:
                continue

            try:
                question_text = SURVEY_DATA[category][index]
                prompt_data += f"[{category}] {question_text}: {val}/5\n"
            except:
                continue

    # 3. System Prompt
    system_prompt = f"""
    You are an expert Organizational Psychologist and Senior HR Analyst.
    Analyze the following employee survey data.
    
    EMPLOYEE NAME: {row['respondent_name']}
    SURVEY DATA:
    {prompt_data}
    
    INSTRUCTIONS:
    - Return ONLY raw HTML. No Markdown.
    - Use <h3> for main headers.
    
    REQUIRED OUTPUT FORMAT:
    <h3>Executive Summary</h3>
    <p>(Summary...)</p>
    
    <h3>Psychological Drivers</h3>
    <p><strong>Motivations:</strong></p>
    <ul><li>...</li></ul>
    <p><strong>Frustrations:</strong></p>
    <ul><li>...</li></ul>
    
    <h3>Risk Analysis</h3>
    <ul><li><strong style="color:#d9534f">[Risk Category]:</strong> ...</li></ul>

    <h3>Action Plan</h3>
    <p><strong>Questions for 1-on-1 Meeting:</strong></p>
    <ul><li>...</li></ul>
    <p><strong>Organizational Improvements:</strong></p>
    <ul><li>...</li></ul>
    """

    # 4. Call Gemini & Save to Cache
    try:
        print(f"Calling Gemini API for Response ID {response_id}...")
        
        # using google-genai library syntax based on your requirements.txt
        response = client.models.generate_content(
            model='gemini-2.5-flash-lite',
            contents=system_prompt
        )
        analysis_text = response.text

        # --- SAVE TO DATABASE START ---
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "UPDATE survey_responses SET ai_analysis_text = %s WHERE id = %s",
                (analysis_text, response_id)
            )
            conn.commit()
            cur.close()
            conn.close()
            print("Analysis saved to database.")
        except Exception as db_e:
            print(f"Warning: Failed to cache analysis: {db_e}")
        # --- SAVE TO DATABASE END ---

        return jsonify({"analysis": analysis_text})

    except Exception as e:
        print(f"Gemini API Error: {e}")
        return jsonify({"error": str(e)}), 500
    

# --- Application Entry Point ---
# Runs the server in debug mode for local development.
# In production, this is handled by the WSGI server (Gunicorn).
if __name__ == '__main__':
    app.run(debug=True)