import pdfplumber

pdf_path = "temp_uploads/20241121_175353_Consolidated_Invoice.pdf"

with pdfplumber.open(pdf_path) as pdf:
    first_page = pdf.pages[0]
    text = first_page.extract_text()
    
    print("=== FIRST 500 CHARS ===")
    print(text[:500])
    print("\n=== CHECKING SUPPLIER ===")
    
    text_lower = text.lower()
    if 'yesss' in text_lower:
        print("✅ Contains 'yesss'")
    if 'wholesale' in text_lower:
        print("✅ Contains 'wholesale'")
    if 'cef' in text_lower:
        print("✅ Contains 'cef'")
