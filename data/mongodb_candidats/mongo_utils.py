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

    def close_connection(self):
        self.client.close()