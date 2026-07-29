from app.auto_integration.schemas import ConnectorManifest


OPEN_FOOD_FACTS = ConnectorManifest(
    slug="open-food-facts",
    name="Open Food Facts",
    description=(
        "Open food-product data for barcode-based nutrition lookups. Audel "
        "stores diary entries and serving calculations locally."
    ),
    base_url="https://world.openfoodfacts.org",
    documentation_url=(
        "https://openfoodfacts.github.io/documentation/docs/Product-Opener/api/"
    ),
    source_url="https://github.com/openfoodfacts/openfoodfacts-server",
    license_name="ODbL 1.0",
    user_agent="Audel/0.1 (personal goal tracker)",
    metadata={
        "source_type": "open_data",
        "category": "nutrition",
        "review_status": "builtin",
    },
    operations=[
        {
            "operation_id": "get_product",
            "name": "Get product by barcode",
            "description": "Retrieve product identity and nutrition data.",
            "path_template": "/api/v3/product/{barcode}",
            "path_parameters": ["barcode"],
            "fixed_query": {
                "fields": (
                    "code,product_name,brands,serving_size,serving_quantity,"
                    "nutriments"
                )
            },
            "input_schema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "barcode": {
                        "type": "string",
                        "pattern": "^[0-9]{8,14}$",
                    }
                },
                "required": ["barcode"],
                "additionalProperties": False,
            },
            "result_mapping": {
                "barcode": "/product/code",
                "name": "/product/product_name",
                "brand": "/product/brands",
                "serving_size": "/product/serving_size",
                "serving_quantity": "/product/serving_quantity",
                "calories_per_100g": (
                    "/product/nutriments/energy-kcal_100g"
                ),
                "calories_per_serving": (
                    "/product/nutriments/energy-kcal_serving"
                ),
                "protein_per_100g": "/product/nutriments/proteins_100g",
                "carbs_per_100g": "/product/nutriments/carbohydrates_100g",
                "fat_per_100g": "/product/nutriments/fat_100g",
            },
        }
    ],
)

BUILTIN_CONNECTORS = (OPEN_FOOD_FACTS,)
