from flask import Flask, jsonify, request
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import psycopg2
import psycopg2.extras
import os
import socket
import time

app = Flask(__name__)

REQUEST_COUNT = Counter('app_requests_total', 'Total request count', ['endpoint', 'method', 'status'])
REQUEST_LATENCY = Histogram('app_request_latency_seconds', 'Request latency', ['endpoint'])

def get_db():
    return psycopg2.connect(
        host=os.environ['DB_HOST'],
        database=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD']
    )

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS items (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

@app.before_request
def before_request():
    request.start_time = time.time()

@app.after_request
def after_request(response):
    latency = time.time() - request.start_time
    REQUEST_LATENCY.labels(endpoint=request.path).observe(latency)
    REQUEST_COUNT.labels(endpoint=request.path, method=request.method, status=response.status_code).inc()
    return response

@app.route('/health')
def health():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT 1')
        cur.close()
        conn.close()
        return jsonify({'status': 'ok', 'host': socket.gethostname()})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/items', methods=['GET'])
def get_items():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute('SELECT * FROM items ORDER BY created_at DESC')
    items = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(list(items))

@app.route('/items/<int:item_id>', methods=['GET'])
def get_item(item_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute('SELECT * FROM items WHERE id = %s', (item_id,))
    item = cur.fetchone()
    cur.close()
    conn.close()
    if item is None:
        return jsonify({'error': 'Item not found'}), 404
    return jsonify(dict(item))

@app.route('/items', methods=['POST'])
def create_item():
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({'error': 'name is required'}), 400
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        'INSERT INTO items (name, description) VALUES (%s, %s) RETURNING *',
        (data['name'], data.get('description', ''))
    )
    item = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(dict(item)), 201

@app.route('/items/<int:item_id>', methods=['PUT'])
def update_item(item_id):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute('SELECT * FROM items WHERE id = %s', (item_id,))
    if cur.fetchone() is None:
        cur.close()
        conn.close()
        return jsonify({'error': 'Item not found'}), 404
    cur.execute(
        'UPDATE items SET name = COALESCE(%s, name), description = COALESCE(%s, description) WHERE id = %s RETURNING *',
        (data.get('name'), data.get('description'), item_id)
    )
    item = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(dict(item))

@app.route('/items/<int:item_id>', methods=['DELETE'])
def delete_item(item_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM items WHERE id = %s', (item_id,))
    if cur.fetchone() is None:
        cur.close()
        conn.close()
        return jsonify({'error': 'Item not found'}), 404
    cur.execute('DELETE FROM items WHERE id = %s', (item_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'message': f'Item {item_id} deleted'})

@app.route('/metrics')
def metrics():
    return generate_latest(), 200, {'Content-Type': CONTENT_TYPE_LATEST}

with app.app_context():
    try:
        init_db()
    except Exception:
        pass

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)