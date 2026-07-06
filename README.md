---
title: PredictMedix
emoji: 🏥
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# PREDICTMEDIX – Medical Cost Prediction & Explainable AI Portal
### Final Year B.Tech Major Project | Computer Science and Engineering

PredictMedix is a web-based healthcare intelligence portal designed to predict individual medical insurance charges and provide transparent explanation breakdowns of those predictions. The application is powered by Machine Learning (XGBoost) and Explainable AI (SHAP) frameworks, featuring a premium responsive user interface.

---

## 🌟 Key Features

* **Advanced Machine Learning Engine**: Predicts annual medical costs using an optimized XGBoost regression model trained on demographic and lifestyle datasets.
* **Explainable AI (SHAP Integration)**: Uses Shapley Additive Explanations to break down the exact mathematical impact (in INR) of each feature (e.g., smoking status, BMI, age) on the final predicted charges.
* **Premium Responsive Web Portal**: Built using Flask with a modern, glassmorphic layout, micro-animations, and a persistent dark/light theme toggle.
* **Secure Authentication System**: User registration, login, and token-based password resets using hashed credentials (`werkzeug.security`) and JWTs.
* **Dual Database Modes**: Seamlessly connects to a MongoDB server or automatically falls back to a zero-configuration local file-based database (`db_fallback.json`) if MongoDB is offline.
* **5-Year Cost Projections**: Provides future estimations calculating age and weight progression year-over-year.
* **Instant PDF Report Export**: Generates and downloads detailed print-friendly patient reports using `xhtml2pdf`.

---

## 🛠️ Technology Stack

* **Frontend**: HTML5, Vanilla CSS3 (custom variables, responsive grids, transitions), JavaScript (ES6+ for theme management and form validation).
* **Backend**: Python, Flask, Flask-Login (session management), Flask-Mail (recovery mail), PyJWT (token generation).
* **Machine Learning**: XGBoost Regressor, Scikit-Learn, Joblib, Pandas, NumPy.
* **Explainable AI**: SHAP (SHapley Additive exPlanations).
* **Database**: MongoDB (via PyMongo) with local JSON fallback.
* **Reporting**: xhtml2pdf (pisa).

---

## 📂 Project Structure

```text
Btech_Major_Project_PredictMedix-main/
│
├── static/
│   ├── css/
│   │   └── style.css            # Custom premium styles & theme variables
│   ├── js/
│   │   └── main.js             # Theme toggler, password toggler & validations
│   └── images/
│       └── hero_health.jpg      # High-quality generated landing page illustration
│
├── templates/
│   ├── base.html                # General shell boilerplate (Navbar, flash, footer)
│   ├── index.html               # Home portal (Hero section or Predictor Form)
│   ├── login.html               # Glassmorphic Login card
│   ├── signup.html              # Secure Registration card
│   ├── report.html              # Responsive Estimation report (Web & PDF layouts)
│   ├── pdf_base.html            # Simple layout container optimized for PDF rendering
│   ├── about.html               # Technical stack details and developer profiles
│   ├── contact.html             # Contact page with messaging inputs
│   └── forgot_password.html     # Password recovery templates
│
├── app.py                       # Main Flask server controller, routing & Mock DB
├── train_model.py               # Model training script using XGBoost
├── insurancemodelf_fullfeatures.pkl # Trained XGBoost regression weights
├── db_fallback.json             # Local file-based user database (fallback)
├── requirements.txt             # Python packages dependency list
└── README.md                    # Project documentation
```

---

## 🚀 How to Run the Project

### 1. Prerequisite Installations
Ensure Python 3.10+ is installed on your system. 

### 2. Install Dependencies
Install all required packages:
```bash
pip install -r requirements.txt
```

### 3. Setup Environment variables
Copy the `.env.example` file and rename it to `.env`. Configure your secret keys and database settings:
```ini
SECRET_KEY=your-custom-secret-key
MONGO_URI=mongodb://localhost:27017/insurance_auth
```
*(Note: If no MONGO_URI is set or MongoDB is unreachable, the application will automatically fall back to using `db_fallback.json` local storage).*

### 4. Run the Application
Start the local development server:
```bash
python app.py
```
Open your browser and navigate to **[http://127.0.0.1:5000](http://127.0.0.1:5000)**.

---

## 🎓 Academic Context
This project was completed as a final year B.Tech Computer Science and Engineering Major Project. 

**Student Contribution:**
* Implemented the Flask backend architecture, user authentication, and mock database fallback logic.
* Engineered the frontend layout, premium Vanilla CSS theme system, and responsive forms.
* Integrated the machine learning pipeline (XGBoost inference) and explainability module (SHAP).
* Configured dynamic PDF reporting exports.
