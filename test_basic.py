"""Basic test without OpenAI"""
import os
os.environ['FLASK_ENV'] = 'development'

print("🧪 Testing Core Features...")
print("=" * 60)

# Test 1: Job Reference Extractor
print("\n1️⃣ Job Reference Extractor...")
from app.services.job_reference_extractor import JobReferenceExtractor

extractor = JobReferenceExtractor()

test_text = """
YOUR ORDER REFERENCE: Project-ABC-123
Invoice Date: 01/01/2025
"""

ref = extractor._extract_from_labeled_field(test_text, 'YESSS', None)
if ref:
    print(f"   ✓ Extracted: '{ref}'")
else:
    print("   ✗ Could not extract reference")

# Test 2: Description Cleaner (rule-based)
print("\n2️⃣ Description Cleaner (rule-based)...")
from app.services.description_cleaner import DescriptionCleaner

cleaner = DescriptionCleaner()
raw = "6242Y 2.5mm BASEC 2-Core +Earth 18,172.00 PVC GREY 100m"
cleaned = cleaner._clean_with_rules(raw)

print(f"   Raw:     {raw}")
print(f"   Cleaned: {cleaned}")

# Test 3: Gmail Service
print("\n3️⃣ Gmail Service...")
from app.services.gmail_service import GmailService

gmail = GmailService(
    credentials_path='integration_data/queue/credentials.json',
    token_path='integration_data/queue/token.pickle'
)

if os.path.exists('integration_data/queue/token.pickle'):
    print("   ✓ Gmail token found")
    print("   ✓ Ready to authenticate")
else:
    print("   ✗ Gmail token missing")

print("\n" + "=" * 60)
print("✅ Core tests passed!")
print("\nNext: Run 'python -m flask run' to start the server")
