"""
HR Survey Application - Main Application Entry Point
--------------------------------------------------
This Flask application handles:
1. Serving the Employee Survey interface.
2. Collecting and persisting responses to a PostgreSQL database.
3. Generating Admin Dashboards with statistical analysis.
4. Integrating Google Gemini AI for qualitative psychological profiling.
5. Managing Token-based Authentication.
"""
import os
import json
import psycopg2
from flask import Flask, render_template, request, jsonify
from psycopg2.extras import RealDictCursor
from datetime import datetime
import pytz

# --- 1. ROBUST DOTENV IMPORT ---
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
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        pass 
    conn = psycopg2.connect(db_url)
    return conn

def get_ist_time():
    """Returns current time in Indian Standard Time"""
    utc_now = datetime.now(pytz.utc)
    ist_tz = pytz.timezone('Asia/Kolkata')
    return utc_now.astimezone(ist_tz)

@app.route('/')
def index():
    return render_template('survey.html', survey_data=SURVEY_DATA)

@app.route('/submit', methods=['POST'])
def submit():
    form_data = request.form.to_dict()
    
    # 1. Extract Token
    token_input = form_data.pop('token', '').strip().upper()
    
    if not token_input:
        return render_template('survey.html', survey_data=SURVEY_DATA, error="Access Token is required.")

    # 2. Extract Data
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

        # --- TOKEN VALIDATION & BURNING ---
        # Check if token exists and is unused
        cur.execute("SELECT id, is_used FROM survey_tokens WHERE token_code = %s FOR UPDATE", (token_input,))
        token_row = cur.fetchone()

        if not token_row:
            cur.close()
            conn.close()
            return render_template('survey.html', survey_data=SURVEY_DATA, error="Invalid Access Token.")
        
        token_id, is_used = token_row
        
        if is_used:
            cur.close()
            conn.close()
            return render_template('survey.html', survey_data=SURVEY_DATA, error="This token has already been used.")

        # Mark token as used
        cur.execute("UPDATE survey_tokens SET is_used = TRUE, used_at = %s WHERE id = %s", (ist_now, token_id))
        
        # --- SAVE SURVEY RESPONSE ---
        cur.execute(
            "INSERT INTO survey_responses (respondent_name, answers, submitted_at) VALUES (%s, %s, %s)",
            (respondent_name, json.dumps(processed_answers), ist_now)
        )
        
        conn.commit()
        cur.close()
        conn.close()
        return render_template('survey.html', survey_data=SURVEY_DATA, success=True)
        
    except Exception as e:
        if conn: conn.rollback()
        return f"Database Error: {e}"


