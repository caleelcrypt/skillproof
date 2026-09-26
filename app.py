from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import json
import os
import secrets
import qrcode
import io
import base64
import random
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-it'

DATA_DIR = 'data'
os.makedirs(DATA_DIR, exist_ok=True)

# ======================== HELPER FUNCTIONS ========================

def read_json(filename):
    path = os.path.join(DATA_DIR, filename)
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return []

def write_json(filename, data):
    path = os.path.join(DATA_DIR, filename)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def get_user_by_email(email):
    users = read_json('users.json')
    for user in users:
        if user['email'] == email:
            return user
    return None

def get_skill_by_id(skill_id):
    skills = read_json('skills.json')
    for skill in skills:
        if skill['id'] == skill_id:
            return skill
    return None

def generate_token():
    return secrets.token_hex(8)

def generate_cert_code():
    chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    code = 'SP-'
    for i in range(8):
        if i == 4:
            code += '-'
        code += chars[secrets.randbelow(len(chars))]
    return code

def get_questions_for_skill(skill_id):
    questions = read_json('questions.json')
    return [q for q in questions if q['skillId'] == skill_id]

def grade_answer(answer, keywords):
    if not answer:
        return 0
    answer_lower = answer.lower()
    matched = 0
    for kw in keywords:
        if kw.lower() in answer_lower:
            matched += 1
    return (matched / len(keywords)) * 100 if keywords else 50

def evaluate_test(questions, answers):
    if not questions:
        return 0
    total = 0
    for i, q in enumerate(questions):
        if i < len(answers):
            total += grade_answer(answers[i], q.get('keywords', []))
    return total / len(questions)

# ======================== ROUTES ========================

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = get_user_by_email(email)
        if user and user['password'] == password:
            session['user'] = user
            flash('Login successful!', 'success')
            if user['role'] == 'employer':
                return redirect('/employer')
            elif user['role'] == 'admin':
                return redirect('/admin')
            return redirect('/')
        flash('Invalid email or password', 'error')
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        if not name or not email or not password:
            flash('All fields required', 'error')
            return redirect('/signup')
        if get_user_by_email(email):
            flash('Email already exists', 'error')
            return redirect('/signup')
        users = read_json('users.json')
        new_user = {
            'id': 'emp' + str(len(users) + 1),
            'email': email,
            'fullName': name,
            'password': password,
            'role': 'employer',
            'createdAt': datetime.now().isoformat()
        }
        users.append(new_user)
        write_json('users.json', users)
        session['user'] = new_user
        flash('Account created!', 'success')
        return redirect('/employer')
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('Logged out', 'success')
    return redirect('/')

@app.route('/employer')
def employer_dashboard():
    if 'user' not in session or session['user']['role'] not in ['employer', 'admin']:
        flash('Please login as employer', 'error')
        return redirect('/login')
    
    user = session['user']
    invitations = read_json('invitations.json')
    my_invitations = [inv for inv in invitations if inv.get('employerId') == user['id']]
    skills = read_json('skills.json')
    certificates = read_json('certificates.json')
    
    return render_template('employer_dashboard.html', 
                         invitations=my_invitations, 
                         skills=skills,
                         certificates=certificates,
                         user=user)

@app.route('/create_invitation', methods=['POST'])
def create_invitation():
    if 'user' not in session:
        flash('Please login', 'error')
        return redirect('/login')
    
    skill_id = request.form.get('skill_id')
    time_limit = request.form.get('time_limit')
    if not time_limit:
        skill = get_skill_by_id(skill_id)
        time_limit = skill.get('defaultTimeLimit', 15) if skill else 15
    else:
        time_limit = int(time_limit)
    candidate_name = request.form.get('candidate_name')
    candidate_email = request.form.get('candidate_email')
    
    token = generate_token()
    invitations = read_json('invitations.json')
    new_inv = {
        'token': token,
        'employerId': session['user']['id'],
        'skillId': skill_id,
        'timeLimit': time_limit,
        'candidateName': candidate_name or None,
        'candidateEmail': candidate_email or None,
        'status': 'pending',
        'score': None,
        'answers': [],
        'selectedQuestionIds': [],
        'completedAt': None,
        'expired': False,
        'createdAt': datetime.now().isoformat()
    }
    invitations.append(new_inv)
    write_json('invitations.json', invitations)
    
    flash(f'✅ Test link created!', 'success')
    return redirect('/employer')

