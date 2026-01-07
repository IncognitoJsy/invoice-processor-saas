#!/usr/bin/env python3
"""
Migration script to transfer data from PythonAnywhere to new system
Run this locally to download and migrate your existing setup
"""

import os
import sys
import json
import shutil
import sqlite3
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class PythonAnywhereMigration:
    """Migrate data from PythonAnywhere setup"""
    
    def __init__(self):
        self.base_dir = Path(__file__).parent.parent
        self.backup_dir = self.base_dir / 'migration_backup'
        self.backup_dir.mkdir(exist_ok=True)
        
        print("🔄 PythonAnywhere Migration Tool")
        print("=" * 60)
    
    def backup_current_state(self):
        """Backup current local state before migration"""
        print("\n📦 Step 1: Backing up current local state...")
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = self.backup_dir / f'backup_{timestamp}'
        backup_path.mkdir(exist_ok=True)
        
        # Backup current database if exists
        if (self.base_dir / 'app.db').exists():
            shutil.copy(self.base_dir / 'app.db', backup_path / 'app.db')
            print("  ✓ Backed up local database")
        
        # Backup .env
        if (self.base_dir / '.env').exists():
            shutil.copy(self.base_dir / '.env', backup_path / '.env')
            print("  ✓ Backed up .env file")
        
        print(f"  ✓ Backup saved to: {backup_path}")
        return backup_path
    
    def show_pythonanywhere_instructions(self):
        """Show instructions for downloading files from PythonAnywhere"""
        print("\n📥 Step 2: Download Files from PythonAnywhere")
        print("-" * 60)
        print("""
You need to download these files from PythonAnywhere:

1. Go to: https://www.pythonanywhere.com/user/incognitojsy/files/

2. Navigate to: /home/incognitojsy/quickbooks-updater/

3. Download these files:
   
   📄 Main Application:
   ✓ quickbooks_product_updater.py (your main Flask app)
   ✓ integration_handler.py (Gmail processor)
   ✓ .env (environment variables - we already have most of this)
   
   🗄️ Database:
   ✓ data/quickbooks_cache.db (QuickBooks product cache)
   
   🔑 Credentials (if not already copied):
   ✓ integration_data/queue/credentials.json (Gmail OAuth)
   ✓ integration_data/queue/token.pickle (Gmail token)

4. Save them to this directory:
   {self.backup_dir}/pythonanywhere_files/

Press Enter when you've downloaded the files, or 'skip' to continue without them...
""")
        
        response = input().strip().lower()
        
        pythonanywhere_dir = self.backup_dir / 'pythonanywhere_files'
        pythonanywhere_dir.mkdir(exist_ok=True)
        
        if response == 'skip':
            print("⚠️  Skipping PythonAnywhere file download")
            return False
        
        return True
    
    def extract_parsers(self):
        """Extract parser logic from old quickbooks_product_updater.py"""
        print("\n🔍 Step 3: Extracting Parser Logic...")
        print("-" * 60)
        
        source_file = self.backup_dir / 'pythonanywhere_files' / 'quickbooks_product_updater.py'
        
        if not source_file.exists():
            print("  ⚠️  quickbooks_product_updater.py not found")
            print(f"  Expected at: {source_file}")
            print("  You can manually copy parser logic later")
            return False
        
        print(f"  ✓ Found source file: {source_file.name}")
        
        # Read the source file
        with open(source_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract parser classes
        parsers_to_extract = {
            'YesssInvoiceParser': 'app/parsers/yesss_parser.py',
            'WholesaleInvoiceParser': 'app/parsers/wholesale_parser.py',
            'CEFInvoiceParser': 'app/parsers/cef_parser.py'
        }
        
        extracted = []
        for parser_name, target_file in parsers_to_extract.items():
            if f'class {parser_name}' in content:
                print(f"  ✓ Found {parser_name} in source")
                extracted.append(parser_name)
            else:
                print(f"  ⚠️  {parser_name} not found")
        
        if extracted:
            print(f"\n  📝 Parsers found: {', '.join(extracted)}")
            print(f"  💡 You'll need to manually copy these classes to:")
            for parser_name, target_file in parsers_to_extract.items():
                if parser_name in extracted:
                    print(f"     → {target_file}")
        
        return True
    
    def migrate_database(self):
        """Migrate QuickBooks cache database"""
        print("\n🗄️  Step 4: Migrating QuickBooks Cache...")
        print("-" * 60)
        
        source_db = self.backup_dir / 'pythonanywhere_files' / 'quickbooks_cache.db'
        
        if not source_db.exists():
            print("  ⚠️  quickbooks_cache.db not found")
            print("  You'll start with a fresh product cache")
            return False
        
        # Create data directory if it doesn't exist
        data_dir = self.base_dir / 'data'
        data_dir.mkdir(exist_ok=True)
        
        target_db = data_dir / 'quickbooks_cache.db'
        
        try:
            # Copy the database
            shutil.copy(source_db, target_db)
            print(f"  ✓ Copied database to: {target_db}")
            
            # Verify the database
            conn = sqlite3.connect(target_db)
            cursor = conn.cursor()
            
            # Check products table
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'")
            if cursor.fetchone():
                cursor.execute("SELECT COUNT(*) FROM products")
                count = cursor.fetchone()[0]
                print(f"  ✓ Found {count} products in cache")
            
            conn.close()
            return True
            
        except Exception as e:
            print(f"  ✗ Error migrating database: {str(e)}")
            return False
    
    def migrate_credentials(self):
        """Migrate Gmail credentials"""
        print("\n🔑 Step 5: Migrating Credentials...")
        print("-" * 60)
        
        # Check if credentials already exist
        local_creds = self.base_dir / 'integration_data' / 'queue' / 'credentials.json'
        local_token = self.base_dir / 'integration_data' / 'queue' / 'token.pickle'
        
        if local_creds.exists() and local_token.exists():
            print("  ✓ Gmail credentials already present")
            return True
        
        # Try to copy from downloaded files
        source_creds = self.backup_dir / 'pythonanywhere_files' / 'credentials.json'
        source_token = self.backup_dir / 'pythonanywhere_files' / 'token.pickle'
        
        copied = 0
        
        if source_creds.exists() and not local_creds.exists():
            shutil.copy(source_creds, local_creds)
            print("  ✓ Copied credentials.json")
            copied += 1
        
        if source_token.exists() and not local_token.exists():
            shutil.copy(source_token, local_token)
            print("  ✓ Copied token.pickle")
            copied += 1
        
        if copied == 0:
            print("  ⚠️  No credentials to copy")
        
        return copied > 0
    
    def update_env_file(self):
        """Update .env with any missing values"""
        print("\n⚙️  Step 6: Checking Environment Variables...")
        print("-" * 60)
        
        env_file = self.base_dir / '.env'
        source_env = self.backup_dir / 'pythonanywhere_files' / '.env'
        
        current_env = {}
        if env_file.exists():
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        current_env[key.strip()] = value.strip()
        
        print(f"  ✓ Current .env has {len(current_env)} variables")
        
        # Check for required variables
        required_vars = [
            'QUICKBOOKS_CLIENT_ID',
            'QUICKBOOKS_CLIENT_SECRET',
            'QUICKBOOKS_ENVIRONMENT',
            'SECRET_KEY',
        ]
        
        missing = [var for var in required_vars if not current_env.get(var)]
        
        if missing:
            print(f"  ⚠️  Missing variables: {', '.join(missing)}")
        else:
            print("  ✓ All required variables present")
        
        return True
    
    def create_migration_summary(self):
        """Create a summary report"""
        print("\n📊 Migration Summary")
        print("=" * 60)
        
        summary = {
            'timestamp': datetime.now().isoformat(),
            'files_migrated': [],
            'status': 'completed'
        }
        
        # Check what was migrated
        checks = {
            'QuickBooks Cache': self.base_dir / 'data' / 'quickbooks_cache.db',
            'Gmail Credentials': self.base_dir / 'integration_data' / 'queue' / 'credentials.json',
            'Gmail Token': self.base_dir / 'integration_data' / 'queue' / 'token.pickle',
            'Environment Config': self.base_dir / '.env',
            'Database': self.base_dir / 'app.db',
        }
        
        for name, path in checks.items():
            if path.exists():
                print(f"  ✓ {name}")
                summary['files_migrated'].append(name)
            else:
                print(f"  ⚠️  {name} - Not Found")
        
        # Save summary
        summary_file = self.backup_dir / 'migration_summary.json'
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        print(f"\n  📄 Summary saved to: {summary_file}")
        
        return summary
    
    def show_next_steps(self):
        """Show what to do next"""
        print("\n🎯 Next Steps")
        print("=" * 60)
        print("""
1. EXTRACT PARSER LOGIC (Manual Step):
   - Open: migration_backup/pythonanywhere_files/quickbooks_product_updater.py
   - Copy the parser classes to:
     • app/parsers/yesss_parser.py
     • app/parsers/wholesale_parser.py  
     • app/parsers/cef_parser.py
   - Keep the existing structure, just replace the parse() method logic

2. TEST LOCALLY:
   python test_basic.py
   python -m flask run

3. TEST WITH REAL INVOICE:
   - Place a test PDF in uploads/
   - Test the parsing and QuickBooks integration

4. DEPLOY TO RAILWAY:
   git add .
   git commit -m "Add migrated parsers and data"
   railway up

5. GRADUAL CUTOVER:
   - Test Railway deployment thoroughly
   - Update DNS when ready
   - Keep PythonAnywhere as backup for 1 week
        """)
    
    def run(self):
        """Run the complete migration"""
        try:
            # Step 1: Backup
            self.backup_current_state()
            
            # Step 2: Get files from PythonAnywhere
            if self.show_pythonanywhere_instructions():
                # Step 3: Extract parsers
                self.extract_parsers()
                
                # Step 4: Migrate database
                self.migrate_database()
                
                # Step 5: Migrate credentials
                self.migrate_credentials()
            
            # Step 6: Update environment
            self.update_env_file()
            
            # Step 7: Summary
            self.create_migration_summary()
            
            # Step 8: Next steps
            self.show_next_steps()
            
            print("\n✅ Migration preparation complete!")
            print("=" * 60)
            
        except KeyboardInterrupt:
            print("\n\n⚠️  Migration interrupted by user")
            sys.exit(1)
        except Exception as e:
            print(f"\n\n✗ Migration error: {str(e)}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

if __name__ == '__main__':
    migration = PythonAnywhereMigration()
    migration.run()
