# Extend API — Tokenburner Context

This context is loaded by `tokenburner extend`. It guides you through adding new API resources.

## Overview

To add a new resource (e.g., "products"), you need:
1. A migration SQL file for the new table
2. Routes in `main.py` following the CRUD pattern
3. OAS3 docstrings so Swagger UI auto-generates docs
4. Deploy and smoke test

## Step 1: Create a Migration

Create `migrations/<next_number>_<name>.sql`:

```sql
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    price REAL NOT NULL,
    account_id INTEGER REFERENCES accounts(id),
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);
```

**SQLite compatibility rules** (dev mode uses SQLite-on-S3):
- Use `INTEGER PRIMARY KEY AUTOINCREMENT` not `SERIAL`
- Use `TEXT` not `TIMESTAMPTZ` for timestamps
- Use `datetime('now')` not `now()` for defaults
- Use `INTEGER` not `BOOLEAN` for booleans (0/1)
- The `db.py` layer handles translation for Postgres in full stack mode

Check the current migration count:
```bash
ls product-template/migrations/
```

## Step 2: Add Routes to `main.py`

Follow the existing CRUD pattern:

```python
# ─── Products CRUD ──────────────────────────────────────

@app.route("/api/products", methods=["GET"])
@require_auth
def list_products():
    """List all products.
    ---
    tags: [Products]
    responses:
      200:
        description: Array of products
    """
    return jsonify(query("SELECT id, name, price, account_id, active, created_at FROM products ORDER BY id"))


@app.route("/api/products/<int:product_id>", methods=["GET"])
@require_auth
def get_product(product_id):
    """Get product by ID.
    ---
    tags: [Products]
    parameters:
      - name: product_id
        in: path
        required: true
        schema:
          type: integer
    responses:
      200:
        description: Product object
      404:
        description: Not found
    """
    rows = query("SELECT id, name, price, account_id, active, created_at FROM products WHERE id = %s", (product_id,))
    if not rows:
        return jsonify({"error": "Product not found"}), 404
    return jsonify(rows[0])


@app.route("/api/products", methods=["POST"])
@require_write
def create_product():
    """Create a product.
    ---
    tags: [Products]
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            required: [name, price, account_id]
            properties:
              name:
                type: string
              price:
                type: number
              account_id:
                type: integer
    responses:
      201:
        description: Created product
      400:
        description: Validation error
    """
    data = request.get_json()
    for field in ("name", "price", "account_id"):
        if not data or data.get(field) is None:
            return jsonify({"error": f"{field} required"}), 400
    execute(
        "INSERT INTO products (name, price, account_id) VALUES (%s, %s, %s)",
        (data["name"], data["price"], data["account_id"]),
    )
    rows = query("SELECT id, name, price, account_id, active, created_at FROM products WHERE name = %s", (data["name"],))
    return jsonify(rows[0]), 201


@app.route("/api/products/<int:product_id>", methods=["PUT"])
@require_write
def update_product(product_id):
    """Update a product.
    ---
    tags: [Products]
    parameters:
      - name: product_id
        in: path
        required: true
        schema:
          type: integer
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            properties:
              name:
                type: string
              price:
                type: number
              active:
                type: boolean
    responses:
      200:
        description: Updated product
      404:
        description: Not found
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    sets, vals = [], []
    for field in ("name", "price", "active"):
        if field in data:
            sets.append(f"{field} = %s")
            vals.append(data[field])
    if not sets:
        return jsonify({"error": "No fields to update"}), 400
    vals.append(product_id)
    execute(f"UPDATE products SET {', '.join(sets)} WHERE id = %s", tuple(vals))
    rows = query("SELECT id, name, price, account_id, active, created_at FROM products WHERE id = %s", (product_id,))
    if not rows:
        return jsonify({"error": "Product not found"}), 404
    return jsonify(rows[0])
```

### Route Pattern Rules

- `@require_auth` for GET (read) — needs any valid API key
- `@require_write` for POST/PUT (write) — needs API key with "write" permission
- Return `jsonify(rows)` for lists, `jsonify(rows[0])` for single items
- POST returns 201, PUT returns 200
- Missing records return 404 with `{"error": "... not found"}`
- Validation errors return 400 with `{"error": "... required"}`
- Use parameterized queries with `%s` — `db.py` translates to `?` for SQLite

### OAS3 Docstring Rules (IMPORTANT)

We use OpenAPI 3.0.3, NOT Swagger 2.0. Common mistakes to avoid:

| Wrong (Swagger 2.0) | Right (OAS3) |
|---------------------|--------------|
| `type: integer` on path param | `schema:` then `type: integer` nested inside |
| `parameters:` with `in: body` | `requestBody:` with `content: application/json:` |
| Missing content type | Always include `content: application/json: schema:` |

Missing `content: application/json:` causes **415 Unsupported Media Type** in Swagger UI.

## Step 3: Deploy

```bash
cd product-template/cdk
AWS_PROFILE=<profile> cdk deploy -c dev_mode=true -c product_name=<product_name>
```

Lambda updates in ~25 seconds. New routes appear in Swagger UI automatically.

## Step 4: Smoke Test

Run POST/GET/PUT curls against the new endpoints to verify they work before telling the user. Always test writes — don't just check that the routes exist.

## Step 5: Update Context

After adding new routes, update `tokenburner.md`:
- Add new table to the database section
- Add new routes to the API section
- Update migration count
- Update "What's Built" checklist
