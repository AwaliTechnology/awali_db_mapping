import logging
import os
import pyodbc
import re # For cleaning identifiers
from pathlib import Path
from graphviz import Digraph
from graphviz.backend.execute import ExecutableNotFound
import sqlparse # Import sqlparse

# Import connection function from core
from .core import get_db_connection

# Setup logging (consistent with other modules)
# Use getLogger to avoid adding multiple handlers if run multiple times
log = logging.getLogger(__name__)
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# --- SQL Parsing Helper ---

def _parse_sql_for_io(sql_definition):
    """
    Uses sqlparse to perform basic analysis of SQL definition to find potential
    source (FROM/JOIN) and target (INSERT/UPDATE/MERGE/DELETE) objects.
    Returns a dictionary {'sources': set(), 'targets': set()}.
    This is a heuristic approach and may not be perfectly accurate.
    """
    sources = set()
    targets = set()
    if not sql_definition:
        return {'sources': sources, 'targets': targets}

    # Remove comments to simplify parsing (basic block comments /* */ and line comments --)
    sql_definition = re.sub(r'/\*.*?\*/', '', sql_definition, flags=re.DOTALL)
    sql_definition = re.sub(r'--.*?\n', '', sql_definition)

    try:
        parsed = sqlparse.parse(sql_definition)
        for stmt in parsed:
            # Flatten the token list for easier iteration
            tokens = list(stmt.flatten())
            i = 0
            while i < len(tokens):
                token = tokens[i]

                # Identify Targets (INSERT/UPDATE/MERGE/DELETE)
                if token.ttype is sqlparse.tokens.Keyword.DML:
                    dml_keyword = token.value.upper()
                    if dml_keyword in ('INSERT', 'UPDATE', 'MERGE', 'DELETE'):
                        # Look ahead for the target table/view name
                        j = i + 1
                        target_name_parts = []
                        while j < len(tokens):
                            next_token = tokens[j]
                            # Skip whitespace, INTO/FROM keywords after DML
                            if next_token.is_whitespace or next_token.value.upper() in ('INTO', 'FROM'):
                                j += 1
                                continue
                            # Found an identifier (potentially schema.table or just table)
                            if next_token.ttype is sqlparse.tokens.Name or isinstance(next_token, sqlparse.sql.Identifier):
                                target_name_parts.append(next_token.value.strip('[]"`'))
                                # Check if the *next* token is a dot (for schema.table)
                                k = j + 1
                                if k < len(tokens) and tokens[k].ttype is sqlparse.tokens.Punctuation and tokens[k].value == '.':
                                    # Look for the object name after the dot
                                    l = k + 1
                                    if l < len(tokens) and (tokens[l].ttype is sqlparse.tokens.Name or isinstance(tokens[l], sqlparse.sql.Identifier)):
                                        target_name_parts.append(tokens[l].value.strip('[]"`'))
                                        j = l # Advance main loop past the object name
                                    else:
                                        # Malformed schema.object? Use what we have.
                                        pass
                                # Add the combined name (or single part name)
                                targets.add('.'.join(target_name_parts))
                                break # Found target for this DML, stop looking ahead
                            else:
                                # Didn't find an identifier immediately after DML keyword (or INTO/FROM)
                                break
                            j += 1
                        # Advance main loop counter past the DML keyword and potential target
                        i = j

                # Identify Sources (FROM/JOIN)
                elif token.ttype is sqlparse.tokens.Keyword and token.value.upper() in ('FROM', 'JOIN'):
                    # Look ahead for the source table/view name
                    j = i + 1
                    source_name_parts = []
                    while j < len(tokens):
                        next_token = tokens[j]
                        if next_token.is_whitespace:
                            j += 1
                            continue
                        # Found an identifier
                        if next_token.ttype is sqlparse.tokens.Name or isinstance(next_token, sqlparse.sql.Identifier):
                            source_name_parts.append(next_token.value.strip('[]"`'))
                            # Check for schema.table pattern
                            k = j + 1
                            if k < len(tokens) and tokens[k].ttype is sqlparse.tokens.Punctuation and tokens[k].value == '.':
                                l = k + 1
                                if l < len(tokens) and (tokens[l].ttype is sqlparse.tokens.Name or isinstance(tokens[l], sqlparse.sql.Identifier)):
                                    source_name_parts.append(tokens[l].value.strip('[]"`'))
                                    j = l
                                else:
                                    pass # Malformed
                            # Add the source name (schema.object or object)
                            # Ignore common table expressions (CTEs) if they appear here - basic check
                            potential_source = '.'.join(source_name_parts)
                            # Very basic check: ignore if it looks like a variable or temp table
                            if not potential_source.startswith(('#', '@')):
                                sources.add(potential_source)
                            # We might find multiple sources after FROM/JOIN, but stop after the first identifier found
                            break
                        else:
                            # Didn't find an identifier immediately after FROM/JOIN
                            break
                        j += 1
                    i = j # Advance main loop counter

                i += 1 # Move to the next token
    except Exception as e:
        log.warning(f"SQL parsing failed for a definition: {e}", exc_info=True) # Log parsing errors

    # Clean up names (remove potential database prefixes if present, assume current db)
    clean_sources = {re.sub(r'^[^.]+\.(?=[^.]+\.)', '', s) for s in sources} # db.schema.obj -> schema.obj
    clean_targets = {re.sub(r'^[^.]+\.(?=[^.]+\.)', '', t) for t in targets} # db.schema.obj -> schema.obj

    # Further cleanup: ensure format is schema.object or just object
    final_sources = set()
    for s in clean_sources:
        parts = s.split('.')
        if len(parts) > 2: # e.g. server.db.schema.obj - unlikely but possible
             final_sources.add(f"{parts[-2]}.{parts[-1]}")
        else:
             final_sources.add(s)

    final_targets = set()
    for t in clean_targets:
        parts = t.split('.')
        if len(parts) > 2:
             final_targets.add(f"{parts[-2]}.{parts[-1]}")
        else:
             final_targets.add(t)


    return {'sources': final_sources, 'targets': final_targets}


