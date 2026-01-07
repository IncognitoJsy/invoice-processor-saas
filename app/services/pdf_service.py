"""PDF processing utilities"""
import logging
from PyPDF2 import PdfReader

logger = logging.getLogger(__name__)

class PDFService:
    """Handle PDF extraction"""
    
    @staticmethod
    def extract_text(pdf_path: str) -> str:
        """Extract text from PDF"""
        try:
            reader = PdfReader(pdf_path)
            text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            return text
        except Exception as e:
            logger.error(f"Error extracting text: {str(e)}")
            return ""
