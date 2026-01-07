"""Clean and simplify product descriptions using AI"""
import re
import logging
from typing import Optional
from openai import OpenAI
import os

logger = logging.getLogger(__name__)

class DescriptionCleaner:
    """Clean product descriptions using AI"""
    
    def __init__(self, openai_api_key: str = None):
        self.openai_client = None
        api_key = openai_api_key or os.environ.get('OPENAI_API_KEY')
        
        if api_key:
            try:
                self.openai_client = OpenAI(api_key=api_key)
                logger.info("OpenAI initialized")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI: {str(e)}")
        
        self.cache = {}
    
    def clean(self, raw_description: str, part_number: str = None) -> str:
        """Clean description"""
        cache_key = f"{raw_description}_{part_number}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        if self.openai_client:
            cleaned = self._clean_with_ai(raw_description, part_number)
            if cleaned:
                self.cache[cache_key] = cleaned
                return cleaned
        
        cleaned = self._clean_with_rules(raw_description)
        self.cache[cache_key] = cleaned
        return cleaned
    
    def _clean_with_ai(self, raw: str, part: str = None) -> Optional[str]:
        """Use AI to clean"""
        try:
            prompt = f"Clean this electrical product description for a customer invoice. Remove codes, prices, technical jargon. Keep only: size, type, color, length.\n\nRaw: {raw}\n\nCleaned:"
            
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=100
            )
            
            cleaned = response.choices[0].message.content.strip()
            if cleaned and 5 < len(cleaned) < 200:
                return cleaned
        except Exception as e:
            logger.error(f"AI cleaning failed: {str(e)}")
        return None
    
    def _clean_with_rules(self, desc: str) -> str:
        """Rule-based cleaning"""
        desc = re.sub(r'\d+\.\d+R\b', '', desc)
        desc = re.sub(r'\b\d{6,}\b', '', desc)
        desc = ' '.join(desc.split())
        return desc.title()
