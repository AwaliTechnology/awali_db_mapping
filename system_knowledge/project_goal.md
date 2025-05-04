# Project Goal: SQL Server Schema Exporter

The primary objective of this project is to create a tool that can connect to a Microsoft SQL Server database and extract the definitions of various database objects. Specifically, we want to retrieve the source code or definition for:

*   Stored Procedures
*   Views
*   Table Definitions (including columns, data types, constraints, indexes, etc.)

This extraction should be performed using standard SQL queries against the database's system catalog views (e.g., `INFORMATION_SCHEMA` or `sys` objects).

Once extracted, the tool should organize these definitions into a structured directory hierarchy on the local filesystem. A potential structure could be:

```
output_directory/
├── sprocs/
│   ├── schema1.proc1.sql
│   ├── schema2.proc2.sql
│   └── ...
├── views/
│   ├── schema1.view1.sql
│   ├── schema2.view2.sql
│   └── ...
└── tables/
    ├── schema1.table1.sql
    ├── schema2.table2.sql
    └── ...
```

Each `.sql` file should contain the `CREATE` statement or equivalent definition for the corresponding database object.

This tool will facilitate:

*   Version controlling the database schema.
*   Easier code reviews of schema changes.
*   Offline browsing and searching of database object definitions.
*   Potentially recreating the schema in another environment (though this might require additional handling for dependencies and ordering).

This project will be developed using a Behavior-Driven Development (BDD) approach, utilizing the Behave framework for defining and testing features.
