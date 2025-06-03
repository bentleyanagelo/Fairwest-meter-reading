import os
import psycopg2
import re
from urllib.parse import urlparse

def get_db_connection():
    """
    Establishes a database connection using DATABASE_URL environment variable.
    Parses the DATABASE_URL to extract connection parameters.
    """
    # CORRECTED: Fetch the environment variable named 'DATABASE_URL'
    database_url = os.environ.get('DATABASE_URL')

    if not database_url:
        # Fallback for local development if DATABASE_URL is not set
        # Ensure these match your local postgresql setup
        print("DATABASE_URL not found, using local default connection parameters.")
        return psycopg2.connect(
            host="127.0.0.1", # Changed back to 127.0.0.1 for typical local setup
            database="fairwest", # Changed back to fairwest for typical local setup
            user="postgres",
            password="admin",
            port="5432" # Explicitly specify port for clarity
        )
    
    # Parse the DATABASE_URL provided by Railway
    result = urlparse(database_url)
    username = result.username
    password = result.password
    database = result.path[1:]
    hostname = result.hostname
    port = result.port

    conn = psycopg2.connect(
        host=hostname,
        database=database,
        user=username,
        password=password,
        port=port
    )
    conn.autocommit = False # We will manage transactions manually for migrations
    return conn

def apply_migrations():
    """
    Applies pending SQL migration scripts to the database.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Ensure the applied_migrations table exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS applied_migrations (
                id SERIAL PRIMARY KEY,
                version TEXT UNIQUE NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit() # Commit the table creation if it happened

        # Get already applied migrations
        cursor.execute("SELECT version FROM applied_migrations ORDER BY version ASC")
        applied_versions = {row[0] for row in cursor.fetchall()}
        print(f"Already applied migrations: {applied_versions}")

        # Find all migration files
        migrations_dir = os.path.join(os.path.dirname(__file__), 'migrations')
        migration_files = sorted([f for f in os.listdir(migrations_dir) if f.endswith('.sql')])
        print(f"Found migration files: {migration_files}")

        for filename in migration_files:
            version = filename.split('_')[0] # Assumes '001_...' format

            if version in applied_versions:
                print(f"Skipping migration {filename} (already applied).")
                continue

            filepath = os.path.join(migrations_dir, filename)
            print(f"Applying migration: {filename}...")
            
            # --- CHANGE IS HERE ---
            with open(filepath, 'r', encoding='utf-8') as f: 
                sql_script = f.read()
            
            # Split SQL script into individual statements
            # This regex splits by semicolon, but handles semicolons within strings
            # (though simple splitting might be sufficient for well-formed migration files)
            sql_commands = [cmd.strip() for cmd in sql_script.split(';') if cmd.strip()]

            for command in sql_commands:
                if command: # Ensure command is not empty
                    try:
                        cursor.execute(command)
                        print(f"    Executed: {command[:70]}...") # Print first 70 chars
                    except psycopg2.Error as e:
                        print(f"    ERROR executing command in {filename}: {e}")
                        conn.rollback() # Rollback on error
                        raise # Re-raise to stop the migration process
            
            # Record the applied migration
            cursor.execute("INSERT INTO applied_migrations (version) VALUES (%s)", (version,))
            conn.commit()
            print(f"Migration {filename} applied successfully and recorded.")

    except psycopg2.Error as e:
        print(f"Database error during migration: {e}")
        if conn:
            conn.rollback() # Ensure rollback if an error occurred before explicit commits
        raise
    except Exception as e:
        print(f"An unexpected error occurred during migration: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()
            print("Database connection closed.")

if __name__ == '__main__':
    print("Starting database migration process...")
    try:
        apply_migrations()
        print("Database migration process completed successfully.")
    except Exception as e:
        print(f"Database migration process failed: {e}")
        exit(1) # Exit with a non-zero code to indicate failure