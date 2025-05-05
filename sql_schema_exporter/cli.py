import getpass
import logging
import re # Import regex for sanitization
from pathlib import Path
# Use absolute import instead of relative for direct script execution
from sql_schema_exporter.core import export_schema
from sql_schema_exporter.lineage import generate_lineage # Import lineage function

# Setup logging (consistent with core)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Helper Functions ---
def sanitize_for_filename(name):
    """Removes or replaces characters invalid for filenames/directory names."""
    # Remove leading/trailing whitespace
    name = name.strip()
    # Replace sequences of invalid characters (including spaces) with a single underscore
    name = re.sub(r'[\\/*?:"<>|\s]+', '_', name)
    # Ensure it's not empty after sanitization
    if not name:
        return "_"
    return name

# --- Main Functions ---
def get_connection_details_from_user():
    """Prompts the user for connection details."""
    print("Please enter SQL Server connection details:")
    server = input("Server Name (e.g., localhost\\SQLEXPRESS or server.database.windows.net): ")
    database = input("Database Name: ")
    # Clarify that 'no' is needed for SQL Login
    auth_method = input("Use Windows Authentication (Trusted Connection)? (Enter 'no' for SQL Server Login) [yes]: ").lower()

    username = None
    password = None
    # Explicitly check for 'no' to prompt for SQL Server Authentication details
    if auth_method == 'no':
        username = input("Username: ")
        password = getpass.getpass("Password: ") # Use getpass for password security
    # Otherwise, assume Windows Authentication (for 'yes', empty input, or anything else)
    else:
        if auth_method != 'yes' and auth_method != '':
            print("Invalid choice. Assuming Windows Authentication.")
        # For 'yes' or invalid choice, username and password remain None

    # Automatically determine output directory from sanitized database name
    output_dir = Path(sanitize_for_filename(database))

    return server, database, username, password, output_dir

def main():
    """Main CLI entry point."""
    server, database, username, password, output_dir = get_connection_details_from_user()

    logging.info(f"Starting schema export to directory: {output_dir.resolve()}")

    # Ensure output directory exists (optional, core.save_definitions also does this)
    # output_dir.mkdir(parents=True, exist_ok=True)

    export_success = export_schema(server, database, username, password, output_dir)

    if export_success:
        print(f"\nSchema export completed successfully to {output_dir.resolve()}")
        # Attempt to generate lineage map
        print("\nAttempting to generate data lineage map...")
        logging.info(f"Starting lineage generation for {database}...")
        try:
            deps_ok, dot_ok, render_err = generate_lineage(
                server, database, username, password, output_dir
            )
            if deps_ok and dot_ok:
                print(f"Lineage DOT graph saved in {output_dir.resolve()}")
                if render_err:
                    print(f"Warning: {render_err}") # Report render error but don't fail exit code
                else:
                    print(f"Lineage graph image rendered in {output_dir.resolve()}")
            elif not deps_ok:
                 print("Lineage generation failed during dependency lookup. Check logs.")
                 # Consider if this should cause exit(1)? For now, just report.
            else: # deps_ok but not dot_ok
                 print("Lineage generation failed while saving DOT file. Check logs.")

        except Exception as lineage_e:
            # Catch unexpected errors during lineage call itself
            print(f"An unexpected error occurred during lineage generation: {lineage_e}")
            logging.error(f"Lineage generation failed unexpectedly: {lineage_e}", exc_info=True)

    else:
        print("\nSchema export failed. Check logs for details.")
        # Exit with a non-zero code to indicate failure
        exit(1)

if __name__ == "__main__":
    main()
