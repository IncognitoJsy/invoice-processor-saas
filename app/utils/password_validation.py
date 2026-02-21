"""Password validation utilities for Intuit password policy compliance."""
import re


def validate_password(password):
    """
    Validate password meets Intuit Developer Services password policy.
    
    Requirements:
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    - Not a commonly used password
    
    Returns (is_valid: bool, error_message: str or None)
    """
    if len(password) < 8:
        return False, 'Password must be at least 8 characters.'
    
    if not re.search(r'[A-Z]', password):
        return False, 'Password must contain at least one uppercase letter.'
    
    if not re.search(r'[a-z]', password):
        return False, 'Password must contain at least one lowercase letter.'
    
    if not re.search(r'\d', password):
        return False, 'Password must contain at least one number.'
    
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?`~]', password):
        return False, 'Password must contain at least one special character (!@#$%^&* etc.).'
    
    # Check against common passwords
    common_passwords = {
        'password', 'password1', '12345678', 'qwerty123', 'letmein1',
        'welcome1', 'monkey123', 'dragon12', 'master12', 'abc12345',
        'Password1', 'Password1!', 'Qwerty123!', 'Admin123!',
    }
    if password.lower().rstrip('!@#$%^&*') in {p.lower() for p in common_passwords}:
        return False, 'That password is too common. Please choose a stronger password.'
    
    return True, None
