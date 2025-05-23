# Feature file for the SQL Server Schema Exporter

Feature: Export SQL Server Schema Objects to Files

  As a developer or DBA
  I want to extract definitions of stored procedures, views, and tables from a SQL Server database
  So that I can store them as individual files in a structured directory layout for version control and review.

  Scenario: Successfully connect and extract objects via interactive prompts
    Given the target output directory is empty or does not exist
    When the schema extraction tool is run
    And the user is prompted for connection details (server, database, username, password)
    And the user provides valid connection details interactively
    Then the tool should connect to the database successfully
    And directories named "sprocs", "views", and "tables" should be created in the output directory
    And SQL files corresponding to the stored procedures in the database should exist in the "sprocs" directory
    And SQL files corresponding to the views in the database should exist in the "views" directory
    And SQL files corresponding to the tables in the database should exist in the "tables" directory
    # Further steps could verify file content, naming conventions, etc.

  Scenario: Handle connection failure via interactive prompts
    Given the target output directory is empty or does not exist
    When the schema extraction tool is run
    And the user is prompted for connection details (server, database, username, password)
    And the user provides invalid connection details interactively
    Then the tool should report a connection error
    And no output directories or files should be created

  # Add more scenarios for specific edge cases, error handling, different object types, etc.
