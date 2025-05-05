# Feature file for Data Lineage Generation

Feature: Generate Data Lineage Map

  As a developer or DBA
  I want to generate a data lineage map based on database dependencies
  So that I can visualize relationships between tables, views, and procedures.

  Background: Basic Setup
    Given a connection configuration for a SQL Server database is available

  Scenario: Successfully generate lineage map
    Given the Graphviz system executable is found
    When the lineage generation process is run for the database
    Then the tool should query database dependencies successfully
    And a lineage graph DOT file named "<database_name>_lineage.gv" should be created in the output directory
    And a rendered lineage graph image named "<database_name>_lineage.gv.png" should be created in the output directory

  Scenario: Handle connection failure during dependency lookup
    Given an invalid connection configuration for a SQL Server database is used for lineage
    When the lineage generation process is run for the database
    Then the tool should report a connection error during dependency lookup
    And no lineage graph DOT file should be created
    And no rendered lineage graph image should be created

  Scenario: Handle missing Graphviz executable for rendering
    Given the Graphviz system executable is not found
    When the lineage generation process is run for the database
    Then the tool should query database dependencies successfully
    And a lineage graph DOT file named "<database_name>_lineage.gv" should be created in the output directory
    And the tool should report an error during graph rendering
    And no rendered lineage graph image should be created