# --- Dependency Query ---
def fetch_dependencies(conn):
    """
    Queries sys.sql_expression_dependencies and also fetches definitions
    of referencing procedures/functions to parse for source/target relationships.
    Returns a dictionary containing 'direct_deps' and 'parsed_flow'.
    """
    cursor = conn.cursor()
    direct_dependencies = []
    parsed_flow_details = {} # Store {proc_name: {'sources': set(), 'targets': set()}}

    # Query to get dependencies AND the definition of the referencing object if it's a proc/func
    query = """
    WITH ObjectInfo AS (
        SELECT schema_id, object_id, name, type, type_desc
        FROM sys.objects
        WHERE type IN ('U', 'V', 'P', 'IF', 'FN', 'TF') -- User Tables, Views, Procs, Functions
    )
    SELECT DISTINCT
        referencing_schema_name = SCHEMA_NAME(oi_ref.schema_id),
        referencing_object_name = oi_ref.name,
        referencing_object_type = oi_ref.type_desc,
        referenced_schema_name = ISNULL(sed.referenced_schema_name, SCHEMA_NAME(oi_target.schema_id)),
        referenced_object_name = sed.referenced_entity_name,
        referenced_object_type = oi_target.type_desc,
        referencing_object_definition = CASE
                                            WHEN oi_ref.type IN ('P', 'IF', 'FN', 'TF') -- Only get definition for procs/funcs
                                            THEN OBJECT_DEFINITION(oi_ref.object_id)
                                            ELSE NULL
                                        END
    FROM
        sys.sql_expression_dependencies sed
    JOIN
        ObjectInfo oi_ref ON sed.referencing_id = oi_ref.object_id
    LEFT JOIN
         ObjectInfo oi_target ON sed.referenced_id = oi_target.object_id
    WHERE
        sed.referenced_id IS NOT NULL
        AND sed.referenced_database_name IS NULL
        AND sed.referenced_server_name IS NULL
        AND oi_target.object_id IS NOT NULL
    ORDER BY
        referencing_schema_name,
        referencing_object_name;
    """
    log.info("Fetching object dependencies and definitions for parsing...")
    try:
        cursor.execute(query)
        results = cursor.fetchall()
        log.info(f"Found {len(results)} raw dependency relationships.")

        processed_procs = set() # Track procs we've already parsed

        for row in results:
            ref_schema, ref_obj, ref_type, target_schema, target_obj, target_type, ref_def = row

            # Store the direct dependency found via sys.sql_expression_dependencies
            direct_dependencies.append({
                'referencing_schema': ref_schema, 'referencing_object': ref_obj, 'referencing_type': ref_type,
                'referenced_schema': target_schema, 'referenced_object': target_obj, 'referenced_type': target_type
            })

            # If the referencing object is a procedure/function and has a definition, parse it
            ref_full_name = f"{ref_schema}.{ref_obj}"
            if ref_def and ref_type in ('SQL_STORED_PROCEDURE', 'SQL_TABLE_VALUED_FUNCTION', 'SQL_SCALAR_FUNCTION', 'SQL_INLINE_TABLE_VALUED_FUNCTION'):
                if ref_full_name not in processed_procs:
                    log.debug(f"Parsing definition for {ref_full_name}...")
                    io_details = _parse_sql_for_io(ref_def)
                    if io_details['sources'] or io_details['targets']:
                         parsed_flow_details[ref_full_name] = io_details
                         log.debug(f"Parsed IO for {ref_full_name}: Sources={io_details['sources']}, Targets={io_details['targets']}")
                    processed_procs.add(ref_full_name)

        log.info(f"Processed dependencies. Found potential parsed flow for {len(parsed_flow_details)} procedures/functions.")
        return {'direct_deps': direct_dependencies, 'parsed_flow': parsed_flow_details}

    except pyodbc.Error as ex:
        log.error(f"Error fetching dependencies/definitions: {ex}")
        raise RuntimeError(f"Failed to fetch dependencies/definitions: {ex}") from ex
    finally:
        if cursor:
            cursor.close()


