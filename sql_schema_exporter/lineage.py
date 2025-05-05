import logging
import os # Import the os module
import pyodbc
from pathlib import Path
from graphviz import Digraph
from graphviz.backend.execute import ExecutableNotFound

# Import connection function from core
from .core import get_db_connection

# Setup logging (consistent with other modules)
# Use getLogger to avoid adding multiple handlers if run multiple times
log = logging.getLogger(__name__)
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# --- Dependency Query ---
def fetch_dependencies(conn):
    """Queries sys.sql_expression_dependencies to find object relationships."""
    cursor = conn.cursor()
    dependencies = []
    # Query optimized slightly: Use DISTINCT, filter types more effectively
    query = """
    WITH ObjectInfo AS (
        SELECT schema_id, object_id, name, type_desc
        FROM sys.objects
        WHERE type IN ('U', 'V', 'P', 'IF', 'FN', 'TF') -- User Tables, Views, Procs, Functions
    )
    SELECT DISTINCT -- Use DISTINCT to avoid duplicate edges for multi-column dependencies
        referencing_schema_name = SCHEMA_NAME(oi_ref.schema_id),
        referencing_object_name = oi_ref.name,
        referencing_object_type = oi_ref.type_desc,
        referenced_schema_name = ISNULL(sed.referenced_schema_name, SCHEMA_NAME(oi_target.schema_id)), -- Use target object schema if available
        referenced_object_name = sed.referenced_entity_name,
        referenced_object_type = oi_target.type_desc
    FROM
        sys.sql_expression_dependencies sed
    JOIN
        ObjectInfo oi_ref ON sed.referencing_id = oi_ref.object_id
    LEFT JOIN -- Use LEFT JOIN in case referenced object is not in our filtered list (e.g. system object)
         ObjectInfo oi_target ON sed.referenced_id = oi_target.object_id
    WHERE
        sed.referenced_id IS NOT NULL -- Exclude dependencies on built-in types/functions if desired
        AND sed.referenced_database_name IS NULL -- Only include intra-database dependencies for now
        AND sed.referenced_server_name IS NULL
        AND oi_target.object_id IS NOT NULL -- Ensure the referenced object is one we track (Table, View, Proc, Func)
    ORDER BY
        referencing_schema_name,
        referencing_object_name;
    """
    log.info("Fetching object dependencies from sys.sql_expression_dependencies...")
    try:
        cursor.execute(query)
        dependencies = cursor.fetchall()
        log.info(f"Found {len(dependencies)} dependency relationships.")
        return dependencies
    except pyodbc.Error as ex:
        log.error(f"Error fetching dependencies: {ex}")
        # Re-raise as a different exception type? Or return None/empty list?
        # Let's re-raise to signal failure clearly
        raise RuntimeError(f"Failed to fetch dependencies: {ex}") from ex
    finally:
        if cursor:
            cursor.close()

# --- Graph Generation ---
def create_lineage_graph(dependencies, db_name):
    """Creates a graphviz.Digraph object from the list of dependencies."""
    # Sanitize db_name for graph name
    sanitized_db_name = "".join(c if c.isalnum() or c in ('_') else '_' for c in db_name)
    dot = Digraph(
        name=f'{sanitized_db_name}_lineage',
        comment=f'Data Lineage for {db_name}',
        graph_attr={'rankdir': 'LR', 'splines': 'true', 'overlap': 'false', 'nodesep': '0.5', 'ranksep': '1.0'}, # Layout hints
        node_attr={'shape': 'box', 'style': 'filled', 'fontname': 'Helvetica'},
        edge_attr={'color': 'gray50', 'arrowhead': 'open'}
    )

    nodes = set()

    # Define shapes/colors for different object types
    type_styles = {
        'USER_TABLE': {'shape': 'box', 'fillcolor': 'lightblue'},
        'VIEW': {'shape': 'ellipse', 'fillcolor': 'lightgoldenrodyellow'},
        'SQL_STORED_PROCEDURE': {'shape': 'cds', 'fillcolor': 'lightcoral'},
        'SQL_TABLE_VALUED_FUNCTION': {'shape': 'invhouse', 'fillcolor': 'lightgreen'},
        'SQL_SCALAR_FUNCTION': {'shape': 'invhouse', 'fillcolor': 'lightgreen'},
        'SQL_INLINE_TABLE_VALUED_FUNCTION': {'shape': 'invhouse', 'fillcolor': 'lightgreen'},
        # Add more as needed
    }
    default_style = {'shape': 'component', 'fillcolor': 'lightgrey'}

    for dep in dependencies:
        ref_schema, ref_obj, ref_type, target_schema, target_obj, target_type = dep

        # Combine schema and object name for unique node IDs
        # Handle potential None schema for referenced objects if needed
        target_full_name = f"{target_schema or '?'}.{target_obj}"
        ref_full_name = f"{ref_schema}.{ref_obj}"

        # Add nodes if not already added
        if target_full_name not in nodes:
            style = type_styles.get(target_type, default_style)
            dot.node(target_full_name, label=f"{target_schema}.\\n{target_obj}", **style)
            nodes.add(target_full_name)
        if ref_full_name not in nodes:
            style = type_styles.get(ref_type, default_style)
            dot.node(ref_full_name, label=f"{ref_schema}.\\n{ref_obj}", **style)
            nodes.add(ref_full_name)

        # Add edge (dependency: target -> referencing object)
        dot.edge(target_full_name, ref_full_name)

    return dot

