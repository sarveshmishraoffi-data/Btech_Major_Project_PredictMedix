import os
import re
import pickle
import jwt
import datetime
import pandas as pd
from bson import ObjectId
from flask import Flask, request, render_template, send_from_directory, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user,current_user
from flask_mail import Mail, Message
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from flask_mail import Message
from flask import Flask, render_template, request, send_file, jsonify
from xhtml2pdf import pisa
from flask import make_response
import io
import shap



load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key')

# Register custom fromjson filter in Jinja
import json
app.jinja_env.filters['fromjson'] = json.loads

def clean_pdf_text(text):
    import re
    match = re.search(r'\(([^)]+)\)', text)
    if match:
        return match.group(1)
    return text

def clean_pdf_val(val_str):
    return val_str.replace("रुपये (INR)", "INR").replace("रुपये", "INR")

app.jinja_env.filters['clean_pdf_text'] = clean_pdf_text
app.jinja_env.filters['clean_pdf_val'] = clean_pdf_val

# MongoDB Configuration with Fallback
try:
    mongo_uri = os.getenv('MONGO_URI') or 'mongodb://localhost:27017/insurance_auth'
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=1000)
    # Test connection
    client.server_info()
    db = client['insurance_auth']
    users_collection = db['users']
    tokens_collection = db['tokens']
    print("Connected to MongoDB successfully.")
except Exception as e:
    print(f"MongoDB connection failed: {e}. Falling back to local db_fallback.json database.")
    import json
    
    class MockCollection:
        def __init__(self, filename, name):
            self.filename = filename
            self.name = name

        def _load(self):
            if not os.path.exists(self.filename):
                return {}
            try:
                with open(self.filename, 'r') as f:
                    data = json.load(f)
                    return data.get(self.name, {})
            except Exception:
                return {}

        def _save(self, data):
            all_data = {}
            if os.path.exists(self.filename):
                try:
                    with open(self.filename, 'r') as f:
                        all_data = json.load(f)
                except Exception:
                    pass
            all_data[self.name] = data
            try:
                with open(self.filename, 'w') as f:
                    json.dump(all_data, f, default=str)
            except Exception as e:
                print(f"Error saving mock db: {e}")

        def find_one(self, query):
            data = self._load()
            for item_id, item in data.items():
                match = True
                for k, v in query.items():
                    if isinstance(v, dict):
                        if '$gt' in v:
                            target = v['$gt']
                            val = item.get(k)
                            if val:
                                try:
                                    import datetime
                                    dt_val = datetime.datetime.fromisoformat(val)
                                except Exception:
                                    dt_val = val
                                if not (isinstance(dt_val, datetime.datetime) and dt_val > target):
                                    match = False
                                    break
                            else:
                                match = False
                                break
                        else:
                            match = False
                            break
                    else:
                        item_val = item_id if k == '_id' else item.get(k)
                        if str(item_val) != str(v):
                            match = False
                            break
                if match:
                    item_copy = item.copy()
                    item_copy['_id'] = ObjectId(item_id) if ObjectId.is_valid(item_id) else item_id
                    return item_copy
            return None

        def insert_one(self, doc):
            data = self._load()
            doc_id = str(ObjectId())
            if '_id' in doc:
                doc_id = str(doc['_id'])
            else:
                doc['_id'] = ObjectId(doc_id)
            doc_copy = doc.copy()
            doc_copy.pop('_id', None)
            data[doc_id] = doc_copy
            self._save(data)
            class InsertResult:
                def __init__(self, inserted_id):
                    self.inserted_id = inserted_id
            return InsertResult(ObjectId(doc_id))

        def update_one(self, query, update):
            data = self._load()
            for item_id, item in data.items():
                match = True
                for k, v in query.items():
                    item_val = item.get(k)
                    if str(item_val) != str(v):
                        match = False
                        break
                if match:
                    if '$set' in update:
                        for uk, uv in update['$set'].items():
                            item[uk] = uv
                        data[item_id] = item
                        self._save(data)
                        return True
            return False

        def delete_one(self, query):
            data = self._load()
            to_delete = None
            for item_id, item in data.items():
                match = True
                for k, v in query.items():
                    item_val = item.get(k)
                    if str(item_val) != str(v):
                        match = False
                        break
                if match:
                    to_delete = item_id
                    break
            if to_delete:
                del data[to_delete]
                self._save(data)
                return True
            return False

    users_collection = MockCollection('db_fallback.json', 'users')
    tokens_collection = MockCollection('db_fallback.json', 'tokens')


# Flask-Mail Configuration (kept for password reset functionality)
app.config.update(
    MAIL_SERVER=os.getenv('MAIL_SERVER'),
    MAIL_PORT=int(os.getenv('MAIL_PORT', 587)),
    MAIL_USE_TLS=os.getenv('MAIL_USE_TLS', 'true').lower() == 'true',
    MAIL_USERNAME=os.getenv('MAIL_USERNAME'),
    MAIL_PASSWORD=os.getenv('MAIL_PASSWORD'),
    MAIL_DEFAULT_SENDER=os.getenv('MAIL_DEFAULT_SENDER'),
    MAIL_DEBUG=True,
    MAIL_SUPPRESS_SEND=False
)
mail = Mail(app)

# Flask-Login Configuration
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['_id'])
        self.name = user_data.get('name', '') 
        self.email = user_data['email']
        self.mobile = user_data.get('mobile', '')
        self.is_verified = True  # Always set to True since we're skipping verification

@login_manager.user_loader
def load_user(user_id):
    try:
        user_data = users_collection.find_one({'_id': ObjectId(user_id)})
        return User(user_data) if user_data else None
    except Exception as e:
        print(f"User loader error: {e}")
        return None

# Load ML model
try:
    with open('insurancemodelf_fullfeatures.pkl', 'rb') as f:
        model = pickle.load(f)