# --- Graph Generation ---
def create_lineage_graph(dependency_data, db_name):
    """
    Creates a graphviz.Digraph object using both direct dependencies
    and parsed source/target information for procedures/functions.
    """
    direct_deps = dependency_data.get('direct_deps', [])
    parsed_flow = dependency_data.get('parsed_flow', {})

    # Sanitize db_name for graph name
    sanitized_db_name = "".join(c if c.isalnum() or c in ('_') else '_' for c in db_name)
    dot = Digraph(
        name=f'{sanitized_db_name}_lineage',
        comment=f'Data Lineage for {db_name}',
        graph_attr={'rankdir': 'LR', 'splines': 'true', 'overlap': 'false', 'nodesep': '0.5', 'ranksep': '1.0'}, # Layout hints
        node_attr={'shape': 'box', 'style': 'filled', 'fontname': 'Helvetica'},
        edge_attr={'color': 'gray50', 'arrowhead': 'open'}
    )

    nodes = {} # Store node info: {full_name: {'label': '...', 'style': {...}}}

    # Define shapes/colors for different object types
    type_styles = {
        'USER_TABLE': {'shape': 'box', 'fillcolor': 'lightblue', 'group': 'table'},
        'VIEW': {'shape': 'ellipse', 'fillcolor': 'lightgoldenrodyellow', 'group': 'view'},
        'SQL_STORED_PROCEDURE': {'shape': 'cds', 'fillcolor': 'lightcoral', 'group': 'proc'},
        'SQL_TABLE_VALUED_FUNCTION': {'shape': 'invhouse', 'fillcolor': 'lightgreen', 'group': 'func'},
        'SQL_SCALAR_FUNCTION': {'shape': 'invhouse', 'fillcolor': 'lightgreen', 'group': 'func'},
        'SQL_INLINE_TABLE_VALUED_FUNCTION': {'shape': 'invhouse', 'fillcolor': 'lightgreen', 'group': 'func'},
        # Add more as needed
    }
    default_style = {'shape': 'component', 'fillcolor': 'lightgrey', 'group': 'other'}

    def add_node(full_name, obj_type, schema_name, obj_name):
        """Helper to add node info to the nodes dictionary if not present."""
        if full_name not in nodes:
            style = type_styles.get(obj_type, default_style).copy() # Use copy
            label = f"{schema_name}.\\n{obj_name}" if schema_name else obj_name
            nodes[full_name] = {'label': label, 'style': style}

    # --- Process Direct Dependencies (from sys.sql_expression_dependencies) ---
    # These show fundamental references (e.g., View uses Table, Proc uses View/Table/Func)
    log.info(f"Processing {len(direct_deps)} direct dependencies for graph nodes and basic edges...")
    for dep in direct_deps:
        ref_schema = dep['referencing_schema']
        ref_obj = dep['referencing_object']
        ref_type = dep['referencing_type']
        target_schema = dep['referenced_schema']
        target_obj = dep['referenced_object']
        target_type = dep['referenced_type']

        # Ensure schema is not None for node naming consistency
        ref_schema = ref_schema or 'dbo' # Default schema if None
        target_schema = target_schema or 'dbo'

        ref_full_name = f"{ref_schema}.{ref_obj}"
        target_full_name = f"{target_schema}.{target_obj}"

        # Add nodes involved in this dependency
        add_node(ref_full_name, ref_type, ref_schema, ref_obj)
        add_node(target_full_name, target_type, target_schema, target_obj)

        # Add edge representing the direct dependency: referenced -> referencing
        # We draw it this way because sys.dependencies tells us 'ref' USES 'target'
        dot.edge(target_full_name, ref_full_name, style='dashed', color='grey') # Dashed for basic dependency

    # --- Process Parsed Flow (for Procedures/Functions) ---
    log.info(f"Processing {len(parsed_flow)} parsed procedures/functions for flow edges...")
    for proc_full_name, io_details in parsed_flow.items():
        # Ensure the procedure node itself exists (it should from direct deps, but double-check)
        if proc_full_name not in nodes:
             # This might happen if a proc has no dependencies listed in sys.dependencies
             # but was parsed (e.g., only inserts literal values). Try to add it.
             # We need its type, guess 'SQL_STORED_PROCEDURE' if unknown.
             schema, obj = proc_full_name.split('.', 1) if '.' in proc_full_name else ('dbo', proc_full_name)
             add_node(proc_full_name, 'SQL_STORED_PROCEDURE', schema, obj)
             log.warning(f"Procedure {proc_full_name} was parsed but not found in direct dependencies nodes. Added with default type.")


        # Add edges for parsed sources: source -> procedure
        for source_name in io_details.get('sources', set()):
            # Attempt to resolve schema if missing (assume dbo)
            if '.' not in source_name:
                source_full_name = f"dbo.{source_name}"
            else:
                source_full_name = source_name

            # Add source node if it doesn't exist (might be a table/view not caught by direct deps)
            if source_full_name not in nodes:
                 schema, obj = source_full_name.split('.', 1) if '.' in source_full_name else ('dbo', source_full_name)
                 # Guess type as USER_TABLE if unknown
                 add_node(source_full_name, 'USER_TABLE', schema, obj)
                 log.warning(f"Source '{source_full_name}' from parsed flow for {proc_full_name} not found in nodes. Added with default type 'USER_TABLE'.")

            # Draw edge: source -> proc
            dot.edge(source_full_name, proc_full_name, style='solid', color='darkgreen', arrowhead='normal') # Solid green for read flow

        # Add edges for parsed targets: procedure -> target
        for target_name in io_details.get('targets', set()):
            if '.' not in target_name:
                target_full_name = f"dbo.{target_name}"
            else:
                target_full_name = target_name

            if target_full_name not in nodes:
                 schema, obj = target_full_name.split('.', 1) if '.' in target_full_name else ('dbo', target_full_name)
                 add_node(target_full_name, 'USER_TABLE', schema, obj)
                 log.warning(f"Target '{target_full_name}' from parsed flow for {proc_full_name} not found in nodes. Added with default type 'USER_TABLE'.")

            # Draw edge: proc -> target
            dot.edge(proc_full_name, target_full_name, style='solid', color='darkred', arrowhead='normal') # Solid red for write flow


    # --- Add all collected nodes to the graph ---
    log.info(f"Adding {len(nodes)} unique nodes to the graph...")
    for name, node_info in nodes.items():
        dot.node(name, label=node_info['label'], **node_info['style'])

    log.info("Graph creation complete.")
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
        dependency_data = fetch_dependencies(conn) # Now returns a dict
        dependencies_fetched = True # Assume fetch succeeded if no exception

        if not dependency_data or (not dependency_data.get('direct_deps') and not dependency_data.get('parsed_flow')):
            log.warning("No dependencies or parsed flow found to generate lineage graph.")
            # Still consider dependency fetch successful, but graph might be empty
            return dependencies_fetched, dot_file_created, render_error_message # Return status

        # Create graph object using the combined data
        dot_graph = create_lineage_graph(dependency_data, database)

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
