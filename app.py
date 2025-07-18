import os
import sys
import logging
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session, g
from flask_sqlalchemy import SQLAlchemy
import requests
from datetime import datetime
from dotenv import load_dotenv
#-authentification-
import secrets
from werkzeug.utils import secure_filename
from authlib.integrations.flask_client import OAuth

import json
from functools import wraps
import logging
logger = logging.getLogger(__name__)
from bson import ObjectId
import traceback
#-configurations-
from data.mongodb_candidats.mongo_utils import MongoManager
from config.external_services import fetch_job_offers
from configs import Config
# -gestion des mails-
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

load_dotenv()

logger = logging.getLogger(__name__)
load_dotenv()

class MongoJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, ObjectId):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(16))
app.config.update(
    SESSION_COOKIE_SAMESITE='Strict',
    SESSION_COOKIE_SECURE=True
)

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(30), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=True)
    picture_url = db.Column(db.String(255), nullable=True)
    candidate_mongo_id = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<User {self.email}>'

oauth = OAuth(app)
oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if g.user is None:
            flash("Veuillez vous connecter pour accéder à cette page.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    g.user = User.query.get(user_id) if user_id else None

@app.context_processor
def inject_user():
    return dict(user=g.user)

@app.route('/login')
def login():
    redirect_uri = url_for('authorized', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@app.route('/logout')
def logout():
    session.clear()
    flash("Vous avez été déconnecté.", "success")
    return redirect(url_for('landing'))

@app.route('/login/authorized')
def authorized():
    token = oauth.google.authorize_access_token()
    if not token:
        flash("Accès refusé par Google.", "danger")
        return redirect(url_for('landing'))

    user_info = token.get('userinfo')
    if not user_info:
        user_info = oauth.google.get('https://www.googleapis.com/oauth2/v1/userinfo').json()

    google_id = user_info['sub']
    user = User.query.filter_by(google_id=google_id).first()

    if user is None:
        user = User(
            google_id=google_id,
            email=user_info['email'],
            name=user_info['name'],
            picture_url=user_info.get('picture')
        )
        db.session.add(user)
        flash(f"Bienvenue, {user.name} ! Votre compte a été créé.", "success")
    else:
        user.name = user_info['name']
        user.picture_url = user_info.get('picture')
        flash(f"Heureux de vous revoir, {user.name} !", "info")
    
    db.session.commit()
    session['user_id'] = user.id
    return redirect(url_for('home'))

@app.route('/')
def landing():
    return redirect(url_for('home')) if g.user else render_template('landing.html')

@app.route('/home')
@login_required
def home():
    return render_template('home.html')

@app.route('/resume')
@login_required
def resume():
    if not g.user.candidate_mongo_id:
        return render_template('resume.html', cv_data=None)
    try:
        mongo_manager = MongoManager()
        cv_data_full = mongo_manager.get_profile_by_id(g.user.candidate_mongo_id)
        mongo_manager.close_connection()
        cv_profile = cv_data_full.get('candidat') if cv_data_full else None
        if not cv_profile:
            flash("Aucun CV n'a été trouvé pour votre profil.", "warning")
        return render_template('resume.html', cv_data=cv_profile)
    except Exception as e:
        logging.error(f"Erreur dans /resume: {str(e)}")
        flash("Erreur lors de la récupération du CV.", "danger")
        return render_template('resume.html', cv_data=None)

@app.route('/upload-resume', methods=['POST'])
@login_required
def upload_resume():
    MODEL_API_URL = Config.MODEL_API_URL
    if 'resume' not in request.files:
        return jsonify({'error': 'Aucun fichier envoyé'}), 400
    file = request.files['resume']
    if file.filename == '' or not allowed_file(file.filename):
        return jsonify({'error': 'Fichier invalide ou non sélectionné'}), 400
    file_content = file.read()
    file_filename = secure_filename(file.filename)
    try:
        logging.info(f"Envoi du CV '{file_filename}' à l'API de parsing.")
        files_for_api = {'file': (file_filename, file_content, 'application/pdf')}
        api_response = requests.post(f"{MODEL_API_URL}/parse-cv/", files=files_for_api)
        api_response.raise_for_status()
        parsed_cv_data = api_response.json()
        if not parsed_cv_data:
            flash("L'API n'a pas pu extraire les données du CV.", 'danger')
            return jsonify({'error': "Le traitement du CV par l'API a échoué."}), 500
        logging.info("Données reçues de l'API. Sauvegarde dans MongoDB.")
        mongo_manager = MongoManager()
        document_to_save = (parsed_cv_data)
        candidate_mongo_id = mongo_manager.save_profile(document_to_save)
        mongo_manager.close_connection()
        g.user.candidate_mongo_id = str(candidate_mongo_id)
        db.session.commit()
        flash('CV téléchargé et analysé avec succès !', 'success')
        return jsonify({'success': True, 'message': 'CV traité et lié au profil'})
    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur de communication avec l'API de parsing: {e}")
        flash('Le service d\'analyse de CV est actuellement indisponible.', 'danger')
        return jsonify({'error': 'Erreur de communication avec le service d\'analyse.'}), 503
    except Exception as e:
        logging.error(f"Erreur critique lors du traitement du CV : {e}", exc_info=True)
        flash('Une erreur serveur est survenue.', 'danger')
        return jsonify({'error': f'Une erreur serveur est survenue : {e}'}), 500
    
@app.route('/delete_resume', methods=['POST'])
@login_required
def delete_resume():
    if not g.user.candidate_mongo_id:
        return jsonify({'error': 'Aucun CV à supprimer.'}), 404
    try:
        mongo_manager = MongoManager()
        mongo_manager.delete_profile_by_id(g.user.candidate_mongo_id)
        mongo_manager.close_connection()
        g.user.candidate_mongo_id = None
        db.session.commit()
        flash('Votre CV a été supprimé avec succès.', 'success')
        return jsonify({'success': True, 'message': 'CV supprimé.'}), 200
    except Exception as e:
        logging.error(f"Erreur lors de la suppression du CV : {e}")
        flash('Une erreur est survenue lors de la suppression.', 'danger')
        return jsonify({'error': 'Erreur interne du serveur.'}), 500

@app.route('/jobs')
@login_required
def jobs():
    try:
        jobs_data = fetch_job_offers()
        return render_template('jobs.html', jobs=jobs_data or [], config=Config)
    except Exception as e:
        logging.error(f"Erreur lors de la récupération des offres d'emploi : {str(e)}")
        flash("Une erreur est survenue lors de la récupération des offres d'emploi.", "danger")
        return render_template('jobs.html', jobs=[], config=Config)

@app.route('/interview-ai', methods=['GET', 'POST'])
@login_required
def interview_ai():
    """
    Gère la simulation d'entretien.
    - GET: Affiche la page de chat pour une offre d'emploi donnée.
    - POST: Traite un message de l'utilisateur, interroge l'API du modèle,
            sauvegarde l'historique et renvoie la réponse de l'IA au client.
    """
    MODEL_API_URL = Config.MODEL_API_URL
    if request.method == 'POST':
        mongo_manager = None  
        try:
            data = request.get_json()
            messages_from_client = data.get('messages', [])
            job_id = data.get('job_id')

            if not job_id:
                return jsonify({'error': 'Donnée manquante : job_id'}), 400
            
            if not g.user.candidate_mongo_id:
                 return jsonify({'response': 'Je ne peux pas commencer car aucun CV n\'a été trouvé.', 'status': 'finished'}), 400

            mongo_manager = MongoManager()
            
            cv_document = mongo_manager.get_profile_by_id(g.user.candidate_mongo_id)
            if not cv_document:
                return jsonify({'response': 'Je ne peux pas commencer car votre profil CV est introuvable.', 'status': 'finished'}), 404

            jobs = fetch_job_offers()
            job_offer = next((job for job in jobs if job.get('id') == job_id), None)
            if not job_offer:
                return jsonify({'error': 'Offre d\'emploi introuvable.', 'status': 'finished'}), 404
            
            job_offer_formatted = {
                "entreprise": job_offer.get("entreprise", "N/A"),
                "poste": job_offer.get("poste", "N/A"),
                "description": job_offer.get("description_poste", "N/A"),
                "mission": job_offer.get("mission", "N/A"),
                "profil_recherche": job_offer.get("profil_recherche", "N/A"),
                "competences": job_offer.get("competences", "N/A")
            }

            payload = {
                "user_id": g.user.google_id,
                "job_offer_id": job_id,
                "cv_document": cv_document,
                "job_offer": job_offer_formatted,
                "messages": messages_from_client
            }

            encoded_payload = json.dumps(payload, cls=MongoJSONEncoder)
            headers = {'Content-Type': 'application/json'}
            
            logging.info(f"Sending payload to model API for user {g.user.google_id} and job {job_id}")
            api_response = requests.post(
                f"{MODEL_API_URL}/simulate-interview/", 
                data=encoded_payload,
                headers=headers,
                timeout=120 
            )
            api_response.raise_for_status()
            response_data = api_response.json()
            if response_data.get("response"):
                ai_message = {"role": "assistant", "content": response_data.get("response")}
                updated_history = messages_from_client + [ai_message]
                mongo_manager.save_conversation_history(g.user.google_id, job_id, updated_history)
            
            return jsonify(response_data)

        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur de communication avec l'API du modèle: {e}")
            return jsonify({'response': "Désolé, une erreur de communication avec l'assistant IA est survenue.", 'status': 'finished'}), 503
        except Exception as e:
            error_details = traceback.format_exc()
            logging.error(f"Erreur critique inattendue dans POST /interview-ai: {error_details}")
            return jsonify({'response': "Désolé, une erreur interne est survenue.", 'status': 'finished'}), 500
        finally:
            if mongo_manager:
                mongo_manager.close_connection()
    try:
        job_id = request.args.get('job_id')
        if not job_id:
            flash("Aucune offre d'emploi sélectionnée.", "warning")
            return redirect(url_for('jobs'))
        
        jobs = fetch_job_offers()
        job_offer = next((job for job in jobs if job.get('id') == job_id), None)
        if not job_offer:
            flash("L'offre d'emploi sélectionnée est introuvable.", "danger")
            return redirect(url_for('jobs'))
        mongo_manager = MongoManager()
        mongo_manager.delete_conversation_history(g.user.google_id, job_id)
        mongo_manager.close_connection()
        
        return render_template('interview_ai.html', job_offer=job_offer, config=Config)
    except Exception as e:
        error_details = traceback.format_exc()
        logging.error(f"Erreur critique dans GET /interview-ai: {error_details}")
        flash("Une erreur interne est survenue lors du chargement de la page d'entretien.", "danger")
        return redirect(url_for('home'))

@app.route('/feedbacks')
@login_required
def feedbacks():
    try:
        mongo_manager = MongoManager()
        # Récupérer tous les feedbacks pour l'utilisateur
        all_feedbacks = mongo_manager.get_all_feedbacks(g.user.google_id)
        jobs_data = fetch_job_offers()
        for feedback in all_feedbacks:
            # Formater la date
            if 'updated_at' in feedback:
                if isinstance(feedback['updated_at'], str):
                    try:
                        feedback['formatted_timestamp'] = datetime.fromisoformat(feedback['updated_at'].replace('Z', '+00:00')).strftime('%d/%m/%Y %H:%M')
                    except ValueError:
                        feedback['formatted_timestamp'] = feedback['updated_at']
                else:
                    feedback['formatted_timestamp'] = feedback['updated_at'].strftime('%d/%m/%Y %H:%M')
            else:
                feedback['formatted_timestamp'] = 'Date inconnue'
            job_offer_id = feedback.get('job_offer_id')
            if job_offer_id and jobs_data:
                matching_job = next((job for job in jobs_data if job.get('id') == job_offer_id), None)
                if matching_job:
                    feedback['job_title'] = matching_job.get('poste', 'Poste inconnu')
                else:
                    feedback['job_title'] = f"Poste #{job_offer_id[:8]}..."
            else:
                feedback['job_title'] = 'Poste inconnu'
        all_feedbacks.sort(key=lambda x: x.get('updated_at', ''), reverse=True)
        mongo_manager.close_connection()
        return render_template('feedbacks.html', feedbacks=all_feedbacks)
    except Exception as e:
        logging.error(f"Erreur lors de la récupération des feedbacks: {e}")
        flash("Une erreur est survenue lors de la récupération de vos feedbacks.", "danger")
        return render_template('feedbacks.html', feedbacks=[])

@app.route('/feedbacks/<feedback_id>')
@login_required  
def get_feedback_details(feedback_id):
    try:
        mongo_manager = MongoManager()
        db = mongo_manager.db
        feedback = None
        all_collections = db.list_collection_names()
        for collection_name in all_collections:
            try:
                collection = db[collection_name]
                found_feedback = collection.find_one({"_id": ObjectId(feedback_id)})
                if found_feedback:
                    # Vérifier que ce feedback appartient à l'utilisateur connecté
                    user_identifiers = [g.user.google_id, str(g.user.id), g.user.email]
                    possible_user_fields = ['user_id', 'user_google_id', 'google_id', 'user', 'email']
                    user_owns_feedback = False
                    for field in possible_user_fields:
                        if field in found_feedback:
                            if str(found_feedback[field]) in [str(uid) for uid in user_identifiers]:
                                user_owns_feedback = True
                                break
                    if user_owns_feedback:
                        feedback = found_feedback
                        feedback['_id'] = str(feedback['_id'])
                        break
            except Exception as e:
                continue
        if not feedback:
            flash("Feedback introuvable.", "danger")
            return redirect(url_for('feedbacks'))
        if 'updated_at' in feedback:
            # Gérer le format MongoDB avec $date
            if isinstance(feedback['updated_at'], dict) and '$date' in feedback['updated_at']:
                if '$numberLong' in feedback['updated_at']['$date']:
                    # Timestamp en millisecondes
                    timestamp_ms = int(feedback['updated_at']['$date']['$numberLong'])
                    timestamp_s = timestamp_ms / 1000
                    feedback['formatted_timestamp'] = datetime.fromtimestamp(timestamp_s).strftime('%d/%m/%Y à %H:%M')
                else:
                    feedback['formatted_timestamp'] = feedback['updated_at']['$date']
            elif isinstance(feedback['updated_at'], str):
                try:
                    feedback['formatted_timestamp'] = datetime.fromisoformat(feedback['updated_at'].replace('Z', '+00:00')).strftime('%d/%m/%Y à %H:%M')
                except ValueError:
                    feedback['formatted_timestamp'] = feedback['updated_at']
            else:
                feedback['formatted_timestamp'] = feedback['updated_at'].strftime('%d/%m/%Y à %H:%M')
        else:
            feedback['formatted_timestamp'] = 'Date inconnue'
        job_offer_id = feedback.get('job_offer_id')
        if job_offer_id:
            jobs_data = fetch_job_offers()
            matching_job = next((job for job in jobs_data if job.get('id') == job_offer_id), None)
            if matching_job:
                feedback['job_title'] = matching_job.get('poste', 'Poste inconnu')
            else:
                feedback['job_title'] = f"Poste #{job_offer_id[:8]}..."
        else:
            feedback['job_title'] = 'Poste inconnu'
        if 'feedback_data' in feedback and isinstance(feedback['feedback_data'], dict):
            if 'analysis_report' in feedback['feedback_data']:
                # Déplacer analysis_report au niveau principal pour le template
                feedback['analysis_report'] = feedback['feedback_data']['analysis_report']
        mongo_manager.close_connection()
        return render_template('feedback_details.html', feedback=feedback)
    except Exception as e:
        logging.error(f"Erreur lors de la récupération du feedback: {e}")
        import traceback
        traceback.print_exc()
        flash("Une erreur est survenue.", "danger")
        return redirect(url_for('feedbacks'))

@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        from_email = request.form.get('email')
        subject = request.form.get('subject')
        message_body = request.form.get('message')
        sender_email = Config.GMAIL_USER
        password = Config.GMAIL_PASSWORD
        receiver_email = sender_email 
        msg = MIMEMultipart()
        msg['From'] = f"application aiRH <{sender_email}>"
        msg['To'] = receiver_email
        msg['Subject'] = f"{subject}"
        html_body = f"""
        <html>
          <body>
            <h3><strong>Nouveau message depuis votre site AIrh</strong></h3>
            <p><strong>De :</strong> {name}</p>
            <p><strong>Contact :</strong> {from_email}</p>
            <p><strong>Sujet :</strong> {subject}</p>
            <p><strong>Message :</strong></p>
            <p>{message_body.replace(chr(10), '<br>')}</p>
          </body>
        </html>
        """
        msg.attach(MIMEText(html_body, 'html'))
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(sender_email, password)
            server.send_message(msg)
        flash("Merci pour votre message ! Il a bien été envoyé.", "success")
    return render_template('contact.html')

@app.route('/save-analysis', methods=['POST'])
@login_required
def save_analysis():
    data = request.get_json()
    job_offer_id = data.get('job_offer_id')
    if not job_offer_id:
        return jsonify({'error': 'Donnée manquante : job_offer_id'}), 400
    try:
        jobs = fetch_job_offers()
        job_title = "Offre inconnue"
        found_job = next((job for job in jobs if job.get('id') == job_offer_id), None)
        if found_job:
            job_title = found_job.get('poste', job_title)
        mongo_manager = MongoManager()
        feedback_id = mongo_manager.save_interview_feedback({
            "user_google_id": g.user.google_id,
            "job_offer_id": job_offer_id,
            "job_title": job_title,
            "feedback_data": None,
            "timestamp": datetime.utcnow().isoformat(),
            "status": "processing",
            "type": "interview"
        })
        mongo_manager.close_connection()
        return jsonify({'success': True, 'feedback_id': str(feedback_id)}), 200
    except Exception as e:
        logging.error(f"Erreur lors de la sauvegarde des métadonnées: {e}")
        return jsonify({'error': 'Erreur serveur'}), 500

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all() 
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
