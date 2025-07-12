import logging
import requests
from data.mongodb_candidats.mongo_utils import MongoManager
from configs import Config

logging.basicConfig(level=logging.INFO)


def fetch_job_offers() -> list:
    try:
        response = requests.get(Config.JOB_API_URL, timeout=Config.API_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        logging.error(f"Timeout lors de la récupération des offres depuis {Config.JOB_API_URL}")
        return []
    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur de requête lors de la récupération des offres : {e}")
        return []
    except Exception as e:
        logging.error(f"Une erreur inattendue est survenue : {e}")
        return []


def run_full_interview_analysis(google_id: str, job_id: str):
    manager = MongoManager()
    try:
        logging.info("Lancement du service d'analyse d'entretien...")
        historique = manager.load_conversation_history(google_id, job_id)
        offres = fetch_job_offers()
        logging.info("Analyse terminée.")
    except Exception as e:
        logging.error(f"Le service d'analyse a échoué : {e}")
    finally:
        manager.close_connection()