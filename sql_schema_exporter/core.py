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
        # Pass conn so save_definitions can call get_table_definition
        save_definitions(tables, output_subdir, output_dir_base, conn=conn)
        return tables # Return fetched table names
    except pyodbc.Error as ex:
        logging.error(f"Error fetching table names: {ex}")
        return [] # Return empty list on error
    finally:
        cursor.close()

# --- Table Definition Generation ---

def get_table_definition(conn, schema_name, table_name):
    """Generates a CREATE TABLE statement for a given table."""
    cursor = conn.cursor()
    parts = [f"CREATE TABLE [{schema_name}].[{table_name}] ("]

    # Get Columns
    column_defs = []
    try:
        col_query = """
        SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT,
               CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE, DATETIME_PRECISION
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION;
        """
        cursor.execute(col_query, schema_name, table_name)
        for col in cursor.fetchall():
            name, dtype, nullable, default, char_len, num_prec, num_scale, dt_prec = col
            col_def = f"    [{name}] {dtype.upper()}"
            # Add size/precision/scale
            if dtype.upper() in ('VARCHAR', 'NVARCHAR', 'CHAR', 'NCHAR', 'VARBINARY', 'BINARY'):
                col_def += f"({'MAX' if char_len == -1 else char_len})"
            elif dtype.upper() in ('DECIMAL', 'NUMERIC'):
                col_def += f"({num_prec}, {num_scale})"
            elif dtype.upper() in ('DATETIME2', 'DATETIMEOFFSET', 'TIME'):
                 col_def += f"({dt_prec})"
            # Nullability
            col_def += " NULL" if nullable == 'YES' else " NOT NULL"
            # Default constraint (simple version, complex defaults need sys.default_constraints)
            if default:
                # Defaults often come with extra parentheses like ((0)) or (getdate())
                default_val = default.strip('()')
                # Handle common cases like getdate() or specific values
                if default_val.lower() == 'getdate':
                    col_def += f" DEFAULT GETDATE()"
                elif default_val.lower() == 'newid':
                     col_def += f" DEFAULT NEWID()"
                else:
                    # Attempt to add simple literal defaults, might need more quoting logic
                    col_def += f" DEFAULT {default_val}" # Needs improvement for strings etc.

            column_defs.append(col_def)
    except pyodbc.Error as ex:
        logging.warning(f"Could not fetch column details for {schema_name}.{table_name}: {ex}")
        return f"-- Could not generate definition for table {schema_name}.{table_name}\n-- Error fetching columns: {ex}\nGO"

    # TODO: Add Primary Key Constraint (query sys.key_constraints, sys.index_columns)
    # TODO: Add Unique Constraints
    # TODO: Add Check Constraints (query sys.check_constraints)
    # TODO: Add Foreign Key Constraints (query sys.foreign_keys, sys.foreign_key_columns)

    parts.append(",\n".join(column_defs))
    parts.append(");") # Closing parenthesis for columns

    # TODO: Add Indexes (query sys.indexes, sys.index_columns) - separate CREATE INDEX statements usually

    parts.append("GO") # Add GO separator

    return "\n".join(parts)


# --- File Writing ---
def save_definitions(objects, subdir, output_dir_base, create_placeholders=False, conn=None):
    """Saves the fetched definitions or creates placeholders/definitions."""
    # conn is needed only when generating table defs on the fly
    output_path = Path(output_dir_base) / subdir
    output_path.mkdir(parents=True, exist_ok=True) # Create subdir if not exists

    count = 0
    for item in objects:
        schema_name = item[0]
        object_name = item[1]
        # Sanitize names slightly in case they contain invalid characters for filenames
        safe_object_name = "".join(c if c.isalnum() or c in ('.', '_') else '_' for c in object_name)
        file_name = f"{schema_name}.{safe_object_name}.sql"
        file_name = f"{schema_name}.{safe_object_name}.sql"
        file_path = output_path / file_name

        content = ""
        if subdir == 'tables':
            # Generate table definition instead of using placeholder
            if conn:
                 try:
                     content = get_table_definition(conn, schema_name, object_name)
                 except Exception as e:
                     logging.error(f"Failed to generate definition for table {schema_name}.{object_name}: {e}")
                     content = f"-- Failed to generate definition for table {schema_name}.{object_name}\n-- Error: {e}\nGO"
            else:
                 # Fallback if connection isn't passed (shouldn't happen with current flow)
                 content = f"-- Connection object not available to generate definition for table {schema_name}.{object_name}\nGO"
        else:
             # Existing logic for Sprocs and Views
             # item[2] should be the definition
             definition = item[2]
             if definition:
                 content = definition.strip()
                 # Add GO statement for SQL Server Management Studio compatibility if desired
                 content += "\nGO"
             else:
                 logging.warning(f"No definition found for {subdir} {schema_name}.{object_name}")
                 content = f"-- No definition found for {schema_name}.{object_name}\nGO"

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
            logging.debug("Connection established. Fetching stored procedures...")
            fetch_objects(conn, 'P', 'sprocs', output_dir)

            logging.debug("Fetching views...")
            fetch_objects(conn, 'V', 'views', output_dir)

            logging.debug("Fetching tables...")
            fetch_tables(conn, 'tables', output_dir) # fetch_tables now calls save_definitions internally

            logging.info("Schema export process completed successfully.")
            return True # Indicate success
    except ConnectionError as e:
        # Connection errors already logged by get_db_connection
        logging.error(f"Export failed due to connection error: {e}") # Add context
        return False # Indicate failure due to connection
    except pyodbc.Error as db_err:
        # Catch pyodbc errors specifically that might occur *after* connection
        logging.error(f"A database error occurred during export: {db_err}")
        return False # Indicate failure due to database operation error
    except Exception as e:
        # Catch any other unexpected errors
        logging.error(f"An unexpected non-database error occurred during export: {e}", exc_info=True) # Log traceback
        return False # Indicate failure due to other error
    finally:
        if conn:
            conn.close()
            logging.info("Database connection closed.")