@app.route('/test/<token>')
def take_test(token):
    invitations = read_json('invitations.json')
    inv = None
    idx = None
    for i, inv_item in enumerate(invitations):
        if inv_item.get('token') == token:
            inv = inv_item
            idx = i
            break
    
    if not inv:
        flash('Invalid test link', 'error')
        return redirect('/')
    
    if inv.get('completedAt'):
        flash('This test has already been completed', 'error')
        return redirect('/')
    
    if inv.get('expired'):
        flash('This test link has expired', 'error')
        return redirect('/')
    
    questions = get_questions_for_skill(inv['skillId'])
    random.shuffle(questions)
    selected_questions = questions[:3]
    
    invitations[idx]['selectedQuestionIds'] = [q['id'] for q in selected_questions]
    write_json('invitations.json', invitations)
    
    skill = get_skill_by_id(inv['skillId'])
    
    return render_template('test.html', 
                         invitation=inv, 
                         questions=selected_questions,
                         time_limit=inv.get('timeLimit', 15),
                         skill=skill)

@app.route('/submit_test', methods=['POST'])
def submit_test():
    token = request.form.get('token')
    answers = request.form.getlist('answers[]')
    
    invitations = read_json('invitations.json')
    inv = None
    idx = None
    for i, inv_item in enumerate(invitations):
        if inv_item.get('token') == token:
            inv = inv_item
            idx = i
            break
    
    if not inv or inv.get('completedAt'):
        flash('Invalid or already completed test', 'error')
        return redirect('/')
    
    # FIX: Build questions in the EXACT order they were shown (using saved IDs)
    all_questions = get_questions_for_skill(inv['skillId'])
    selected_ids = inv.get('selectedQuestionIds', [])
    q_map = {q['id']: q for q in all_questions}
    selected = [q_map[qid] for qid in selected_ids if qid in q_map]
    
    if not selected:
        random.shuffle(all_questions)
        selected = all_questions[:3]
    
    score = evaluate_test(selected, answers)
    skill = get_skill_by_id(inv['skillId'])
    passing_score = skill.get('passingScore', 70) if skill else 70
    passed = score >= passing_score
    
    invitations[idx]['score'] = score
    invitations[idx]['answers'] = answers
    invitations[idx]['completedAt'] = datetime.now().isoformat()
    invitations[idx]['expired'] = True
    invitations[idx]['status'] = 'passed' if passed else 'failed'
    write_json('invitations.json', invitations)
    
    cert_data = None
    if passed:
        code = generate_cert_code()
        verify_url = f"{request.host_url}verify/{code}"
        cert_data = {
            'code': code,
            'candidateName': inv.get('candidateName', 'Candidate'),
            'skillName': skill.get('name', inv['skillId']) if skill else inv['skillId'],
            'score': round(score),
            'issuedAt': datetime.now().isoformat(),
            'expiresAt': (datetime.now() + timedelta(days=730)).isoformat(),
            'invitationToken': token,
            'employerId': inv['employerId'],
            'skillId': inv['skillId'],
            'verifyUrl': verify_url
        }
        certificates = read_json('certificates.json')
        certificates.append(cert_data)
        write_json('certificates.json', certificates)
    
    results = read_json('results.json')
    results.append({
        'name': inv.get('candidateName', 'Anonymous'),
        'skillId': inv['skillId'],
        'skillName': skill.get('name', inv['skillId']) if skill else inv['skillId'],
        'score': round(score),
        'passed': passed,
        'certificateCode': code if passed else None,
        'completedAt': datetime.now().isoformat(),
        'invitationToken': token,
        'answers': answers
    })
    write_json('results.json', results)
    
    return render_template('result.html', 
                         score=round(score), 
                         passed=passed, 
                         certificate=cert_data,
                         skill=skill,
                         skill_name=skill.get('name') if skill else inv['skillId'])

