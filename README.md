# SQL Server Schema Exporter

This project provides a tool to connect to a Microsoft SQL Server database, extract the definitions of stored procedures, views, and tables, and save them into a structured directory layout (`sprocs/`, `views/`, `tables/`) as individual `.sql` files.

The primary goal is to facilitate version control, code review, and offline browsing of database schema objects. See [system_knowledge/project_goal.md](system_knowledge/project_goal.md) for more details.

The project uses a Behavior-Driven Development (BDD) approach with the Behave framework.

## Setup and Installation

### 1. Clone the Repository

```bash
git clone <your-repository-url>
cd <your-repository-directory>
```

### 2. System Dependencies (ODBC Driver)

This tool uses the `pyodbc` Python library, which requires a system-level ODBC driver for SQL Server to be installed.

**On macOS (using Homebrew):**

```bash
# Tap the Microsoft repository (if you haven't already)
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release

# Update brew and install the driver (e.g., version 17)
brew update
brew install msodbcsql17
# Note: mssql-tools (sqlcmd, bcp) are optional for this script but often installed alongside
# brew install mssql-tools
```

*   Verify the driver installation by checking your `odbcinst.ini` file (e.g., `cat $(brew --prefix)/etc/odbcinst.ini`). You should see an entry like `[ODBC Driver 17 for SQL Server]`.
*   The Python code in `sql_schema_exporter/core.py` specifies the driver name in the connection string (`DRIVER={ODBC Driver 17 for SQL Server}`). Ensure this matches the name registered in your `odbcinst.ini`.

**On other systems (Linux/Windows):**

Follow Microsoft's official documentation to install the appropriate ODBC driver for your operating system. Ensure the driver is correctly registered so `pyodbc` can find it.

### 3. System Dependencies (Graphviz - for Lineage)

To generate the visual lineage graph image (`.png`), the Graphviz command-line tools (`dot`, etc.) must be installed and available in your system's PATH.

**On macOS (using Homebrew):**
```bash
brew install graphviz
```

**On Debian/Ubuntu Linux:**
```bash
sudo apt update && sudo apt install graphviz
```

**On Windows:**
Download from the official [Graphviz website](https://graphviz.org/download/) or use a package manager like Chocolatey (`choco install graphviz`). Ensure the `bin` directory of the Graphviz installation is added to your system's PATH environment variable.

*Note: If Graphviz is not installed or found, the tool will still generate the `.gv` (DOT source) file, but it will report an error and skip rendering the image.*

### 4. Python Dependencies

It's recommended to use a Python virtual environment.

```bash
# Create a virtual environment (optional but recommended)
python3 -m venv .venv

# Activate the virtual environment BEFORE installing packages
# On macOS/Linux:
source .venv/bin/activate
# On Windows:
# .venv\Scripts\activate

# Install required Python packages inside the active environment
pip install -r features/requirements.txt
```
The `features/requirements.txt` file includes:
*   `pyodbc`: For connecting to the database.
*   `behave`: For running the BDD tests.
*   `graphviz`: Python interface for creating Graphviz DOT files and rendering them.

## Configuration (for Tests)

The Behave tests (`features/steps/sql_schema_exporter_steps.py`) require connection details for a **test** SQL Server database. These are read from environment variables to avoid hardcoding credentials. Set the following variables in your shell before running `behave`:

*   `TEST_DB_SERVER`: The server name/address of your test SQL Server instance.
*   `TEST_DB_DATABASE`: The name of the test database.
*   `TEST_DB_USER`: (Optional) The username for SQL Server authentication. Leave unset or empty to use Windows/Trusted Authentication.
*   `TEST_DB_PASSWORD`: (Optional) The password for SQL Server authentication. Leave unset if using Windows/Trusted Authentication.

Example (using SQL Authentication):
```bash
export TEST_DB_SERVER="your_test_server.database.windows.net"
export TEST_DB_DATABASE="MyTestDatabase"
export TEST_DB_USER="testuser"
export TEST_DB_PASSWORD="yoursecurepassword"
```

Example (using Windows/Trusted Authentication):
```bash
export TEST_DB_SERVER="localhost\\SQLEXPRESS"
export TEST_DB_DATABASE="MyTestDatabase"
# Leave TEST_DB_USER and TEST_DB_PASSWORD unset
```

## Usage

### Running the Exporter Tool

Execute the tool as a Python module from the **root directory** of the project (the directory containing the `sql_schema_exporter` folder). This ensures Python correctly recognizes the package structure.

```bash
# Make sure you are in the project's root directory
python -m sql_schema_exporter.cli
```

The tool will prompt you interactively for the connection details (server, database, authentication method, credentials).
The extracted schema files will be placed in an output directory named after the database (e.g., `YourDatabaseName/`).
After extracting the schema, the tool will also attempt to query database dependencies and generate a data lineage graph (`YourDatabaseName_lineage.gv` and `YourDatabaseName_lineage.gv.png`) in the same output directory.

### Running the Tests

Ensure your test database environment variables are set (see Configuration section).

```bash
behave
```

This will run all scenarios defined in the `features` directory (including schema export and data lineage tests) against your test database. Test output files are temporarily created in `features/test_output_data/YourTestDatabaseName/` and cleaned up afterwards.
