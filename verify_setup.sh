#!/bin/bash

echo "🔍 Verifying Invoice Processor Setup..."
echo ""

# Color codes for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counters
PASS=0
FAIL=0

check_file() {
    if [ -f "$1" ]; then
        echo -e "${GREEN}✓${NC} $1"
        ((PASS++))
        return 0
    else
        echo -e "${RED}✗${NC} $1 - MISSING"
        ((FAIL++))
        return 1
    fi
}

check_dir() {
    if [ -d "$1" ]; then
        echo -e "${GREEN}✓${NC} $1/"
        ((PASS++))
        return 0
    else
        echo -e "${RED}✗${NC} $1/ - MISSING"
        ((FAIL++))
        return 1
    fi
}

echo "📁 Checking Root Files..."
check_file ".gitignore"
check_file ".env"
check_file ".env.example"
check_file "requirements.txt"
check_file "Dockerfile"
check_file "docker-compose.yml"
check_file "railway.toml"
check_file "Procfile"
check_file "README.md"
check_file "wsgi.py"
check_file "manage.py"
echo ""

echo "📂 Checking Directories..."
check_dir "app"
check_dir "app/models"
check_dir "app/services"
check_dir "app/parsers"
check_dir "app/utils"
check_dir "app/api"
check_dir "app/web"
check_dir "app/tasks"
check_dir "app/templates"
check_dir "app/static"
check_dir "tests"
check_dir "migrations"
check_dir "scripts"
check_dir "logs"
check_dir "uploads"
check_dir "integration_data"
echo ""

echo "🐍 Checking Core Python Files..."
check_file "app/__init__.py"
check_file "app/config.py"
check_file "app/extensions.py"
echo ""

echo "📊 Checking Models..."
check_file "app/models/__init__.py"
check_file "app/models/user.py"
check_file "app/models/invoice.py"
check_file "app/models/product.py"
echo ""

echo "🔧 Checking Services..."
check_file "app/services/__init__.py"
check_file "app/services/gmail_service.py"
check_file "app/services/quickbooks_service.py"
check_file "app/services/job_reference_extractor.py"
check_file "app/services/description_cleaner.py"
check_file "app/services/invoice_processor.py"
check_file "app/services/pdf_service.py"
echo ""

echo "📄 Checking Parsers..."
check_file "app/parsers/__init__.py"
check_file "app/parsers/base_parser.py"
check_file "app/parsers/yesss_parser.py"
check_file "app/parsers/wholesale_parser.py"
check_file "app/parsers/cef_parser.py"
echo ""

echo "🌐 Checking Web Routes..."
check_file "app/web/__init__.py"
check_file "app/web/dashboard.py"
check_file "app/web/invoices.py"
check_file "app/web/queue.py"
check_file "app/web/settings.py"
echo ""

echo "📝 Checking API Routes..."
check_file "app/api/__init__.py"
echo ""

echo "🔍 Checking File Contents..."

# Check if key files have content
if [ -s "app/__init__.py" ]; then
    echo -e "${GREEN}✓${NC} app/__init__.py has content"
    ((PASS++))
else
    echo -e "${RED}✗${NC} app/__init__.py is empty"
    ((FAIL++))
fi

if [ -s "requirements.txt" ]; then
    echo -e "${GREEN}✓${NC} requirements.txt has content"
    ((PASS++))
else
    echo -e "${RED}✗${NC} requirements.txt is empty"
    ((FAIL++))
fi

if [ -s ".env" ]; then
    echo -e "${GREEN}✓${NC} .env exists and has content"
    ((PASS++))
else
    echo -e "${YELLOW}⚠${NC} .env is empty (you need to add credentials)"
fi
echo ""

echo "🐳 Checking Docker Files..."
if grep -q "FROM python:3.11-slim" Dockerfile 2>/dev/null; then
    echo -e "${GREEN}✓${NC} Dockerfile is valid"
    ((PASS++))
else
    echo -e "${RED}✗${NC} Dockerfile is invalid or empty"
    ((FAIL++))
fi

if grep -q "version:" docker-compose.yml 2>/dev/null; then
    echo -e "${GREEN}✓${NC} docker-compose.yml is valid"
    ((PASS++))
else
    echo -e "${RED}✗${NC} docker-compose.yml is invalid or empty"
    ((FAIL++))
fi
echo ""

echo "📊 File Statistics..."
echo "Python files: $(find app -name "*.py" 2>/dev/null | wc -l | tr -d ' ')"
echo "Total files: $(find . -type f -not -path '*/\.*' -not -path '*/venv/*' 2>/dev/null | wc -l | tr -d ' ')"
echo "Directories: $(find app -type d 2>/dev/null | wc -l | tr -d ' ')"
echo ""

echo "🔒 Checking Git Status..."
if [ -d ".git" ]; then
    echo -e "${GREEN}✓${NC} Git repository initialized"
    ((PASS++))
    
    # Check if there are uncommitted changes
    if [ -n "$(git status --porcelain)" ]; then
        echo -e "${YELLOW}⚠${NC} You have uncommitted changes"
        echo "   Run: git add . && git commit -m 'Your message'"
    else
        echo -e "${GREEN}✓${NC} All changes committed"
        ((PASS++))
    fi
else
    echo -e "${RED}✗${NC} Git repository not initialized"
    ((FAIL++))
fi
echo ""

echo "🎯 Environment Check..."
if command -v python3 &> /dev/null; then
    echo -e "${GREEN}✓${NC} Python3 installed: $(python3 --version)"
    ((PASS++))
else
    echo -e "${RED}✗${NC} Python3 not found"
    ((FAIL++))
fi

if command -v docker &> /dev/null; then
    echo -e "${GREEN}✓${NC} Docker installed: $(docker --version)"
    ((PASS++))
else
    echo -e "${YELLOW}⚠${NC} Docker not found (optional but recommended)"
fi

if command -v git &> /dev/null; then
    echo -e "${GREEN}✓${NC} Git installed: $(git --version)"
    ((PASS++))
else
    echo -e "${RED}✗${NC} Git not found"
    ((FAIL++))
fi
echo ""

echo "═══════════════════════════════════════════"
echo "📊 VERIFICATION SUMMARY"
echo "═══════════════════════════════════════════"
echo -e "Passed: ${GREEN}${PASS}${NC}"
echo -e "Failed: ${RED}${FAIL}${NC}"
echo ""

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}🎉 ALL CHECKS PASSED!${NC}"
    echo ""
    echo "✅ Your project structure is complete!"
    echo ""
    echo "📋 Next steps:"
    echo "1. Edit .env with your actual credentials"
    echo "2. Create virtual environment: python3 -m venv venv"
    echo "3. Activate it: source venv/bin/activate"
    echo "4. Install dependencies: pip install -r requirements.txt"
    echo "5. Initialize database: flask db init"
    echo "6. Run: flask run"
    echo ""
    echo "Or use Docker:"
    echo "  docker-compose up"
    echo ""
else
    echo -e "${RED}⚠️  SOME CHECKS FAILED${NC}"
    echo ""
    echo "Please review the errors above and fix missing files."
    echo ""
fi

echo "💡 Tips:"
echo "- Run 'ls -la app/' to see app structure"
echo "- Run 'cat app/__init__.py' to verify file contents"
echo "- Run 'git status' to check uncommitted changes"
echo ""