@app.route('/admin')
def admin():
    if request.args.get('key') != 'mysecretadminpassword':
        return "Access Denied."

    # --- 1. Date Filter Logic ---
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    query = "SELECT * FROM survey_responses"
    params = []
    
    if start_date and end_date:
        query += " WHERE submitted_at BETWEEN %s AND %s"
        params = [start_date, end_date + ' 23:59:59']
    
    query += " ORDER BY submitted_at DESC"

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Fetch Responses
    cur.execute(query, tuple(params))
    rows = cur.fetchall()

    # --- FETCH UNUSED TOKENS ---
    cur.execute("SELECT token_code FROM survey_tokens WHERE is_used = FALSE ORDER BY id ASC")
    token_rows = cur.fetchall()
    unused_tokens = [t['token_code'] for t in token_rows]

    cur.close()
    conn.close()

    ist_tz = pytz.timezone('Asia/Kolkata')
    processed_rows = []
    
    # --- Trend Data Storage ---
    monthly_scores = {} 
    
    for row in rows:
        utc_time = row['submitted_at']
        if utc_time:
            if utc_time.tzinfo is None:
                utc_time = pytz.utc.localize(utc_time)
            row['submitted_at'] = utc_time.astimezone(ist_tz)

        answers = row['answers']
        cat_totals = {k: [] for k in SURVEY_DATA.keys()}
        
        for key, val in answers.items():
            if isinstance(val, int) and '_' in key:
                parts = key.rsplit('_', 1)
                raw_cat = parts[0]
                if raw_cat in cat_totals:
                    category = raw_cat
                elif raw_cat.replace(' and ', ' & ') in cat_totals:
                    category = raw_cat.replace(' and ', ' & ')
                else:
                    continue
                cat_totals[category].append(val)
        
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
        
        if valid_categories_count > 0:
            overall = round(sum_of_category_averages / valid_categories_count, 2)
        else:
            overall = 0
        
        month_key = row['submitted_at'].strftime('%Y-%m')
        if month_key not in monthly_scores:
            monthly_scores[month_key] = []
        monthly_scores[month_key].append(overall)

        active_cats = {k:v for k,v in cat_averages.items() if v > 0}
        if active_cats:
            sorted_cats = sorted(active_cats.items(), key=lambda x: x[1], reverse=True)
            highest_score = sorted_cats[0][1]
            lowest_score = sorted_cats[-1][1]
            
            if highest_score == lowest_score:
                if highest_score == 5:
                    strength, weakness = ("All Categories", 5.0), ("None", 0)
                elif highest_score == 1:
                    strength, weakness = ("None", 0), ("All Categories", 1.0)
                else:
                    strength, weakness = ("Balanced", highest_score), ("Balanced", lowest_score)
            else:
                strength, weakness = sorted_cats[0], sorted_cats[-1]
        else:
            strength, weakness = ("N/A", 0), ("N/A", 0)

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

    sorted_months = sorted(monthly_scores.keys())
    trend_labels = []
    trend_data = []
    for m in sorted_months:
        display_date = datetime.strptime(m, '%Y-%m').strftime('%b %Y')
        trend_labels.append(display_date)
        avg_score = sum(monthly_scores[m]) / len(monthly_scores[m])
        trend_data.append(round(avg_score, 2))

    return render_template('admin.html', 
                         responses=processed_rows, 
                         survey_data=SURVEY_DATA,
                         trend_labels=trend_labels,
                         trend_data=trend_data,
                         start_date=start_date,
                         end_date=end_date,
                         unused_tokens=unused_tokens) # Passing tokens to template

# ... [Keep report routes exactly as they were, they don't need token logic] ...

