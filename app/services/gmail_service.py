"""Gmail integration service"""
import os
import pickle
import logging
from typing import List, Dict, Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

class GmailService:
    """Gmail API integration"""
    
    def __init__(self, credentials_path: str = 'credentials.json', token_path: str = 'token.pickle'):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = None
    
    def authenticate(self) -> bool:
        """Authenticate with Gmail API"""
        creds = None
        
        if os.path.exists(self.token_path):
            with open(self.token_path, 'rb') as token:
                creds = pickle.load(token)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_path):
                    logger.error(f"Credentials file not found: {self.credentials_path}")
                    return False
                
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            
            with open(self.token_path, 'wb') as token:
                pickle.dump(creds, token)
        
        try:
            self.service = build('gmail', 'v1', credentials=creds)
            logger.info("Gmail authentication successful")
            return True
        except Exception as e:
            logger.error(f"Gmail authentication failed: {str(e)}")
            return False
    
    def search_messages(self, query: str, max_results: int = 10) -> List[Dict]:
        """Search for messages matching query"""
        if not self.service:
            if not self.authenticate():
                return []
        
        try:
            results = self.service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()
            
            messages = results.get('messages', [])
            logger.info(f"Found {len(messages)} messages matching query: {query}")
            return messages
            
        except Exception as e:
            logger.error(f"Error searching messages: {str(e)}")
            return []
    
    def get_message(self, message_id: str) -> Optional[Dict]:
        """Get full message details"""
        if not self.service:
            if not self.authenticate():
                return None
        
        try:
            message = self.service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            return message
        except Exception as e:
            logger.error(f"Error getting message {message_id}: {str(e)}")
            return None
