import getpass
import logging
from pathlib import Path
# Use absolute import instead of relative for direct script execution
from sql_schema_exporter.core import export_schema

# Setup logging (consistent with core)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DEFAULT_OUTPUT_DIR = Path('output') # Default relative to where script is run

def get_connection_details_from_user():
    """Prompts the user for connection details."""
    print("Please enter SQL Server connection details:")
    server = input("Server Name (e.g., localhost\\SQLEXPRESS or server.database.windows.net): ")
    database = input("Database Name: ")
    auth_method = input("Use Windows Authentication? (yes/no) [yes]: ").lower()

    username = None
    password = None
    if auth_method == 'no':
        username = input("Username: ")
        password = getpass.getpass("Password: ") # Use getpass for password security
    elif auth_method != 'yes' and auth_method != '':
         print("Invalid choice. Assuming Windows Authentication.")
         username = None
         password = None

    output_dir_str = input(f"Output directory [{DEFAULT_OUTPUT_DIR}]: ")
    output_dir = Path(output_dir_str) if output_dir_str else DEFAULT_OUTPUT_DIR

    return server, database, username, password, output_dir

def main():
    """Main CLI entry point."""
    server, database, username, password, output_dir = get_connection_details_from_user()

    logging.info(f"Starting schema export to directory: {output_dir.resolve()}")

    # Ensure output directory exists (optional, core.save_definitions also does this)
    # output_dir.mkdir(parents=True, exist_ok=True)

    success = export_schema(server, database, username, password, output_dir)

    if success:
        print(f"\nSchema export completed successfully to {output_dir.resolve()}")
    else:
        print("\nSchema export failed. Check logs for details.")
        # Exit with a non-zero code to indicate failure
        exit(1)

if __name__ == "__main__":
    main()