except Exception as e:
    print(f"Model loading error: {e}")
    model = None

# Helper Functions
def generate_token(user_id, expiration=3600):
    return jwt.encode({
        'user_id': str(user_id),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=expiration)
    }, app.secret_key, algorithm='HS256')

def send_reset_email(email, token):
    try:
        url = url_for('reset_password', token=token, _external=True)
        msg = Message("Reset Your Password", recipients=[email])
        msg.body = f"Click to reset your password: {url}"
        mail.send(msg)
    except Exception as e:
        print(f"Reset Email Error: {e}")

def validate_mobile_number(number):
    return re.match(r'^[6-9]\d{9}$', number)

STATE_TO_ZONE = {
    # Northwest (0)
    'Jammu and Kashmir': 'northwest', 'Ladakh': 'northwest', 'Himachal Pradesh': 'northwest',
    'Punjab': 'northwest', 'Haryana': 'northwest', 'Uttarakhand': 'northwest',
    'Rajasthan': 'northwest', 'Delhi': 'northwest', 'Chandigarh': 'northwest',
    # Northeast (1)
    'Uttar Pradesh': 'northeast', 'Bihar': 'northeast', 'West Bengal': 'northeast',
    'Sikkim': 'northeast', 'Assam': 'northeast', 'Meghalaya': 'northeast',
    'Tripura': 'northeast', 'Mizoram': 'northeast', 'Manipur': 'northeast',
    'Nagaland': 'northeast', 'Arunachal Pradesh': 'northeast',
    # Southeast (2)
    'Odisha': 'southeast', 'Andhra Pradesh': 'southeast', 'Telangana': 'southeast',
    'Tamil Nadu': 'southeast', 'Puducherry': 'southeast', 'Andaman and Nicobar Islands': 'southeast',
    'Chhattisgarh': 'southeast', 'Jharkhand': 'southeast',
    # Southwest (3)
    'Gujarat': 'southwest', 'Maharashtra': 'southwest', 'Goa': 'southwest',
    'Karnataka': 'southwest', 'Kerala': 'southwest', 'Lakshadweep': 'southwest',
    'Dadra and Nagar Haveli and Daman and Diu': 'southwest', 'Madhya Pradesh': 'southwest'
}




# Routes ============>


@app.route('/')
def home():
    return render_template('index.html')

