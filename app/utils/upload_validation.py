"""
File upload validation utilities.

Intuit App Store security review checks for:
- File extension validation (whitelist only)
- MIME type validation (magic bytes, not just Content-Type header)
- File size limits
- Prevention of executable uploads
- Prevention of path traversal in filenames

Usage:
    from app.utils.upload_validation import validate_upload
    
    error = validate_upload(file)
    if error:
        return jsonify({'error': error}), 400
"""
import os
import re

# Allowed file extensions (must match Config.ALLOWED_EXTENSIONS)
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

# Allowed MIME types mapped to extensions
ALLOWED_MIME_TYPES = {
    'application/pdf': {'pdf'},
    'image/png': {'png'},
    'image/jpeg': {'jpg', 'jpeg'},
}

# Magic bytes for file type verification
FILE_SIGNATURES = {
    'pdf': [b'%PDF'],
    'png': [b'\x89PNG\r\n\x1a\n'],
    'jpg': [b'\xff\xd8\xff'],
    'jpeg': [b'\xff\xd8\xff'],
}

# Dangerous extensions that should never be uploaded
BLOCKED_EXTENSIONS = {
    'exe', 'bat', 'cmd', 'com', 'msi', 'scr', 'pif',  # Windows executables
    'sh', 'bash', 'csh',                                  # Shell scripts
    'php', 'php3', 'php4', 'php5', 'phtml',              # PHP
    'py', 'pyc', 'pyo',                                   # Python
    'js', 'jsx', 'ts',                                    # JavaScript
    'jsp', 'jspx', 'asp', 'aspx',                        # Server pages
    'rb', 'pl', 'cgi',                                    # Other scripts
    'html', 'htm', 'svg', 'xml',                          # Markup (XSS risk)
    'swf', 'jar', 'war',                                  # Java/Flash
    'dll', 'so', 'dylib',                                 # Libraries
    'zip', 'tar', 'gz', 'rar', '7z',                     # Archives (could contain executables)
}

# Maximum file size (16MB - matches Config.MAX_CONTENT_LENGTH)
MAX_FILE_SIZE = 16 * 1024 * 1024


def get_file_extension(filename):
    """Safely extract file extension, lowercased."""
    if not filename or '.' not in filename:
        return None
    return filename.rsplit('.', 1)[1].lower()


def sanitize_filename(filename):
    """
    Sanitize filename to prevent path traversal and other attacks.
    
    - Strips directory components
    - Removes dangerous characters
    - Limits length
    """
    if not filename:
        return None
    
    # Strip any directory path components
    filename = os.path.basename(filename)
    
    # Remove null bytes
    filename = filename.replace('\x00', '')
    
    # Remove path traversal patterns
    filename = filename.replace('..', '')
    filename = filename.replace('/', '').replace('\\', '')
    
    # Only allow safe characters: alphanumeric, dash, underscore, dot
    filename = re.sub(r'[^\w\-.]', '_', filename)
    
    # Limit length (255 is typical filesystem max)
    if len(filename) > 200:
        ext = get_file_extension(filename)
        filename = filename[:195] + '.' + ext if ext else filename[:200]
    
    return filename


def validate_upload(file_storage, max_size=MAX_FILE_SIZE):
    """
    Validate an uploaded file for security.
    
    Args:
        file_storage: Flask FileStorage object (from request.files)
        max_size: Maximum allowed file size in bytes
        
    Returns:
        str or None: Error message if validation fails, None if valid
    """
    if not file_storage or not file_storage.filename:
        return 'No file provided.'
    
    filename = file_storage.filename
    
    # 1. Check extension is allowed
    ext = get_file_extension(filename)
    if not ext:
        return 'File must have an extension.'
    
    if ext in BLOCKED_EXTENSIONS:
        return 'This file type is not allowed.'
    
    if ext not in ALLOWED_EXTENSIONS:
        return f'Only {", ".join(sorted(ALLOWED_EXTENSIONS))} files are accepted.'
    
    # 2. Check MIME type from Content-Type header
    content_type = file_storage.content_type or ''
    if content_type:
        # Normalize content type (strip parameters like charset)
        base_type = content_type.split(';')[0].strip().lower()
        
        if base_type in ALLOWED_MIME_TYPES:
            # Verify extension matches MIME type
            if ext not in ALLOWED_MIME_TYPES[base_type]:
                return 'File extension does not match file type.'
        elif base_type not in ('application/octet-stream', ''):
            # application/octet-stream is generic, allow it and verify via magic bytes
            return f'File type "{base_type}" is not allowed.'
    
    # 3. Check magic bytes (file signature)
    try:
        header = file_storage.read(16)
        file_storage.seek(0)  # Reset file pointer
        
        if ext in FILE_SIGNATURES:
            signatures = FILE_SIGNATURES[ext]
            if not any(header.startswith(sig) for sig in signatures):
                return 'File content does not match its extension. The file may be corrupted or mislabelled.'
    except Exception:
        return 'Could not read file for validation.'
    
    # 4. Check file size
    try:
        file_storage.seek(0, 2)  # Seek to end
        size = file_storage.tell()
        file_storage.seek(0)  # Reset
        
        if size == 0:
            return 'File is empty.'
        
        if size > max_size:
            max_mb = max_size / (1024 * 1024)
            return f'File is too large. Maximum size is {max_mb:.0f}MB.'
    except Exception:
        pass  # Flask's MAX_CONTENT_LENGTH will catch oversized files
    
    return None  # All checks passed
