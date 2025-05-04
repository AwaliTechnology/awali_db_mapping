import os
import shutil
from pathlib import Path
from behave import *
import re # For sanitization
from sql_schema_exporter import core # Import the core logic

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

def get_test_output_dir(context):
    """Gets the sanitized output directory path based on the test database name."""
    # Ensure context.database is set by the 'provides details' step first
    db_name = getattr(context, 'database', 'default_test_db')
    sanitized_db_name = sanitize_for_filename(db_name)
    # Place it inside a general test output area to keep things tidy
    base_test_output = Path(__file__).parent.parent / "test_output_data"
    return base_test_output / sanitized_db_name

def clean_output_directory(output_dir):
    """Removes the output directory if it exists."""
    if output_dir.exists():
        shutil.rmtree(output_dir)
    # Also ensure the base test output directory exists if we derived the path
    if output_dir.parent.name == "test_output_data":
        output_dir.parent.mkdir(parents=True, exist_ok=True)


# --- Step Implementations ---

@given('the target output directory is empty or does not exist')
def step_impl(context):
    # Output dir depends on the database name, which isn't known yet.
    # We'll determine and clean it in the 'provides details' step or after_scenario.
    # For now, just assert the base test dir exists or can be created.
    base_test_output = Path(__file__).parent.parent / "test_output_data"
    # Clean the whole base dir before feature? Or rely on after_scenario?
    # Let's clean in after_scenario based on context.output_dir
    pass # Defer directory handling

@when('the schema extraction tool is run')
def step_impl(context):
    # In a real test, we'd likely call core.export_schema directly
    # We store the result (True/False) in the context
    # Connection details should come from the context, set by subsequent steps
    # For now, this step doesn't do much until connection details are provided
    pass # Execution happens in the 'provides details' step

@step("the user is prompted for connection details (server, database, username, password)")
def step_impl(context):
    # This step is more descriptive for the feature file.
    # The actual provision of details happens in the next step.
    # We can store placeholder prompts or flags if needed for more complex tests.
    context.prompts_expected = True


@step("the user provides valid connection details interactively")
def step_impl(context):
    # --- !!! IMPORTANT !!! ---
    # For automated testing, DO NOT use real interactive prompts.
    # Instead, simulate the input by setting context variables.
    # These should point to a TEST database you have set up.
    # Replace these with your actual TEST environment details.
    # Consider using environment variables or a secure config for this.
    context.server = os.environ.get("TEST_DB_SERVER", "localhost\\SQLEXPRESS") # Example
    context.database = os.environ.get("TEST_DB_DATABASE", "TestDB")       # Example
    context.username = os.environ.get("TEST_DB_USER", None)              # Example: None for Win Auth
    context.password = os.environ.get("TEST_DB_PASSWORD", None)          # Example: None for Win Auth

    # Determine and clean the output directory based on the database name
    context.output_dir = get_test_output_dir(context)
    clean_output_directory(context.output_dir) # Clean before the run
    assert not context.output_dir.exists()

    # Simulate running the core export function with these details
    context.export_success = core.export_schema(
        context.server,
        context.database,
        context.username,
        context.password,
        context.output_dir # Pass the derived output directory
    )

@step("the user provides invalid connection details interactively")
def step_impl(context):
    # Use deliberately incorrect details to trigger a connection error
    context.server = "invalid_server_name"
    context.database = "invalid_database"
    context.username = "invalid_user"
    context.password = "invalid_password"

    # Determine and clean the output directory based on the database name
    context.output_dir = get_test_output_dir(context)
    clean_output_directory(context.output_dir) # Clean before the run
    assert not context.output_dir.exists()

    # Simulate running the core export function
    context.export_success = core.export_schema(
        context.server,
        context.database,
        context.username,
        context.password,
        context.output_dir # Pass the derived output directory
    )


@then('the tool should connect to the database successfully')
def step_impl(context):
    # The success of the connection is implied if export_success is True
    # core.export_schema handles the connection attempt and logging
    assert getattr(context, 'export_success', False) is True, "Export process should have succeeded"

@then('the tool should report a connection error')
def step_impl(context):
    # If export_schema returned False after providing invalid details, we assume it was a connection error
    # More robust checking could involve capturing logs or specific exceptions if core.py raised them.
    assert getattr(context, 'export_success', True) is False, "Export process should have failed"


@then('directories named "sprocs", "views", and "tables" should be created in the output directory')
def step_impl(context):
    assert context.output_dir.exists(), f"Output directory '{context.output_dir}' does not exist"
    assert (context.output_dir / "sprocs").is_dir(), "sprocs directory not found"
    assert (context.output_dir / "views").is_dir(), "views directory not found"
    assert (context.output_dir / "tables").is_dir(), "tables directory not found"

@then('SQL files corresponding to the stored procedures in the database should exist in the "sprocs" directory')
def step_impl(context):
    sprocs_dir = context.output_dir / "sprocs"
    # Check if at least one .sql file exists. More specific checks depend on the test DB.
    sql_files = list(sprocs_dir.glob("*.sql"))
    # This assertion depends on your TEST database having at least one procedure.
    # Adjust if your test DB might be empty or if you want to check for specific files.
    assert len(sql_files) > 0, f"No .sql files found in {sprocs_dir}. (Ensure test DB has procedures)"

@then('SQL files corresponding to the views in the database should exist in the "views" directory')
def step_impl(context):
    views_dir = context.output_dir / "views"
    sql_files = list(views_dir.glob("*.sql"))
    # Adjust assertion based on your test DB content.
    assert len(sql_files) > 0, f"No .sql files found in {views_dir}. (Ensure test DB has views)"


@then('SQL files corresponding to the tables in the database should exist in the "tables" directory')
def step_impl(context):
    tables_dir = context.output_dir / "tables"
    sql_files = list(tables_dir.glob("*.sql"))
    # Adjust assertion based on your test DB content.
    assert len(sql_files) > 0, f"No .sql files found in {tables_dir}. (Ensure test DB has tables)"


@then('no output directories or files should be created')
def step_impl(context):
    # Check that the base output directory was not created, or if it was, it's empty
    assert not context.output_dir.exists() or len(list(context.output_dir.iterdir())) == 0, \
        f"Output directory '{context.output_dir}' was created or is not empty"


# --- Environment Control ---
def before_feature(context, feature):
    # Optional: Setup tasks before any scenario in this feature runs
    pass

def after_scenario(context, scenario):
    # Clean up the output directory used in the scenario, if it was set
    if hasattr(context, 'output_dir'):
        clean_output_directory(context.output_dir)
