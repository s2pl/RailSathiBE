import os
import logging
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, date
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

print("DB User:", os.getenv("POSTGRES_USER"))

# Database configuration
DB_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': int(os.getenv('POSTGRES_PORT', 5432)),
    'user': os.getenv('POSTGRES_USER', 'postgres'),
    'password': os.getenv('POSTGRES_PASSWORD', 'password'),
    'database': os.getenv('POSTGRES_DB', 'rail_sathi_db')
}

def get_db_connection():
    """Get database connection"""
    try:
        connection = psycopg2.connect(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            database=DB_CONFIG['database']
        )
        connection.autocommit = False
        return connection
    except Exception as e:
        logger.error(f"Database connection failed: {str(e)}")
        raise

@contextmanager
def get_db_cursor():
    """Context manager for database operations"""
    connection = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        yield cursor, connection
    except Exception as e:
        if connection:
            connection.rollback()
        logger.error(f"Database operation failed: {str(e)}")
        raise
    finally:
        if connection:
            connection.close()

def serialize_datetime(obj):
    """Convert datetime objects to strings for JSON serialization"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj

def serialize_row(row):
    """Serialize a database row for JSON response"""
    if not row:
        return None
    
    serialized = {}
    for key, value in row.items():
        serialized[key] = serialize_datetime(value)
    return serialized

def serialize_rows(rows):
    """Serialize multiple database rows for JSON response"""
    if not rows:
        return []
    
    return [serialize_row(row) for row in rows]

def execute_query(connection, query: str, params: Tuple = None) -> List[Dict]:
    """Execute a SELECT query and return results"""
    try:
        cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(query, params)
        results = cursor.fetchall()
        return serialize_rows(results)
    except Exception as e:
        logger.error(f"Query execution failed: {str(e)}")
        logger.error(f"Query: {query}")
        logger.error(f"Params: {params}")
        raise

def execute_query_one(connection, query: str, params: Tuple = None) -> Optional[Dict]:
    """Execute a SELECT query and return single result"""
    try:
        cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(query, params)
        result = cursor.fetchone()
        return serialize_row(result)
    except Exception as e:
        logger.error(f"Query execution failed: {str(e)}")
        logger.error(f"Query: {query}")
        logger.error(f"Params: {params}")
        raise

def execute_insert(connection, query: str, params: Tuple = None) -> int:
    """Execute an INSERT query and return last insert ID"""
    try:
        cursor = connection.cursor()
        cursor.execute(query, params)
        # For PostgreSQL, we need to use RETURNING clause or currval()
        # This assumes the query includes RETURNING id or similar
        if 'RETURNING' in query.upper():
            result = cursor.fetchone()
            return result[0] if result else None
        else:
            # Fallback for queries without RETURNING
            return cursor.rowcount
    except Exception as e:
        logger.error(f"Insert execution failed: {str(e)}")
        logger.error(f"Query: {query}")
        logger.error(f"Params: {params}")
        raise

def execute_update(connection, query: str, params: Tuple = None) -> int:
    """Execute an UPDATE query and return affected rows"""
    try:
        cursor = connection.cursor()
        cursor.execute(query, params)
        return cursor.rowcount
    except Exception as e:
        logger.error(f"Update execution failed: {str(e)}")
        logger.error(f"Query: {query}")
        logger.error(f"Params: {params}")
        raise

def execute_delete(connection, query: str, params: Tuple = None) -> int:
    """Execute a DELETE query and return affected rows"""
    try:
        cursor = connection.cursor()
        cursor.execute(query, params)
        return cursor.rowcount
    except Exception as e:
        logger.error(f"Delete execution failed: {str(e)}")
        logger.error(f"Query: {query}")
        logger.error(f"Params: {params}")
        raise

def test_connection():
    """Test database connection"""
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        connection.close()
        logger.info("Database connection test successful")
        return True
    except Exception as e:
        logger.error(f"Database connection test failed: {str(e)}")
        return False

def init_database():
    """Initialize database connection and test"""
    logger.info("Initializing database connection...")
    logger.info(f"Database Host: {DB_CONFIG['host']}")
    logger.info(f"Database Name: {DB_CONFIG['database']}")
    
    if test_connection():
        logger.info("Database initialization successful")
        return True
    else:
        logger.error("Database initialization failed")
        return False

if __name__ == "__main__":
    # Test database connection
    init_database()