# --- Main Orchestration Function ---
def generate_lineage(server, database, username, password, output_dir, skip_render=False):
    """Fetches dependencies, creates DOT graph, and optionally renders it."""
    conn = None
    dependencies_fetched = False
    dot_file_created = False
    render_error_message = None

    try:
        conn = get_db_connection(server, database, username, password) # Use shared connection logic
        dependencies = fetch_dependencies(conn)
        dependencies_fetched = True

        if not dependencies:
            log.warning("No dependencies found to generate lineage graph.")
            return dependencies_fetched, dot_file_created, render_error_message # Return status

        # Create graph object
        dot_graph = create_lineage_graph(dependencies, database)

        # Define output paths
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True) # Ensure output dir exists
        # Sanitize db name for filename
        sanitized_db_name = "".join(c if c.isalnum() or c in ('_') else '_' for c in database)
        base_filename = output_path / f"{sanitized_db_name}_lineage"
        dot_filename = base_filename.with_suffix(".gv")

        # Save DOT file
        try:
            dot_graph.save(filename=str(dot_filename))
            log.info(f"Lineage DOT graph saved to {dot_filename}")
            dot_file_created = True
        except IOError as e:
            log.error(f"Failed to save DOT file {dot_filename}: {e}")
            # Continue to attempt rendering if requested, but report DOT save failure later?
            # For now, let's stop if DOT save fails.
            raise RuntimeError(f"Failed to save DOT file: {e}") from e

        # Render graph (optional)
        if not skip_render:
            try:
                # Render to PNG (default format)
                rendered_path = dot_graph.render(filename=str(dot_filename), view=False, cleanup=True) # cleanup removes dot file after render
                # Re-save the dot file if cleanup=True removed it
                if not dot_filename.exists():
                     dot_graph.save(filename=str(dot_filename))
                log.info(f"Lineage graph rendered to {rendered_path}")
            except ExecutableNotFound as e:
                render_error_message = f"Graphviz executable not found. Cannot render graph. Please install Graphviz. Error: {e}"
                log.error(render_error_message)
            except Exception as e: # Catch other rendering errors
                render_error_message = f"An error occurred during graph rendering: {e}"
                log.error(render_error_message, exc_info=True)

    except (ConnectionError, RuntimeError, pyodbc.Error) as e:
        # Catch connection errors or dependency fetch errors
        log.error(f"Lineage generation failed: {e}")
        # Ensure dependencies_fetched is False if error occurred during fetch
        if isinstance(e, RuntimeError) and "fetch dependencies" in str(e):
            dependencies_fetched = False
        elif isinstance(e, ConnectionError):
             dependencies_fetched = False
        # Re-raise or handle as needed? For now, just log and return status.
        # Store the error to check in steps?
        # Let's return the status tuple
    finally:
        if conn:
            conn.close()
            log.debug("Lineage database connection closed.")

    return dependencies_fetched, dot_file_created, render_error_message

# Example usage (if run directly)
if __name__ == '__main__':
    # Replace with your details for direct testing
    # Make sure to set environment variables or replace placeholders
    test_server = os.environ.get("TEST_DB_SERVER", "your_server")
    test_db = os.environ.get("TEST_DB_DATABASE", "your_db")
    test_user = os.environ.get("TEST_DB_USER", None) # None for Windows Auth
    test_pass = os.environ.get("TEST_DB_PASSWORD", None) # None for Windows Auth
    test_output = Path(f"{test_db}_lineage_output")

    print(f"Attempting lineage generation for {test_server}/{test_db}...")
    generate_lineage(test_server, test_db, test_user, test_pass, test_output)
    print(f"Check output in {test_output.resolve()}")