# signup Routes========>
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated: 
        return redirect(url_for('home'))

    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        middle_name = request.form.get('middle_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        
        # Construct full name for database compatibility
        name_parts = [first_name]
        if middle_name:
            name_parts.append(middle_name)
        if last_name:
            name_parts.append(last_name)
        name = " ".join(name_parts)

        email = request.form.get('email', '').strip()
        mobile = request.form.get('mobile', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        if not all([first_name, email, mobile, password, confirm]):
            flash('All mandatory fields are required!', 'danger')
            return redirect(url_for('signup'))

        if password != confirm:
            flash('Passwords dont match.', 'danger')
            return redirect(url_for('signup'))

        if not validate_mobile_number(mobile):
            flash('Invalid mobile number.', 'danger')
            return redirect(url_for('signup'))

        if users_collection.find_one({'email': email}) or users_collection.find_one({'mobile': mobile}):
            flash('Email or Mobile already exists.', 'danger')
            return redirect(url_for('signup'))

        hashed_pw = generate_password_hash(password)
        user = {
            'name': name,
            'email': email,
            'mobile': mobile,
            'password': hashed_pw,
            'is_verified': True,  # Automatically verified
            'created_at': datetime.datetime.utcnow()
        }
        result = users_collection.insert_one(user)
        
        # Immediately log the user in after signup
        login_user(User(user), remember=True)
        flash('Signup successful! You are now logged in.', 'success')
        return redirect(url_for('home'))

    return render_template('signup.html')




#  login Routes============>
@app.route('/login', methods=['GET', 'POST'])
def login():
    
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        remember = bool(request.form.get('remember'))

        user_data = users_collection.find_one({'email': email})
        if not user_data or not check_password_hash(user_data['password'], password):
            flash('Invalid credentials.', 'danger')
            return redirect(url_for('login'))

        # No email verification check anymore
        login_user(User(user_data), remember=remember)
        # flash('Logged in successfully!', 'success') 
        return redirect(url_for('home'))

    return render_template('login.html')





# logout Routes
@app.route('/logout')
@login_required
def logout():
    logout_user()
    # flash('logout successfully','success')
    return redirect(url_for('home'))


# forgot-password==========>
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        user_data = users_collection.find_one({'email': email})
        if user_data:
            token = generate_token(user_data['_id'], expiration=3600)
            tokens_collection.insert_one({
                'user_id': user_data['_id'],
                'token': token,
                'token_type': 'password_reset',
                'created_at': datetime.datetime.utcnow(),
                'expires_at': datetime.datetime.utcnow() + datetime.timedelta(hours=1)
            })
            send_reset_email(email, token)

        flash('If your email exists, a reset link has been sent.', 'info')
        return redirect(url_for('login'))
    return render_template('forgot_password.html')




# reset-password======>
@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        user_id = payload['user_id']

        token_data = tokens_collection.find_one({
            'user_id': ObjectId(user_id),
            'token': token,
            'token_type': 'password_reset',
            'expires_at': {'$gt': datetime.datetime.utcnow()}
        })

        if not token_data:
            flash('Invalid or expired reset link.', 'danger')
            return redirect(url_for('forgot_password'))

        if request.method == 'POST':
            pw = request.form['password']
            confirm = request.form['confirm_password']
            if pw != confirm:
                flash('Passwords do not match.', 'danger')
                return redirect(url_for('reset_password', token=token))

            hashed_pw = generate_password_hash(pw)
            users_collection.update_one({'_id': ObjectId(user_id)}, {'$set': {'password': hashed_pw}})
            tokens_collection.delete_one({'_id': token_data['_id']})
            flash('Password updated! You can login now.', 'success')
            return redirect(url_for('login'))

        return render_template('reset_password.html', token=token)

    except jwt.ExpiredSignatureError:
        flash('Reset link expired.', 'danger')
    except Exception:
        flash('Invalid reset link.', 'danger')
    return redirect(url_for('forgot_password'))


def generate_health_tips(data):
    tips = []

    # 1. BMI Tips tailored to Indian diet & habits
    if data['bmi'] < 18.5:
        tips.append("पोषक आहार: दाल, पनीर, दूध, केला और भीगे हुए बादाम/अखरोट का सेवन बढ़ाएं। (Nutritional tips: increase intake of dal, paneer, milk, banana, and soaked almonds/walnuts.)")
    elif 18.5 <= data['bmi'] < 25:
        tips.append("स्वस्थ आहार: घर का बना संतुलित भोजन खाएं। योग और प्राणायाम से स्वास्थ्य बनाए रखें। (Maintain health: eat balanced home-cooked Indian food. Practice yoga & pranayam regularly.)")
    elif 25 <= data['bmi'] < 30:
        tips.append("वजन नियंत्रण: समोसा, कचौरी, भुजिया जैसे तले-भुने स्नैक्स और चाय में चीनी कम करें। (Weight control: reduce fried snacks like samosas, kachoris, bhujia, and cut down sugar in tea/chai.)")
        tips.append("आहार सुधार: रिफाइंड चावल के बजाय रागी या बाजरा (millets) शामिल करें। (Diet improvement: incorporate millets like ragi or bajra instead of refined white rice.)")
    else:
        tips.append("अत्यधिक वजन: उच्च कैलोरी वाले भोजन (मिठाई, जंक फूड) से पूरी तरह परहेज करें। (Obesity warning: avoid high-calorie Indian sweets, desserts, and junk food entirely.)")
        tips.append("नियमित व्यायाम: रोजाना सुबह-शाम 30-40 मिनट की वॉक या सूर्य नमस्कार करें। (Regular exercise: practice a 30-40 minute brisk walk or Surya Namaskar daily.)")

    # 2. Smoking Tips
    if data['smoker'] == 'yes':
        tips.append("धूम्रपान/तंबाकू छोड़ें: यह हृदय रोग और कैंसर के खतरे को कम करेगा। (Quit smoking/tobacco: this significantly reduces risks of stroke, heart disease, and cancer.)")
    else:
        tips.append("धूम्रपान न करना: आपकी फेफड़ों और हृदय की सेहत के लिए यह बहुत उत्तम आदत है। (Non-smoking: this is a great habit for long-term respiratory and cardiovascular health.)")

    # 3. Age Tips
    if data['age'] >= 45:
        tips.append("आयु स्वास्थ्य: 45 वर्ष से ऊपर नियमित रक्तचाप (BP) और लिपिड प्रोफाइल टेस्ट करवाएं। (Age advice: above 45, ensure regular blood pressure checking and lipid profile screenings.)")
    elif data['age'] < 18:
        tips.append("युवा स्वास्थ्य: खेल-कूद और शारीरिक गतिविधियों में भाग लें, ताज़ा भोजन खाएं। (Youth tips: participate in outdoor sports/activities and prioritize fresh, home-cooked meals.)")

    # 4. Gender Tips
    if data['sex'] == 'female':
        tips.append("महिला स्वास्थ्य: भारतीय महिलाओं में एनीमिया का खतरा रहता है, पालक, दालें और अनार खाएं। (Women's health: prioritize iron and calcium rich foods like spinach, lentils, and pomegranates.)")
    elif data['sex'] == 'male':
        tips.append("पुरुष स्वास्थ्य: हृदय स्वास्थ्य के प्रति सतर्क रहें, दैनिक तनाव कम करने के लिए ध्यान करें। (Men's health: stay vigilant of cardiovascular health and practice meditation to reduce daily stress.)")

    # 5. Children Tips
    if data['children'] > 2:
        tips.append(f"पारिवारिक स्वास्थ्य: बच्चों के संतुलित पोषण और समय पर टीकाकरण (Vaccination) का ध्यान रखें। (Family health: focus on balanced nutrition and timely immunization/vaccination for your children.)")

    # 6. Region Tips
    region_tips = {
        'northeast': "क्षेत्रीय सलाह: पूर्वोत्तर के नमी वाले मौसम में हाइड्रेटेड रहें और स्थानीय जड़ी-बूटियाँ शामिल करें। (Regional advice: stay hydrated in northeast humidity; consume local seasonal herbs and greens.)",
        'northwest': "क्षेत्रीय सलाह: उत्तर-पश्चिम की गर्मी/सर्दी में मौसमी बदलाव के अनुसार खान-पान रखें। (Regional advice: adjust diet dynamically according to seasonal shifts in the northwest climate.)",
        'southeast': "क्षेत्रीय सलाह: दक्षिण-पूर्व तटीय क्षेत्रों में ताज़ा समुद्री भोजन और नारियल पानी का उपयोग करें। (Regional advice: utilize fresh local coastal produce and coconut water in the southeast.)",
        'southwest': "क्षेत्रीय सलाह: दक्षिण-पश्चिम क्षेत्र में मानसून के दौरान गर्म ताज़ा भोजन और हल्दी वाले दूध का सेवन करें। (Regional advice: consume hot fresh food and turmeric milk during the southwest monsoon.)"
    }
    region_tip = region_tips.get(data.get('region_zone') or data.get('region'), "")
    if region_tip:
        tips.append(region_tip)

    # 7. Hypertension Tips (New)
    if data.get('hypertension') == 'yes':
        tips.append("उच्च रक्तचाप (Hypertension): नमक, पापड़, अचार, और पैकेट बंद नमकीन का सेवन कम करें। (Hypertension care: drastically reduce salt intake, pickles, papads, and processed namkeen.)")
        tips.append("बीपी ट्रैकिंग: सप्ताह में कम से कम एक बार ब्लड प्रेशर मापें और doctor की सलाह लें। (BP tracking: monitor your blood pressure at least once a week and follow physician guidelines.)")

    # 8. Diabetes Tips (New)
    if data.get('diabetes') == 'yes':
        tips.append("मधुमेह (Diabetes): सफेद चावल, मैदा, और चीनी वाली चाय से बचें। साबुत अनाज खाएं। (Diabetes care: avoid white rice, maida, and sweet milk tea. Shift to whole grains.)")
        tips.append("शुगर ट्रैकिंग: खाली पेट और खाने के बाद नियमित रूप से शुगर की जांच करें। (Glucose tracking: monitor fasting and postprandial blood glucose levels regularly.)")

    # 9. Activity Level Tips (New)
    activity = data.get('activity_level', 'lightly_active')
    if activity == 'sedentary':
        tips.append("शारीरिक सक्रियता: दिन की शुरुआत 10 मिनट के प्राणायाम और वॉक से करें। (Activity warning: begin your routine with 10 minutes of Pranayam and gentle walking.)")
    elif activity == 'highly_active':
        tips.append("सक्रिय जीवनशैली: प्रोटीन युक्त आहार लें (पनीर, दाल, सत्तू) जो मांसपेशियों को शक्ति दे। (High activity diet: ensure adequate protein intake from Indian sources like paneer, dal, and sattu.)")

    return tips


def suggest_insurance_plans(age, smoker, hypertension, diabetes, bmi, children):
    # Determine recommended sum insured based on risk factors
    if age > 50 or smoker == 'yes' or hypertension == 'yes' or diabetes == 'yes' or bmi > 30:
        recommended_sum_insured = "₹10,00,000 (10 Lakhs)"
    else:
        recommended_sum_insured = "₹5,00,000 (5 Lakhs)"

    # Calculate dynamically adjusted premiums based on age and smoker/disease load
    age_factor = max(1.0, age / 30.0)
    risk_multiplier = 1.0
    if smoker == 'yes':
        risk_multiplier += 0.25
    if hypertension == 'yes':
        risk_multiplier += 0.15
    if diabetes == 'yes':
        risk_multiplier += 0.20
    if children > 0:
        risk_multiplier += (0.15 * children) # Family Floater loading

    plans = [
        {
            'company': "HDFC ERGO",
            'plan_name': "Optima Secure (Super Premium)",
            'premium_annual': round(9500 * age_factor * risk_multiplier),
            'sum_insured': recommended_sum_insured,
            'waiting_period': "2 Years for pre-existing diseases",
            'term': "1, 2, or 3 Years",
            'pros': [
                "2x Coverage: Doubles coverage amount automatically from Day 1 at no extra cost.",
                "Zero Deductions: 100% payout on consumables & non-medical items.",
                "Unlimited Restore: Refills sum insured unlimited times if exhausted."
            ],
            'cons': [
                "Higher Premium: Premium is 15-20% higher compared to budget segment plans.",
                "Waiting Period: Strict 2-year waiting period for pre-existing hypertension or diabetes."
            ],
            'copayment': "0% Co-payment (No sharing of hospital bills)",
            'website': "www.hdfcergo.com",
            'head_office': "Connaught Place, New Delhi (Capital NCR)",
            'branch_office': "District Court Road Complex, Sector 12",
            'suitability_score': 95 if (smoker == 'yes' or hypertension == 'yes' or diabetes == 'yes') else 85,
            'category': "Best Value & High Coverage"
        },
        {
            'company': "Niva Bupa",
            'plan_name': "ReAssure 2.0 (Modern Tech-focused)",
            'premium_annual': round(8200 * age_factor * risk_multiplier),
            'sum_insured': recommended_sum_insured,
            'waiting_period': "3 Years for pre-existing diseases",
            'term': "1 to 3 Years",
            'pros': [
                "ReAssure Forever: Unlimited sum insured triggers for any illness in the policy year.",
                "Lock-the-Premium: Premium rate is locked and won't increase until you make a claim.",
                "Booster+ Benefit: Unused base sum insured carries forward up to 10x maximum."
            ],
            'cons': [
                "3 Years Pre-Existing Waiting Period: Waiting period of 36 months for pre-existing conditions.",
                "Co-pay on Zone upgrade: 20% co-payment applies if treated in a higher-tier zone than registered."
            ],
            'copayment': "0% Co-payment (subject to zone boundaries)",
            'website': "www.nivabupa.com",
            'head_office': "Nehru Place, New Delhi (Capital NCR)",
            'branch_office': "Metro Pillar 42, Main Mall Road Area",
            'suitability_score': 90 if age < 45 else 78,
            'category': "Best for Young Adults & Families"
        },
        {
            'company': "Care Health",
            'plan_name': "Care Supreme (Budget Saver)",
            'premium_annual': round(6800 * age_factor * risk_multiplier),
            'sum_insured': recommended_sum_insured,
            'waiting_period': "4 Years for pre-existing diseases",
            'term': "1 to 3 Years",
            'pros': [
                "Value for Money: Highly affordable annual premiums suitable for budget buyers.",
                "No Room Rent Sub-limits: Choose any single private room without capping rules.",
                "Free Health Checkups: Annual diagnostic health checks for all members."
            ],
            'cons': [
                "4 Years Pre-Existing Waiting Period: Longest wait time (48 months) for diabetes/BP claims.",
                "Treatment Sub-limits: Capped payouts on cataract and joint replacement surgeries."
            ],
            'copayment': "0% Co-payment (unless age > 60, where 20% co-payment applies)",
            'website': "www.careinsurance.com",
            'head_office': "Sector 32, Gurugram, Haryana (Capital NCR)",
            'branch_office': "Ground Floor, Block A Commercial Complex",
            'suitability_score': 88 if children > 0 else 82,
            'category': "Most Economical / Value-for-Money"
        },
        {
            'company': "Star Health",
            'plan_name': "Star Assure Insurance (Senior & Comprehensive)",
            'premium_annual': round(8900 * age_factor * risk_multiplier),
            'sum_insured': recommended_sum_insured,
            'waiting_period': "3 Years for pre-existing diseases",
            'term': "1, 2, or 3 Years",
            'pros': [
                "Robotic Surgery Cover: Up to 100% cover for advanced surgeries and robotic treatments.",
                "Assure Benefit: Direct 100% additional sum insured on renewals.",
                "No Claim Bonus: Up to 100% bonus accumulation on sum insured."
            ],
            'cons': [
                "No Premium Lock: Annual premium rates increase with age bracket transitions.",
                "Co-payment on Pre-existing: Up to 10% co-payment may apply for specific pre-existing loads."
            ],
            'copayment': "10% Co-payment on pre-existing diseases",
            'website': "www.starhealth.in",
            'head_office': "Nariman Point, Mumbai (Maharashtra Capital)",
            'branch_office': "Station Road Crossing, Near Central Bank Branch",
            'suitability_score': 92 if age >= 50 else 80,
            'category': "Best for Middle-aged & Senior Citizens"
        }
    ]

    # Sort plans by suitability score (descending)
    plans.sort(key=lambda x: x['suitability_score'], reverse=True)
    return plans


def calculate_health_score(steps, bp_sys, bp_dia, heart_rate, sleep_duration, sleep_quality, spo2, active_mins, water_intake, stress_level, alcohol, sugar, salt, sitting_time, exercise_freq, hrv, resp_rate):
    score = 100
    
    # 1. Steps
    if steps < 5000: score -= 10
    elif steps < 8000: score -= 5
    elif steps >= 10000: score += 2
    
    # 2. Blood Pressure
    if bp_sys > 140 or bp_dia > 90: score -= 12
    elif bp_sys > 130 or bp_dia > 85: score -= 6
    
    # 3. Heart Rate
    if heart_rate > 85 or heart_rate < 50: score -= 5
    
    # 4. Sleep
    if sleep_duration < 6: score -= 8
    elif sleep_duration < 7: score -= 4
    if sleep_quality < 70: score -= 6
    
    # 5. SpO2
    if spo2 < 95: score -= 15
    
    # 6. Active Minutes
    if active_mins < 30: score -= 6
    
    # 7. Water
    if water_intake < 2.0: score -= 4
    
    # 8. Stress
    if stress_level > 7: score -= 8
    elif stress_level > 4: score -= 4
    
    # 9. Alcohol
    if alcohol == 'heavy': score -= 12
    elif alcohol == 'moderate': score -= 6
    
    # 10. Sugar & Salt
    if sugar > 50: score -= 6
    if salt > 6: score -= 5
    
    # 11. Sitting Time
    if sitting_time > 8: score -= 6
    
    # 12. Exercise Frequency
    if exercise_freq < 3: score -= 6
    
    # 13. HRV & Resp Rate
    if hrv < 45: score -= 5
    if resp_rate > 20 or resp_rate < 12: score -= 4
    
    return max(10, min(100, score))


@app.route('/predict', methods=['POST'])
@login_required
def predict():
    try:
        if model is None:
            return render_template('index.html', prediction_text="Model not loaded. Contact admin.")

        # 🔹 Extract form data from the user and calculate BMI (with fallback for cached forms)
        if 'weight' in request.form and 'height' in request.form:
            weight = float(request.form['weight'])
            height = float(request.form['height'])
            weight_unit = request.form.get('weight_unit', 'kg')
            height_unit = request.form.get('height_unit', 'cm')
            
            # Unit conversions to standard metric (kg & cm)
            if weight_unit == 'lbs':
                weight_kg = weight * 0.45359237
                weight_display = f"{weight} lbs ({round(weight_kg, 1)} kg)"
            else:
                weight_kg = weight
                weight_display = f"{weight} kg"
                
            if height_unit == 'm':
                height_cm = height * 100
                height_display = f"{height} m ({round(height_cm, 1)} cm)"
            elif height_unit == 'in':
                height_cm = height * 2.54
                height_display = f"{height} inches ({round(height_cm, 1)} cm)"
            else:
                height_cm = height
                height_display = f"{height} cm"
                
            bmi = weight_kg / ((height_cm / 100) ** 2)
        elif 'bmi' in request.form:
            bmi = float(request.form['bmi'])
            weight = 0.0
            height = 0.0
            weight_unit = 'kg'
            height_unit = 'cm'
            weight_display = "N/A"
            height_display = "N/A"
        else:
            return render_template('index.html', prediction_text="Error: Missing form inputs. Please reload the home page and try again.")

        # Resolve Indian State / UT to zone
        state = request.form['region']
        zone = STATE_TO_ZONE.get(state, state) # if already zone (cached US submission) or not in map, keep it

        # Extract Wearable & Lifestyle details
        steps = int(request.form.get('step_count', 8500))
        bp_sys = int(request.form.get('bp_sys', 120))
        bp_dia = int(request.form.get('bp_dia', 80))
        heart_rate = int(request.form.get('heart_rate', 68))
        sleep_duration = float(request.form.get('sleep_duration', 7.5))
        sleep_quality = int(request.form.get('sleep_quality', 88))
        spo2 = int(request.form.get('spo2', 98))
        active_mins = int(request.form.get('active_mins', 50))
        calories_burned = int(request.form.get('calories_burned', 2200))
        water_intake = float(request.form.get('water_intake', 2.5))
        stress_level = int(request.form.get('stress_level', 3))
        alcohol = request.form.get('alcohol', 'none')
        sugar = int(request.form.get('sugar', 28))
        salt = int(request.form.get('salt', 5))
        sitting_time = int(request.form.get('sitting_time', 6))
        exercise_freq = int(request.form.get('exercise_freq', 5))
        hrv = int(request.form.get('hrv', 58))
        resp_rate = int(request.form.get('resp_rate', 16))

        health_score = calculate_health_score(
            steps, bp_sys, bp_dia, heart_rate, sleep_duration, sleep_quality, spo2, active_mins,
            water_intake, stress_level, alcohol, sugar, salt, sitting_time, exercise_freq, hrv, resp_rate
        )

        form_data = {
            'name': current_user.name,
            'age': int(request.form['age']),
            'sex': request.form['sex'],
            'weight': weight,
            'weight_unit': weight_unit,
            'weight_display': weight_display,
            'height': height,
            'height_unit': height_unit,
            'height_display': height_display,
            'bmi': round(bmi, 2),
            'children': int(request.form['children']),
            'smoker': request.form['smoker'],
            'region': state,
            'region_zone': zone,
            'hypertension': request.form.get('hypertension', 'no'),
            'diabetes': request.form.get('diabetes', 'no'),
            'activity_level': request.form.get('activity_level', 'lightly_active'),
            
            # Smart Wearables
            'steps': steps,
            'bp_sys': bp_sys,
            'bp_dia': bp_dia,
            'heart_rate': heart_rate,
            'sleep_duration': sleep_duration,
            'sleep_quality': sleep_quality,
            'spo2': spo2,
            'active_mins': active_mins,
            'calories_burned': calories_burned,
            'water_intake': water_intake,
            'stress_level': stress_level,
            'alcohol': alcohol,
            'sugar': sugar,
            'salt': salt,
            'sitting_time': sitting_time,
            'exercise_freq': exercise_freq,
            'hrv': hrv,
            'resp_rate': resp_rate,
            'health_score': health_score
        }

        # 🔹 Convert form data to model-friendly format
        model_data = {
            'age': form_data['age'],
            'sex': 0 if form_data['sex'] == 'male' else 1,
            'bmi': form_data['bmi'],
            'children': form_data['children'],
            'smoker': 1 if form_data['smoker'] == 'yes' else 0,
            'region': {'northwest': 0, 'northeast': 1, 'southeast': 2, 'southwest': 3}.get(zone, 0)
        }

        # 🔹 Predict current year cost
        df = pd.DataFrame([model_data])
        current_cost = model.predict(df)[0]
        form_data['cost'] = f"{current_cost:,.2f}"

        # Cost Breakdown
        form_data['hosp_charges'] = f"{(current_cost * 0.55):,.2f}"
        form_data['test_charges'] = f"{(current_cost * 0.15):,.2f}"
        form_data['consult_charges'] = f"{(current_cost * 0.10):,.2f}"
        form_data['medicine_charges'] = f"{(current_cost * 0.20):,.2f}"

        # Biological Health Age
        health_age = form_data['age']
        if health_score >= 85:
            health_age = max(18, form_data['age'] - 3)
        elif health_score < 65:
            health_age = form_data['age'] + 4
        form_data['health_age'] = health_age

        # Disease Risk Estimation
        form_data['risk_obesity'] = "High Risk" if bmi > 25 else "Normal"
        form_data['risk_hypertension'] = "High Risk" if bp_sys > 135 or bp_dia > 85 or form_data['smoker'] == 'yes' or form_data.get('hypertension') == 'yes' else "Normal"
        form_data['risk_diabetes'] = "High Risk" if sugar > 40 or (bmi > 27 and form_data['activity_level'] == 'sedentary') or form_data.get('diabetes') == 'yes' else "Normal"

        # Risk Category
        if current_cost > 15000:
            risk_category = "Very High"
        elif current_cost > 8000:
            risk_category = "High"
        elif current_cost > 4000:
            risk_category = "Moderate"
        else:
            risk_category = "Low"
        form_data['risk_category'] = risk_category

        # Emergency Alerts
        emergency_alerts = []
        if spo2 < 95:
            emergency_alerts.append("SpO₂ warning: Low blood oxygen level detected! (SpO₂ < 95%)")
        if bp_sys > 140 or bp_dia > 90:
            emergency_alerts.append("Blood Pressure warning: Elevated blood pressure detected!")
        if heart_rate > 100:
            emergency_alerts.append("Heart Rate warning: Tachycardia risk (HR > 100 bpm)")
        form_data['emergency_alerts'] = emergency_alerts

        # 🔹 Explanation & Health Tips
        try:
            explanations = explain_prediction(model, model_data)
        except Exception as e:
            explanations = [f"AI खर्च का विश्लेषण नहीं कर सका (AI could not analyze the expense): {e}"]

        form_data['explanations'] = explanations
        form_data['health_tips'] = generate_health_tips(form_data)
        form_data['insurance_plans'] = suggest_insurance_plans(
            form_data['age'],
            form_data['smoker'],
            form_data['hypertension'],
            form_data['diabetes'],
            form_data['bmi'],
            form_data['children']
        )


        # 🔹 Future prediction check
        future_predictions = []
        if request.form.get("future_prediction") == "yes":
            base_age = model_data['age']
            base_bmi = model_data['bmi']
            current_smoker = model_data['smoker']
            for i in range(1, 6):
                future_model_data = model_data.copy()
                future_model_data['age'] = base_age + i
                future_model_data['bmi'] = base_bmi + (0.5 * i)  # Slight BMI increase yearly

                df_future = pd.DataFrame([future_model_data])
                future_cost = model.predict(df_future)[0]
                future_predictions.append({
                    'year': 2025 + i,
                    'cost': f"{future_cost:,.2f}"
                })

        form_data['future_predictions'] = future_predictions

        # 🔹 Return final report page
        return render_template('report.html', **form_data)

    except Exception as e:
        return render_template('index.html', prediction_text=f'Error: {str(e)}')





# How AI interpreted this expense
def explain_prediction(model, input_data):
    try:
        input_df = pd.DataFrame([input_data])

        # Use TreeExplainer for tree-based models
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(input_df)

        feature_labels = {
            'age': 'उम्र का असर (Effect of Age)',
            'sex': 'लिंग का असर (Effect of Gender)',
            'bmi': 'BMI का असर (Effect of BMI)',
            'children': 'बच्चों की संख्या का असर (Effect of Number of Children)',
            'smoker': 'धूम्रपान स्थिति का असर (Effect of Smoking Status)',
            'region': 'क्षेत्र का असर (Effect of Region)'
        }

        explanations = []
        for i, feature in enumerate(input_df.columns):
            label = feature_labels.get(feature, feature)
            value = shap_values[0][i]
            explanations.append(f"{label}: {value:.2f} रुपये (INR)")

        return explanations

    except Exception as e:
        return [f"AI खर्च का विश्लेषण नहीं कर सका (AI could not analyze the expense): {e}"]







@app.route('/generate_pdf', methods=['POST'])
def generate_pdf():
    try:
        html = render_template('report.html', **request.form)   
        pdf = io.BytesIO()
        pisa_status = pisa.CreatePDF(html, dest=pdf)

        if pisa_status.err:
            return "PDF Generation Error", 500

        pdf.seek(0)
        return send_file(pdf, download_name='medical_report.pdf', as_attachment=True)

    except Exception as e:
        return f"PDF Generation Failed: {str(e)}", 500









@app.route('/about')
# @login_required
def about():
    return render_template('about.html')

@app.route('/contact')
# @login_required
def contact():
    return render_template('contact.html')

@app.route('/resumes/<filename>')
# @login_required
def download_resume(filename):
    os.makedirs('resumes', exist_ok=True)
    return send_from_directory('resumes', filename, as_attachment=True)


import math
import requests

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371.0 # Earth's radius in km
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def get_nearby_transit(name, lat=None, lon=None):
    import random
    name_lower = name.lower()
    if "aiims" in name_lower:
        return "Metro: AIIMS Metro Station (350m) | Bus: Safdarjung terminal (500m)"
    elif "apollo" in name_lower:
        return "Bus: Apollo Hospital Junction (80m) | Metro: Jasola Apollo Metro (400m)"
    elif "max" in name_lower:
        return "Metro: Saket Metro Station (750m) | Bus: Press Enclave Stand (150m)"
    elif "fortis" in name_lower:
        return "Metro: Shalimar Bagh Metro (650m) | Bus: Fortis Crossing (100m)"
    
    # Deterministic generation using coordinate seed or name length
    seed_val = int(abs(lat * 1000) + abs(lon * 1000)) if lat and lon else len(name)
    random.seed(seed_val)
    
    prefix = name.split()[0] if name.split() else "City"
    transit_options = [
        f"Metro: {prefix} Metro Station ({random.randint(2, 8)}00m) | Bus: Crossing Stop ({random.randint(50, 200)}m)",
        f"Bus: {prefix} Bus Stand ({random.randint(100, 300)}m) | Rail: Local Station ({round(random.uniform(1.2, 3.2), 1)} km)",
        f"Metro: Line 1 Crossing ({random.randint(300, 750)}m) | Bus: Depot Corner ({random.randint(80, 250)}m)",
        f"Bus: Panchayat Office Junction ({random.randint(50, 180)}m) | Rail: Junction Station ({round(random.uniform(2.0, 4.0), 1)} km)"
    ]
    return random.choice(transit_options)

@app.route('/hospitals')
@login_required
def hospitals():
    return render_template('hospitals.html')

@app.route('/api/nearby_hospitals')
@login_required
def api_nearby_hospitals():
    try:
        lat = float(request.args.get('lat', 28.6139))  # Delhi lat default
        lon = float(request.args.get('lon', 77.2090))  # Delhi lon default
        search_type = request.args.get('type', 'hospital')  # hospital or pharmacy
        
        hospitals_list = []
        
        # 1. Try OSM Overpass API (Free, Real-time)
        try:
            overpass_url = "https://overpass-api.de/api/interpreter"
            amenity = "hospital" if search_type == 'hospital' else "pharmacy"
            query = f"""
            [out:json][timeout:10];
            (
              node["amenity"="{amenity}"](around:12000,{lat},{lon});
              way["amenity"="{amenity}"](around:12000,{lat},{lon});
              relation["amenity"="{amenity}"](around:12000,{lat},{lon});
            );
            out center;
            """
            response = requests.post(overpass_url, data={'data': query}, timeout=6)
            if response.status_code == 200:
                data = response.json()
                elements = data.get('elements', [])
                for el in elements:
                    name = el.get('tags', {}).get('name')
                    if not name:
                        continue
                    
                    # Determine coordinates
                    h_lat = el.get('lat') or el.get('center', {}).get('lat')
                    h_lon = el.get('lon') or el.get('center', {}).get('lon')
                    
                    if h_lat and h_lon:
                        dist = calculate_distance(lat, lon, h_lat, h_lon)
                    else:
                        dist = 5.0 # default fallback distance
                        
                    # Categorize based on type and name keywords
                    name_lower = name.lower()
                    
                    if search_type == 'hospital':
                        if any(kw in name_lower for kw in ["aiims", "all india institute", "apex"]):
                            category = "Apex Government (AIIMS Level)"
                            cat_id = "aiims"
                            badge_class = "badge-danger"
                        elif any(kw in name_lower for kw in ["civil", "district", "government", "govt", "chc", "phc", "municipal", "primary health", "community health"]):
                            category = "Govt Hospital / CHC / PHC"
                            cat_id = "govt"
                            badge_class = "badge-success"
                        elif any(kw in name_lower for kw in ["charitable", "trust", "seva", "sewa", "mission", "free"]):
                            category = "Charitable / Funded Free Hospital"
                            cat_id = "charitable"
                            badge_class = "badge-warning"
                        else:
                            category = "Private Medical Hospital"
                            cat_id = "private"
                            badge_class = "badge-info"
                    else:
                        # Pharmacy categories
                        if any(kw in name_lower for kw in ["aushadhi", "jan", "government", "govt", "pmbjky", "pradhan mantri"]):
                            category = "Jan Aushadhi Kendra (Govt)"
                            cat_id = "aushadhi"
                            badge_class = "badge-success"
                        elif any(kw in name_lower for kw in ["apollo", "medplus", "netmeds", "wellness", "generic", "religare"]):
                            category = "Chain Pharmacy / Store"
                            cat_id = "chain"
                            badge_class = "badge-info"
                        else:
                            category = "Local Chemist / Pharmacy"
                            cat_id = "local"
                            badge_class = "badge-warning"
                        
                    hospitals_list.append({
                        'name': name,
                        'category': category,
                        'cat_id': cat_id,
                        'badge_class': badge_class,
                        'distance': round(dist, 2),
                        'lat': h_lat,
                        'lon': h_lon,
                        'address': el.get('tags', {}).get('addr:street') or el.get('tags', {}).get('addr:full') or "Nearby Location",
                        'transit': get_nearby_transit(name, h_lat, h_lon)
                    })
        except Exception as e:
            print(f"Overpass API error: {e}")
            
        # 2. Fallback to mock data if Overpass returned nothing or failed
        if not hospitals_list:
            if search_type == 'hospital':
                mock_data = [
                    {
                        'name': "All India Institute of Medical Sciences (AIIMS Sub-centre)",
                        'category': "Apex Government (AIIMS Level)",
                        'cat_id': "aiims",
                        'badge_class': "badge-danger",
                        'distance': 1.8,
                        'address': "Main Gateway Road, Sector 4",
                        'transit': "Metro: AIIMS Metro Station (350m) | Bus: Safdarjung terminal (500m)"
                    },
                    {
                        'name': "District Civil & Maternity Government Hospital",
                        'category': "Govt Hospital / CHC / PHC",
                        'cat_id': "govt",
                        'badge_class': "badge-success",
                        'distance': 3.2,
                        'address': "Near Block Development Office, Civil Lines",
                        'transit': "Metro: Civil Lines Metro (700m) | Bus: Civil Lines Bus Stand (200m)"
                    },
                    {
                        'name': "Community Block Primary Health Centre (PHC)",
                        'category': "Govt Hospital / CHC / PHC",
                        'cat_id': "govt",
                        'badge_class': "badge-success",
                        'distance': 5.5,
                        'address': "Rural Bypass Circle, Ward 2",
                        'transit': "Rail: Gurgaon Railway Station (2.5 km) | Bus: PHC Village Stop (100m)"
                    },
                    {
                        'name': "Red Cross Charitable Trust & Seva Hospital",
                        'category': "Charitable / Funded Free Hospital",
                        'cat_id': "charitable",
                        'badge_class': "badge-warning",
                        'distance': 4.1,
                        'address': "Charity Lane, Old Town Crossing",
                        'transit': "Bus: Old Town Junction Stop (150m) | Metro: Rajiv Chowk (3.1 km)"
                    },
                    {
                        'name': "Apollo Multi-Specialty Private Hospital",
                        'category': "Private Medical Hospital",
                        'cat_id': "private",
                        'badge_class': "badge-info",
                        'distance': 2.4,
                        'address': "VIP Mall Road, Phase 1",
                        'transit': "Metro: VIP Road Metro (300m) | Bus: Apollo Hospital Stop (50m)"
                    },
                    {
                        'name': "Metro LifeCare Private Nursing Home & Clinic",
                        'category': "Private Medical Hospital",
                        'cat_id': "private",
                        'badge_class': "badge-info",
                        'distance': 6.0,
                        'address': "New Link Road, Block B",
                        'transit': "Bus: Block B Crossing Stop (100m)"
                    }
                ]
            else:
                # Mock Pharmacy Fallback
                mock_data = [
                    {
                        'name': "Pradhan Mantri Bhartiya Janaushadhi Kendra (Govt Subsidized)",
                        'category': "Jan Aushadhi Kendra (Govt)",
                        'cat_id': "aushadhi",
                        'badge_class': "badge-success",
                        'distance': 0.8,
                        'address': "Civil Lines Market, Shop No. 12",
                        'transit': "Metro: Civil Lines Metro (700m) | Bus: Civil Lines Stand (180m)"
                    },
                    {
                        'name': "Apollo Pharmacy (24/7 National Chain)",
                        'category': "Chain Pharmacy / Store",
                        'cat_id': "chain",
                        'badge_class': "badge-info",
                        'distance': 1.2,
                        'address': "Main High Street Road, Phase 2",
                        'transit': "Metro: Phase 2 Metro Station (250m) | Bus: Main Road Stop (80m)"
                    },
                    {
                        'name': "MedPlus Medicals & Chemists",
                        'category': "Chain Pharmacy / Store",
                        'cat_id': "chain",
                        'badge_class': "badge-info",
                        'distance': 2.1,
                        'address': "City Center Mall Arcade, Ground Floor",
                        'transit': "Bus: City Center Mall Gate (50m)"
                    },
                    {
                        'name': "Sharma Medical Store & Local Chemists",
                        'category': "Local Chemist / Pharmacy",
                        'cat_id': "local",
                        'badge_class': "badge-warning",
                        'distance': 0.5,
                        'address': "Local Block Market, Ward 4",
                        'transit': "Bus: Ward 4 Local Market Stand (120m)"
                    }
                ]
            hospitals_list = mock_data
            
        # Sort by distance
        hospitals_list.sort(key=lambda x: x['distance'])
        return jsonify({'status': 'success', 'data': hospitals_list})
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=True)