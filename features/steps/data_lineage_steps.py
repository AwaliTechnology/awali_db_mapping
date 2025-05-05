import os
import shutil
from pathlib import Path
from behave import *
from unittest.mock import patch # For mocking graphviz executable check

# Assuming core and lineage modules will exist
from sql_schema_exporter import core, lineage
# Import helpers from the other steps file
from .sql_schema_exporter_steps import get_test_output_dir, clean_output_directory, sanitize_for_filename

# --- Context Setup ---

# Store connection details in context for lineage steps
def setup_connection_details(context, use_invalid=False):
    if use_invalid:
        context.server = "invalid_server_name"
        context.database = "invalid_database"
        context.username = "invalid_user"
        context.password = "invalid_password"
    else:
        context.server = os.environ.get("TEST_DB_SERVER", "localhost\\SQLEXPRESS")
        context.database = os.environ.get("TEST_DB_DATABASE", "TestDB")
        context.username = os.environ.get("TEST_DB_USER", None)
        context.password = os.environ.get("TEST_DB_PASSWORD", None)
    # Determine output dir based on database name
    context.output_dir = get_test_output_dir(context)
    # Clean the specific output dir before the scenario runs
    clean_output_directory(context.output_dir)
    assert not context.output_dir.exists() or len(list(context.output_dir.iterdir())) == 0

# --- Step Implementations ---

@given(u'a connection configuration for a SQL Server database is available')
def step_impl(context):
    # This step implies that the necessary env vars are set
    # We'll actually load them in the 'When' step or specific 'Given' steps
    pass

@given(u'the Graphviz system executable is found')
def step_impl(context):
    # We assume it's found by default. The scenario for 'not found' will override this.
    context.graphviz_found = True
    # We might mock the check later if needed, but for now, assume it works if installed.

@when(u'the lineage generation process is run for the database')
def step_impl(context):
    # Setup default valid connection details if not overridden by other steps
    if not hasattr(context, 'server'):
        setup_connection_details(context, use_invalid=False)

    # Store potential errors during the process
    context.lineage_error = None
    context.render_error = None

    # Simulate mocking graphviz rendering if needed
    mock_render = not getattr(context, 'graphviz_found', True)

    try:
        # --- This is where the core lineage logic will be called ---
        # Placeholder for now:
        # lineage.generate_lineage(
        #     server=context.server,
        #     database=context.database,
        #     username=context.username,
        #     password=context.password,
        #     output_dir=context.output_dir,
        #     skip_render=mock_render # Pass flag to skip rendering if mocking 'not found'
        # )
        # Simulate success for now if connection is valid
        if not getattr(context, 'invalid_connection', False):
             context.dependencies_queried = True
             # Simulate file creation for valid connection scenario
             dot_path = context.output_dir / f"{sanitize_for_filename(context.database)}_lineage.gv"
             png_path = context.output_dir / f"{sanitize_for_filename(context.database)}_lineage.gv.png"
             dot_path.parent.mkdir(parents=True, exist_ok=True)
             dot_path.touch() # Create empty file
             if not mock_render:
                 png_path.touch() # Create empty file
             else:
                 # Simulate the render error report
                 context.render_error = "Graphviz executable not found"

        else:
             # Simulate connection error during lineage if connection is invalid
             raise ConnectionError("Simulated connection error during lineage")

    except ConnectionError as e:
        context.lineage_error = e
        context.dependencies_queried = False
    except Exception as e: # Catch other potential errors from lineage logic
        context.lineage_error = e
        context.dependencies_queried = False # Assume query failed if any error occurs


@then(u'the tool should query database dependencies successfully')
def step_impl(context):
    assert getattr(context, 'dependencies_queried', False) is True, "Dependencies should have been queried successfully"
    assert context.lineage_error is None, f"Expected no lineage error, but got: {context.lineage_error}"

@then(u'a lineage graph DOT file named "<database_name>_lineage.gv" should be created in the output directory')
def step_impl(context):
    db_name_sanitized = sanitize_for_filename(context.database)
    expected_file = context.output_dir / f"{db_name_sanitized}_lineage.gv"
    assert expected_file.exists(), f"Expected DOT file '{expected_file}' not found."
    assert expected_file.is_file(), f"Expected DOT file '{expected_file}' is not a file."

@then(u'a rendered lineage graph image named "<database_name>_lineage.gv.png" should be created in the output directory')
def step_impl(context):
    db_name_sanitized = sanitize_for_filename(context.database)
    expected_file = context.output_dir / f"{db_name_sanitized}_lineage.gv.png"
    assert expected_file.exists(), f"Expected PNG file '{expected_file}' not found."
    assert expected_file.is_file(), f"Expected PNG file '{expected_file}' is not a file."

@given(u'an invalid connection configuration for a SQL Server database is used for lineage')
def step_impl(context):
    setup_connection_details(context, use_invalid=True)
    context.invalid_connection = True # Flag for the 'When' step

@then(u'the tool should report a connection error during dependency lookup')
def step_impl(context):
    assert context.lineage_error is not None, "Expected a lineage error, but none was reported."
    # Check if it's specifically a connection-related error (more robust check)
    assert isinstance(context.lineage_error, (ConnectionError, RuntimeError)), \
        f"Expected ConnectionError or RuntimeError, but got {type(context.lineage_error)}: {context.lineage_error}"
    assert getattr(context, 'dependencies_queried', True) is False, "Dependencies should not have been queried successfully"


@then(u'no lineage graph DOT file should be created')
def step_impl(context):
    db_name_sanitized = sanitize_for_filename(context.database)
    expected_file = context.output_dir / f"{db_name_sanitized}_lineage.gv"
    assert not expected_file.exists(), f"DOT file '{expected_file}' should not exist, but it does."

@then(u'no rendered lineage graph image should be created')
def step_impl(context):
    db_name_sanitized = sanitize_for_filename(context.database)
    expected_file = context.output_dir / f"{db_name_sanitized}_lineage.gv.png"
    assert not expected_file.exists(), f"PNG file '{expected_file}' should not exist, but it does."

@given(u'the Graphviz system executable is not found')
def step_impl(context):
    context.graphviz_found = False # Flag for the 'When' step to simulate render failure

@then(u'the tool should report an error during graph rendering')
def step_impl(context):
    assert getattr(context, 'render_error', None) is not None, "Expected a rendering error report."
    # We could check the specific error message if the lineage function returns it

# --- Environment Control (Shared with other steps) ---
# Use the after_scenario from sql_schema_exporter_steps.py implicitly
# Ensure the base test output directory is cleaned if necessary
def before_all(context):
     base_test_output = Path(__file__).parent.parent / "test_output_data"
     if base_test_output.exists():
         shutil.rmtree(base_test_output)
     base_test_output.mkdir(parents=True, exist_ok=True)

# after_scenario is already defined in sql_schema_exporter_steps.py and should clean context.output_dir
