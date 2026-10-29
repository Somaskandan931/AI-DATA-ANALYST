from ai_data_analyst.sql_agent.contracts import (
    ColumnSchema,
    SchemaSnapshot,
    TableSchema,
)
from ai_data_analyst.sql_agent.ollama_generator import OllamaSQLGenerator

schema = SchemaSnapshot(
    tables=(
        TableSchema(
            name="customers",
            columns=(
                ColumnSchema(name="id", declared_type="INTEGER", primary_key=True),
                ColumnSchema(name="name", declared_type="TEXT"),
                ColumnSchema(name="city", declared_type="TEXT"),
            ),
        ),
    )
)

generator = OllamaSQLGenerator()

candidate = generator.generate(
    question="Show all customers from Chennai",
    schema=schema,
)

print("\nGenerated SQL:")
print(candidate.sql)
