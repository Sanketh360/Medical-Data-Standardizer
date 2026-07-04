import os
import pymysql.cursors
from dotenv import load_dotenv

# Load variables from local .env file (safely excluded from Git)
load_dotenv()

DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'user': os.environ.get('DB_USER', 'root'),
    'password': os.environ.get('DB_PASSWORD'),
    'database': os.environ.get('DB_NAME', 'medical_data_standardisation'),
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

def get_db_connection():
    """Establish and return a connection to the MySQL database."""
    return pymysql.connect(**DB_CONFIG)