# --- REPLACED REPORT ROUTE ---
@app.route('/report')
def report():
    if request.args.get('key') != 'mysecretadminpassword':
        return "Access Denied."

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM survey_responses ORDER BY submitted_at ASC") 
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return "No data available to generate report."

    selected_year = request.args.get('year')
    selected_month = request.args.get('month')
    
    available_years = sorted(list(set([row['submitted_at'].strftime('%Y') for row in rows])), reverse=True)
    present_month_nums = sorted(list(set([row['submitted_at'].strftime('%m') for row in rows])))
    month_map = {m: datetime.strptime(m, "%m").strftime("%B") for m in present_month_nums}

    trend_buckets = {}
    for row in rows:
        month_key = row['submitted_at'].strftime('%Y-%m')
        answers = row['answers']
        cat_sums = {}
        cat_counts = {}
        for key, val in answers.items():
            if isinstance(val, int) and '_' in key:
                raw_cat = key.rsplit('_', 1)[0]
                cat = raw_cat if raw_cat in SURVEY_DATA else raw_cat.replace(' and ', ' & ')
                if cat not in SURVEY_DATA: continue
                cat_sums[cat] = cat_sums.get(cat, 0) + val
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
        
        row_cat_avgs = []
        for cat in cat_sums:
            row_cat_avgs.append(cat_sums[cat] / cat_counts[cat])
        if row_cat_avgs:
            row_overall = sum(row_cat_avgs) / len(row_cat_avgs)
            if month_key not in trend_buckets: trend_buckets[month_key] = []
            trend_buckets[month_key].append(row_overall)

    trend_labels = []
    trend_data = []
    for m_key in sorted(trend_buckets.keys()):
        avg_score = sum(trend_buckets[m_key]) / len(trend_buckets[m_key])
        label = datetime.strptime(m_key, '%Y-%m').strftime('%b %Y')
        trend_labels.append(label)
        trend_data.append(round(avg_score, 2))

    filtered_rows = []
    for row in rows:
        row_year = row['submitted_at'].strftime('%Y')
        row_month = row['submitted_at'].strftime('%m')
        if selected_year and row_year != selected_year: continue
        if selected_month and row_month != selected_month: continue
        filtered_rows.append(row)

    if not filtered_rows:
        return render_template('report.html', 
                               averages={}, total=0, overall=0, strongest=("N/A",0), weakest=("N/A",0),
                               timestamp=get_ist_time().strftime('%Y-%m-%d %I:%M %p'),
                               available_years=available_years, month_map=month_map,
                               selected_year=selected_year, selected_month=selected_month,
                               trend_labels=trend_labels, trend_data=trend_data)

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

    text_corpus = ""
    for row in filtered_rows:
        answers = row['answers']
        for key, val in answers.items():
            if key.startswith('Comments') and isinstance(val, str):
                text_corpus += " " + val.lower()

    stop_words = set([
        'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', 'your', 'yours', 
        'he', 'him', 'his', 'she', 'her', 'hers', 'it', 'its', 'they', 'them', 'their', 
        'what', 'which', 'who', 'whom', 'this', 'that', 'these', 'those', 'am', 'is', 'are', 
        'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'having', 'do', 'does', 
        'did', 'doing', 'a', 'an', 'the', 'and', 'but', 'if', 'or', 'because', 'as', 'until', 
        'while', 'of', 'at', 'by', 'for', 'with', 'about', 'against', 'between', 'into', 
        'through', 'during', 'before', 'after', 'above', 'below', 'to', 'from', 'up', 'down', 
        'in', 'out', 'on', 'off', 'over', 'under', 'again', 'further', 'then', 'once', 'here', 
        'there', 'when', 'where', 'why', 'how', 'all', 'any', 'both', 'each', 'few', 'more', 
        'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 
        'than', 'too', 'very', 's', 't', 'can', 'will', 'just', 'don', 'should', 'now', 
        'bstl', 'company', 'organization'
    ])
    
    import re
    words = re.findall(r'\b[a-z]{3,}\b', text_corpus)
    word_counts = {}
    for word in words:
        if word not in stop_words:
            word_counts[word] = word_counts.get(word, 0) + 1
            
    sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:50]
    word_cloud_data = [[word, count] for word, count in sorted_words]

    return render_template('report.html', 
                           averages=final_averages, 
                           total=len(filtered_rows),
                           overall=overall_score,
                           strongest=strongest,
                           weakest=weakest,
                           timestamp=ist_now.strftime('%Y-%m-%d %I:%M %p'),
                           available_years=available_years,
                           month_map=month_map,
                           selected_year=selected_year,
                           selected_month=selected_month,
                           trend_labels=trend_labels,
                           trend_data=trend_data,
                           word_cloud_data=word_cloud_data)


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
        response = client.models.generate_content(
            model='gemini-2.5-flash-lite', 
            contents=system_prompt
        )
        return jsonify({"analysis": response.text})
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/analyze_response/<int:response_id>')
def analyze_response(response_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM survey_responses WHERE id = %s", (response_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return jsonify({"error": "Response not found"}), 404

    if row.get('ai_analysis_text'):
        print(f"Serving cached analysis for Response ID {response_id}")
        return jsonify({"analysis": row['ai_analysis_text']})

    answers = row['answers']
    prompt_data = ""
    
    for key, val in answers.items():
        if '_' in key and isinstance(val, int):
            parts = key.rsplit('_', 1)
            raw_cat = parts[0]
            index = int(parts[1]) - 1 

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

    try:
        print(f"Calling Gemini API for Response ID {response_id}...")
        response = client.models.generate_content(
            model='gemini-2.5-flash-lite',
            contents=system_prompt
        )
        analysis_text = response.text

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

        return jsonify({"analysis": analysis_text})

    except Exception as e:
        print(f"Gemini API Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)