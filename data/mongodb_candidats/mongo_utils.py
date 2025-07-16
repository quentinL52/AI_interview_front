import os
import json
from pymongo import MongoClient
from bson.objectid import ObjectId
import logging
from configs import Config
from datetime import datetime

class MongoManager:
    def __init__(self):
        self.client = MongoClient(Config.MONGO_URI)
        self.db = self.client[Config.MONGO_DB_NAME]
        self.candidate_collection = self.db[Config.MONGO_CV_COLLECTION]  
        self.historique_entretient = self.db[Config.MONGO_INTERVIEW_COLLECTION]
        
    # -- CRUD pour le profils des candidats --
    def save_profile(self, profile_data):
        if not isinstance(profile_data, dict):
            raise TypeError("Le profil doit être un dictionnaire")
        result = self.candidate_collection.insert_one(profile_data)
        return result.inserted_id

    def create_profile_from_json(self, json_file_path):
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not isinstance(data, dict):
                print(f"Erreur : Les données ne sont pas un dictionnaire valide")
                return None

            if 'candidat' in data:
                candidat_data = data['candidat']
                if not isinstance(candidat_data, dict):
                    print(f"Erreur : La clé 'candidat' ne contient pas un dictionnaire valide")
                    return None
                return self.save_profile(candidat_data)
            else:
                print(f"La clé 'candidat' est manquante dans le fichier {json_file_path}")
                return None
        except FileNotFoundError:
            print(f"Erreur : Le fichier JSON '{json_file_path}' n'a pas été trouvé.")
            return None
        except json.JSONDecodeError:
            print(f"Erreur : Le contenu de '{json_file_path}' n'est pas un JSON valide.")
            return None
        except Exception as e:
            print(f"Erreur inattendue lors de la création du profil : {str(e)}")
            return None
        
    def delete_profile_by_id(self, profile_id):     
        object_id_to_delete = ObjectId(profile_id)
        result = self.candidate_collection.delete_one({"_id": object_id_to_delete})            
        return result
            
    def fetch_document_by_id(self, document_id: str):
        if not ObjectId.is_valid(document_id):
            raise ValueError(f"ID MongoDB invalide : {document_id}")
        return self.candidate_collection.find_one({"_id": ObjectId(document_id)})   
         
    def get_profile_by_id(self, profile_id):
        try:
            logging.info(f"Récupération du profil avec l'ID: {profile_id}")
            result = self.candidate_collection.find_one({"_id": ObjectId(profile_id)})
            if result:
                logging.info("Données trouvées dans MongoDB:", result)
                if '_id' in result:
                    del result['_id']
                if not isinstance(result, dict):
                    logging.error(f"Erreur: Les données ne sont pas un dictionnaire. Type: {type(result)}")
                    return None                    
                return result
            else:
                logging.info(f"Aucun profil trouvé pour l'ID: {profile_id}")
                return None
        except Exception as e:
            logging.error(f"Erreur lors de la récupération du profil: {str(e)}")
            return None
        
    #-- fonctions CRUD pour l'historique des conversations --
    def save_conversation_history(self, google_id: str, job_id: str, messages: list):
        self.historique_entretient.update_one(
            {"google_id": google_id, "job_id": job_id},
            {
                "$set": {
                    "messages": messages,
                    "last_updated": datetime.utcnow()
                }
            },
            upsert=True
        )

    def load_conversation_history(self, google_id: str, job_id: str) -> list:
        history_doc = self.historique_entretient.find_one(
            {"google_id": google_id, "job_id": job_id}
        )
        return history_doc.get("messages", []) if history_doc else [] 

    def delete_conversation_history(self, google_id: str, job_id: str):
        """Supprime l'historique de conversation pour un utilisateur et une offre d'emploi."""
        logging.info(f"Réinitialisation de l'historique pour l'utilisateur {google_id} et l'offre {job_id}")
        self.historique_entretient.delete_one({"google_id": google_id, "job_id": job_id})   

    def save_general_feedback(self, feedback_data):
        try:
            general_feedback_collection = self.db['general_feedbacks']
            result = general_feedback_collection.insert_one(feedback_data)
            return result.inserted_id
        except Exception as e:
            logging.error(f"Erreur sauvegarde feedback général: {str(e)}")
            raise e
    
    def save_interview_feedback(self, feedback_data):
        try:
            interview_feedback_collection = self.db['interview_feedbacks']
            result = interview_feedback_collection.insert_one(feedback_data)
            return result.inserted_id
        except Exception as e:
            logging.error(f"Erreur sauvegarde feedback entretien: {str(e)}")
            raise e
    
    def get_all_feedbacks(self, google_id: str):
        try:
            general_collection = self.db['general_feedbacks']
            interview_collection = self.db['interview_feedbacks']
            
            general_feedbacks = list(general_collection.find({"user_google_id": google_id}))
            interview_feedbacks = list(interview_collection.find({"user_google_id": google_id}))
            
            for feedback in general_feedbacks:
                feedback['_id'] = str(feedback['_id'])
                feedback['type'] = 'general'
                feedback['job_title'] = 'Feedback général'
            
            for feedback in interview_feedbacks:
                feedback['_id'] = str(feedback['_id'])
                feedback['type'] = 'interview'
            
            return general_feedbacks + interview_feedbacks
        except Exception as e:
            logging.error(f"Erreur récupération feedbacks: {str(e)}")
            return []
    
    def get_feedback_by_id(self, feedback_id: str):
        try:
            general_collection = self.db['general_feedbacks']
            interview_collection = self.db['interview_feedbacks']
            
            feedback = general_collection.find_one({"_id": ObjectId(feedback_id)})
            if feedback:
                feedback['_id'] = str(feedback['_id'])
                feedback['type'] = 'general'
                feedback['job_title'] = 'Feedback général'
                return feedback
            
            feedback = interview_collection.find_one({"_id": ObjectId(feedback_id)})
            if feedback:
                feedback['_id'] = str(feedback['_id'])
                feedback['type'] = 'interview'
                return feedback
            
            return None
        except Exception as e:
            logging.error(f"Erreur récupération feedback par ID: {str(e)}")
            return None
    
    def get_interview_feedback_by_status(self, google_id: str, status: str):
        try:
            interview_collection = self.db['interview_feedbacks']
            feedback = interview_collection.find_one({
                "user_google_id": google_id, 
                "status": status
            })
            if feedback:
                feedback['_id'] = str(feedback['_id'])
            return feedback
        except Exception as e:
            logging.error(f"Erreur récupération feedback par status: {str(e)}")
            return None

    def get_all_feedbacks(self, google_id: str):
        try:
            interview_collection = self.db['interview_feedbacks']
            
            interview_feedbacks = list(interview_collection.find({"user_google_id": google_id}))
            
            for feedback in interview_feedbacks:
                feedback['_id'] = str(feedback['_id'])
                feedback['type'] = 'interview'
            
            return interview_feedbacks
        except Exception as e:
            logging.error(f"Erreur récupération feedbacks: {str(e)}")
            return []

    def get_feedback_by_id(self, feedback_id: str):
        try:
            interview_collection = self.db['interview_feedbacks']
            
            feedback = interview_collection.find_one({"_id": ObjectId(feedback_id)})
            if feedback:
                feedback['_id'] = str(feedback['_id'])
                feedback['type'] = 'interview'
                return feedback
            
            return None
        except Exception as e:
            logging.error(f"Erreur récupération feedback par ID: {str(e)}")
            return None
    
    def update_interview_feedback(self, feedback_id: str, feedback_data: dict, status: str):
        try:
            interview_collection = self.db['interview_feedbacks']
            interview_collection.update_one(
                {"_id": ObjectId(feedback_id)},
                {
                    "$set": {
                        "feedback_data": feedback_data,
                        "status": status,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
        except Exception as e:
            logging.error(f"Erreur mise à jour feedback: {str(e)}")
            raise e

    def close_connection(self):
        self.client.close()
