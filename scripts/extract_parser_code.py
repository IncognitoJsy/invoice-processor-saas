#!/usr/bin/env python3
"""
Helper script to extract parser classes from old code
"""

import re
import sys
from pathlib import Path

def extract_class(source_code, class_name):
    """Extract a complete class from source code"""
    
    # Find the class definition
    pattern = rf'class {class_name}.*?(?=\nclass |\nif __name__|\Z)'
    match = re.search(pattern, source_code, re.DOTALL)
    
    if match:
        return match.group(0)
    return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python extract_parser_code.py <path_to_quickbooks_product_updater.py>")
        sys.exit(1)
    
    source_file = Path(sys.argv[1])
    
    if not source_file.exists():
        print(f"Error: File not found: {source_file}")
        sys.exit(1)
    
    print(f"📖 Reading: {source_file}")
    
    with open(source_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    parsers = {
        'YesssInvoiceParser': 'app/parsers/yesss_parser.py',
        'WholesaleInvoiceParser': 'app/parsers/wholesale_parser.py',
        'CEFInvoiceParser': 'app/parsers/cef_parser.py',
    }
    
    print("\n🔍 Extracting parser classes...\n")
    
    for class_name, target_file in parsers.items():
        code = extract_class(content, class_name)
        
        if code:
            print(f"✓ Found {class_name}")
            print(f"  → {len(code)} characters")
            print(f"  → Save to: {target_file}")
            
            # Save extracted code
            output_dir = Path('migration_backup/extracted_parsers')
            output_dir.mkdir(parents=True, exist_ok=True)
            
            output_file = output_dir / f"{class_name}.txt"
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(code)
            
            print(f"  ✓ Saved to: {output_file}\n")
        else:
            print(f"✗ {class_name} not found\n")
    
    print("✅ Extraction complete!")
    print(f"📁 Check migration_backup/extracted_parsers/")

if __name__ == '__main__':
    main()