@app.route('/verify/<code>')
def verify_certificate(code):
    certificates = read_json('certificates.json')
    cert = None
    for c in certificates:
        if c.get('code') == code:
            cert = c
            break
    
    if not cert:
        return render_template('verify.html', certificate=None, code=code)
    
    expired = datetime.now().isoformat() > cert.get('expiresAt', '')
    cert['isValid'] = not expired
    
    return render_template('verify.html', certificate=cert, code=code)

@app.route('/answers/<token>')
def view_answers(token):
    """Employer can view candidate's submitted answers"""
    if 'user' not in session:
        flash('Please login', 'error')
        return redirect('/login')
    
    invitations = read_json('invitations.json')
    inv = None
    for i in invitations:
        if i.get('token') == token:
            inv = i
            break
    
    if not inv:
        flash('Invitation not found', 'error')
        return redirect('/employer')
    
    if inv.get('employerId') != session['user']['id']:
        flash('Unauthorized access', 'error')
        return redirect('/employer')
    
    questions = get_questions_for_skill(inv['skillId'])
    selected_ids = inv.get('selectedQuestionIds', [])
    if selected_ids:
        q_map = {q['id']: q for q in questions}
        questions = [q_map[qid] for qid in selected_ids if qid in q_map]
    
    return render_template('answers.html', 
                         invitation=inv, 
                         questions=questions,
                         answers=inv.get('answers', []))

@app.route('/delete_invitation/<token>')
def delete_invitation(token):
    """Delete a single invitation"""
    if 'user' not in session:
        flash('Please login', 'error')
        return redirect('/login')
    
    invitations = read_json('invitations.json')
    invitations = [inv for inv in invitations if inv.get('token') != token]
    write_json('invitations.json', invitations)
    
    flash('🗑️ Invitation deleted', 'success')
    return redirect('/employer')

@app.route('/clear_invitations')
def clear_invitations():
    """Delete all invitations for the logged-in employer"""
    if 'user' not in session:
        flash('Please login', 'error')
        return redirect('/login')
    
    user_id = session['user']['id']
    invitations = read_json('invitations.json')
    invitations = [inv for inv in invitations if inv.get('employerId') != user_id]
    write_json('invitations.json', invitations)
    
    flash('🗑️ All your invitations cleared', 'success')
    return redirect('/employer')

@app.route('/admin')
def admin_panel():
    if 'user' not in session or session['user']['role'] != 'admin':
        flash('Admin access required', 'error')
        return redirect('/login')
    
    skills = read_json('skills.json')
    questions = read_json('questions.json')
    certificates = read_json('certificates.json')
    results = read_json('results.json')
    
    return render_template('admin.html',
                         skills=skills,
                         questions=questions,
                         certificates=certificates,
                         results=results)

@app.route('/add_skill', methods=['POST'])
def add_skill():
    if 'user' not in session or session['user']['role'] != 'admin':
        flash('Unauthorized', 'error')
        return redirect('/admin')
    
    name = request.form.get('name')
    time_limit = int(request.form.get('time_limit', 15))
    passing_score = int(request.form.get('passing_score', 70))
    
    skills = read_json('skills.json')
    new_skill = {
        'id': name.lower().replace(' ', '_') + str(len(skills) + 1),
        'name': name,
        'description': '',
        'defaultTimeLimit': time_limit,
        'passingScore': passing_score
    }
    skills.append(new_skill)
    write_json('skills.json', skills)
    flash('Skill added!', 'success')
    return redirect('/admin')

@app.route('/add_question', methods=['POST'])
def add_question():
    if 'user' not in session or session['user']['role'] != 'admin':
        flash('Unauthorized', 'error')
        return redirect('/admin')
    
    skill_id = request.form.get('skill_id')
    text = request.form.get('text')
    keywords = request.form.get('keywords', '').split(',')
    
    questions = read_json('questions.json')
    new_q = {
        'id': 'q' + str(len(questions) + 1),
        'skillId': skill_id,
        'text': text,
        'keywords': [k.strip() for k in keywords if k.strip()]
    }
    questions.append(new_q)
    write_json('questions.json', questions)
    flash('Question added!', 'success')
    return redirect('/admin')

if __name__ == '__main__':
    app.run(debug=True)