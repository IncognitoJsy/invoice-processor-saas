#!/bin/bash

set -e  # Exit on error

echo "🚀 Setting up Invoice Processor SaaS..."
echo ""

# ============================================
# STEP 1: Create Directory Structure
# ============================================
echo "📁 Creating directory structure..."
mkdir -p app/{models,services,parsers,utils,api,web,tasks,templates,static/{css,js,img}}
mkdir -p app/templates/{base,dashboard,invoices,queue,settings,components}
mkdir -p migrations tests/{unit,integration} scripts logs uploads temp_uploads integration_data/queue docs

# Create __init__.py files
touch app/__init__.py
touch app/models/__init__.py
touch app/services/__init__.py
touch app/parsers/__init__.py
touch app/utils/__init__.py
touch app/api/__init__.py
touch app/web/__init__.py
touch app/tasks/__init__.py
touch tests/__init__.py
touch tests/unit/__init__.py
touch tests/integration/__init__.py

echo "✅ Directory structure created"
echo ""

# ============================================
# STEP 2: Create .gitignore
# ============================================
echo "📝 Creating .gitignore..."
cat > .gitignore << 'EOF'
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
env/
ENV/
.venv

# Flask
instance/
.webassets-cache

# Environment
.env
.env.local

# Database
*.db
*.sqlite
*.sqlite3

# Logs
logs/
*.log

# Uploads
uploads/
temp_uploads/
integration_data/

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Distribution
build/
dist/
*.egg-info/
EOF

echo "✅ .gitignore created"
echo ""

# ============================================
# STEP 3: Create .env.example
# ============================================
echo "📝 Creating .env.example..."
cat > .env.example << 'EOF'
# Flask
FLASK_APP=wsgi.py
FLASK_ENV=development
SECRET_KEY=your-secret-key-here-change-in-production

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/invoice_dev

# Redis
REDIS_URL=redis://localhost:6379/0

# QuickBooks
QUICKBOOKS_CLIENT_ID=your_client_id
QUICKBOOKS_CLIENT_SECRET=your_client_secret
QUICKBOOKS_REDIRECT_URI=http://localhost:5000/callback
QUICKBOOKS_ENVIRONMENT=sandbox

# OpenAI
OPENAI_API_KEY=your_openai_api_key

# Gmail
GMAIL_CREDENTIALS_PATH=credentials.json

# Telegram
TELEGRAM_BOT_TOKEN=your_telegram_token
TELEGRAM_CHAT_ID=your_chat_id

# Sentry (Optional)
SENTRY_DSN=

# Application
APP_URL=http://localhost:5000
MAX_UPLOAD_SIZE=16777216
EOF

cp .env.example .env
echo "✅ .env files created"
echo ""

# ============================================
# STEP 4: Create requirements.txt
# ============================================
echo "📝 Creating requirements.txt..."
cat > requirements.txt << 'EOF'
# Core Framework
Flask==3.0.0
flask-sqlalchemy==3.1.1
flask-migrate==4.0.5
flask-login==0.6.3
flask-wtf==1.2.1
Werkzeug==3.0.1

# Database
psycopg2-binary==2.9.9
alembic==1.13.1

# Background Tasks
celery==5.3.4
redis==5.0.1

# API & Auth
flask-cors==4.0.0
flask-limiter==3.5.0
PyJWT==2.8.0

# Security
cryptography==41.0.7
python-dotenv==1.0.0
bcrypt==4.1.2

# QuickBooks
requests==2.31.0
oauthlib==3.2.2
requests-oauthlib==1.3.1

# Gmail
google-auth==2.25.2
google-auth-oauthlib==1.2.0
google-auth-httplib2==0.2.0
google-api-python-client==2.111.0

# PDF Processing
PyPDF2==3.0.1
pdfplumber==0.10.3

# AI
openai==1.6.1
thefuzz==0.22.1

# Utilities
python-dateutil==2.8.2
pytz==2023.3.post1
click==8.1.7

