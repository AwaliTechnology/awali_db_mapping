import os
import pyodbc
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Database Connection ---
def get_db_connection(server, database, username, password):
    """Establishes a connection to the SQL Server database using provided details."""
    # NOTE: Ensure the DRIVER name matches the one registered in your odbcinst.ini
    # Common names: {ODBC Driver 17 for SQL Server}, {ODBC Driver 18 for SQL Server}, {msodbcsql17}
    # Check your system's ODBC configuration if connection fails with 'driver not found'.
    conn_str = [
        f'DRIVER={{ODBC Driver 17 for SQL Server}}',
        f'SERVER={server}',
        f'DATABASE={database}',
    ]
    if username:
        conn_str.append(f'UID={username}')
        # Only add PWD if password is provided (it might be empty for some auth methods)
        if password is not None:
             conn_str.append(f'PWD={password}')
    else:
        # Use Windows Authentication (Trusted Connection)
        conn_str.append('Trusted_Connection=yes')

    connection_string = ';'.join(conn_str)
    logging.info(f"Connecting to {server}/{database}...")
    try:
        conn = pyodbc.connect(connection_string, autocommit=True) # Autocommit often useful for scripts
        logging.info("Connection successful.")
        return conn
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        logging.error(f"Error connecting to database: {sqlstate} - {ex}")
        # Re-raise a more specific exception or return None to indicate failure
        raise ConnectionError(f"Database connection failed: {ex}") from ex

# --- Extraction Functions ---
def fetch_objects(conn, object_type_code, output_subdir, output_dir_base):
    """Fetches definitions for a given object type (View or Stored Procedure)."""
    cursor = conn.cursor()
    # Using INFORMATION_SCHEMA.ROUTINES for broader compatibility (includes functions)
    # and OBJECT_DEFINITION for the actual source.
    query = """
    SELECT
        ROUTINE_SCHEMA,
        ROUTINE_NAME,
        OBJECT_DEFINITION(OBJECT_ID(QUOTENAME(ROUTINE_SCHEMA) + '.' + QUOTENAME(ROUTINE_NAME))) AS definition
    FROM INFORMATION_SCHEMA.ROUTINES
    WHERE ROUTINE_TYPE = ? -- 'PROCEDURE' or 'FUNCTION' (OBJECT_DEFINITION works for Views too)
    ORDER BY ROUTINE_SCHEMA, ROUTINE_NAME;
    """
    # Adjust query and parameters for Views
    object_type_name = "Stored Procedures"
    param = 'PROCEDURE'
    if object_type_code == 'V':
        query = """
        SELECT
            TABLE_SCHEMA,
            TABLE_NAME,
            VIEW_DEFINITION
        FROM INFORMATION_SCHEMA.VIEWS
        ORDER BY TABLE_SCHEMA, TABLE_NAME;
        """
        param = None # No parameter needed for the view query
        object_type_name = "Views"


    logging.info(f"Fetching {object_type_name} definitions...")
    try:
        if param:
            cursor.execute(query, param)
        else:
            cursor.execute(query) # For Views

        objects = cursor.fetchall()
        logging.info(f"Found {len(objects)} {object_type_name}.")
        save_definitions(objects, output_subdir, output_dir_base)
        return objects # Return fetched objects for potential use/testing
    except pyodbc.Error as ex:
        logging.error(f"Error fetching {object_type_name}: {ex}")
        return [] # Return empty list on error
    finally:
        cursor.close()

def fetch_tables(conn, output_subdir, output_dir_base):
    """Fetches table names and creates placeholder files."""
    cursor = conn.cursor()
    query = """
    SELECT TABLE_SCHEMA, TABLE_NAME
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_TYPE = 'BASE TABLE'
    ORDER BY TABLE_SCHEMA, TABLE_NAME;
    """
    logging.info(f"Fetching table names...")
    try:
        cursor.execute(query)
        tables = cursor.fetchall()
        logging.info(f"Found {len(tables)} tables.")
        # Pass create_placeholders=True to save_definitions
        save_definitions(tables, output_subdir, output_dir_base, create_placeholders=True)
        return tables # Return fetched table names
    except pyodbc.Error as ex:
        logging.error(f"Error fetching tables: {ex}")
        return [] # Return empty list on error
    finally:
        cursor.close()


# --- File Writing ---
def save_definitions(objects, subdir, output_dir_base, create_placeholders=False):
    """Saves the fetched definitions or creates placeholders."""
    output_path = Path(output_dir_base) / subdir
    output_path.mkdir(parents=True, exist_ok=True) # Create subdir if not exists

    count = 0
    for item in objects:
        schema_name = item[0]
        object_name = item[1]
        # Sanitize names slightly in case they contain invalid characters for filenames
        safe_object_name = "".join(c if c.isalnum() or c in ('.', '_') else '_' for c in object_name)
        file_name = f"{schema_name}.{safe_object_name}.sql"
        file_path = output_path / file_name

        content = ""
        if not create_placeholders:
            # item[2] should be the definition (for sprocs/views)
            definition = item[2]
            if definition:
                content = definition.strip()
                # Add GO statement for SQL Server Management Studio compatibility if desired
                content += "\nGO"
            else:
                logging.warning(f"No definition found for {subdir} {schema_name}.{object_name}")
                content = f"-- No definition found for {schema_name}.{object_name}\nGO"
        else:
            # Placeholder content for tables
            content = f"-- Placeholder for table {schema_name}.{object_name}\n-- Definition needs to be scripted separately.\nGO"

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            logging.debug(f"Saved definition to {file_path}")
            count += 1
        except IOError as e:
            logging.error(f"Error writing file {file_path}: {e}")
    logging.info(f"Saved {count} files to {output_path}")


# --- Main Orchestration Function ---
def export_schema(server, database, username, password, output_dir):
    """Connects to the DB and exports schema objects."""
    conn = None
    try:
        conn = get_db_connection(server, database, username, password)
        if conn:
            # Fetch and save Stored Procedures ('P')
            fetch_objects(conn, 'P', 'sprocs', output_dir)

            # Fetch and save Views ('V')
            fetch_objects(conn, 'V', 'views', output_dir)

            # Fetch table names and create placeholders
            fetch_tables(conn, 'tables', output_dir)

            logging.info("Schema export process completed successfully.")
            return True # Indicate success
    except ConnectionError as e:
        # Connection errors already logged by get_db_connection
        return False # Indicate failure due to connection
    except Exception as e:
        logging.error(f"An unexpected error occurred during export: {e}")
        return False # Indicate failure due to other error
    finally:
        if conn:
            conn.close()
            logging.info("Database connection closed.")