# Monitoring
sentry-sdk[flask]==1.39.2

# Production Server
gunicorn==21.2.0
gevent==23.9.1

# Development
pytest==7.4.3
pytest-cov==4.1.0
pytest-flask==1.3.0
black==23.12.1
flake8==7.0.0
EOF

echo "✅ requirements.txt created"
echo ""

# ============================================
# STEP 5: Create Dockerfile
# ============================================
echo "🐳 Creating Dockerfile..."
cat > Dockerfile << 'EOF'
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p logs uploads temp_uploads integration_data/queue

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8000/health')"

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "120", "wsgi:app"]
EOF

echo "✅ Dockerfile created"
echo ""

# ============================================
# STEP 6: Create docker-compose.yml
# ============================================
echo "🐳 Creating docker-compose.yml..."
cat > docker-compose.yml << 'EOF'
version: '3.8'

services:
  web:
    build: .
    command: flask run --host=0.0.0.0 --port=5000 --reload
    volumes:
      - .:/app
      - upload_data:/app/uploads
    ports:
      - "5000:5000"
    environment:
      - FLASK_APP=wsgi.py
      - FLASK_ENV=development
      - DATABASE_URL=postgresql://postgres:password@db:5432/invoice_dev
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis
    env_file:
      - .env

  db:
    image: postgres:15-alpine
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=invoice_dev
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=password
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  celery_worker:
    build: .
    command: celery -A app.celery worker --loglevel=info
    volumes:
      - .:/app
    environment:
      - DATABASE_URL=postgresql://postgres:password@db:5432/invoice_dev
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis
    env_file:
      - .env

  celery_beat:
    build: .
    command: celery -A app.celery beat --loglevel=info
    volumes:
      - .:/app
    environment:
      - DATABASE_URL=postgresql://postgres:password@db:5432/invoice_dev
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis
    env_file:
      - .env

volumes:
  postgres_data:
  upload_data:
EOF

echo "✅ docker-compose.yml created"
echo ""

# ============================================
# STEP 7: Create Railway & Procfile
# ============================================
echo "🚂 Creating railway.toml..."
cat > railway.toml << 'EOF'
[build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile"

[deploy]
startCommand = "gunicorn wsgi:app --workers 4 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT"
healthcheckPath = "/health"
healthcheckTimeout = 100
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10
EOF

cat > Procfile << 'EOF'
web: gunicorn wsgi:app --workers 4 --threads 4 --timeout 120
worker: celery -A app.celery worker --loglevel=info
beat: celery -A app.celery beat --loglevel=info
EOF

echo "✅ Railway & Procfile created"
echo ""

# ============================================
# STEP 8: Create README
# ============================================
echo "📖 Creating README..."
cat > README.md << 'EOF'
# Invoice Processor SaaS

Automated invoice processing system with QuickBooks integration.

## Quick Start

### Local Development
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and edit environment file
cp .env.example .env
# Edit .env with your credentials

# Run the app
flask run
```

### With Docker
```bash
docker-compose up
```

## Features

- 📧 Automatic Gmail monitoring
- 📄 PDF parsing
- 🤖 AI-powered description cleaning
- 💰 Intelligent pricing
- 📊 QuickBooks integration
EOF

echo "✅ README created"
echo ""

# ============================================
# COMPLETE!
# ============================================
echo "🎉 Setup complete!"
echo ""
echo "✅ Directory structure"
echo "✅ Configuration files"
echo "✅ Docker setup"
echo "✅ Requirements file"
echo "✅ Documentation"
echo ""
echo "📋 Next steps:"
echo "1. Edit .env with your actual credentials"
echo "2. Create Python virtual environment: python3 -m venv venv"
echo "3. Activate it: source venv/bin/activate"
echo "4. Install dependencies: pip install -r requirements.txt"
echo ""
echo "Or use Docker:"
echo "  docker-compose up"
echo ""
