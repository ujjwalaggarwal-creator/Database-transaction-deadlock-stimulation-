from flask import Flask, render_template, request, jsonify
import mysql.connector

app = Flask(__name__)

# Change YOUR_MYSQL_PASSWORD to your MySQL root password
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "Database@sql05",
    "database": "deadlock_simulator"
}

DATABASE = "deadlock_simulator"


def connect_db():
    return mysql.connector.connect(**DB_CONFIG)


def initialize_database():
    # Create the database if it does not exist
    connection = mysql.connector.connect(**DB_CONFIG)
    cursor = connection.cursor()
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DATABASE}")
    cursor.close()
    connection.close()

    db = connect_db()
    cursor = db.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(50) UNIQUE NOT NULL,
            status VARCHAR(30) DEFAULT 'ACTIVE'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS resources (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(50) UNIQUE NOT NULL,
            holder_id INT NULL,
            FOREIGN KEY (holder_id) REFERENCES transactions(id)
            ON DELETE SET NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS waiting_requests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            transaction_id INT NOT NULL,
            resource_id INT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (transaction_id) REFERENCES transactions(id)
            ON DELETE CASCADE,
            FOREIGN KEY (resource_id) REFERENCES resources(id)
            ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INT AUTO_INCREMENT PRIMARY KEY,
            message VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.commit()
    cursor.close()
    db.close()


def add_log(message):
    db = connect_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO activity_log (message) VALUES (%s)",
        (message,)
    )
    db.commit()
    cursor.close()
    db.close()


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/state")
def get_state():
    db = connect_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM transactions")
    transactions = cursor.fetchall()

    cursor.execute("""
        SELECT resources.*, transactions.name AS holder
        FROM resources
        LEFT JOIN transactions
        ON resources.holder_id = transactions.id
    """)
    resources = cursor.fetchall()

    cursor.execute("""
        SELECT waiting_requests.id,
               transactions.name AS transaction_name,
               resources.name AS resource_name
        FROM waiting_requests
        JOIN transactions ON waiting_requests.transaction_id = transactions.id
        JOIN resources ON waiting_requests.resource_id = resources.id
        ORDER BY waiting_requests.id
    """)
    waiting = cursor.fetchall()

    cursor.execute("""
        SELECT * FROM activity_log ORDER BY id DESC LIMIT 20
    """)
    logs = cursor.fetchall()

    cursor.close()
    db.close()

    return jsonify({
        "transactions": transactions,
        "resources": resources,
        "waiting": waiting,
        "logs": logs
    })


@app.route("/api/transactions", methods=["POST"])
def create_transaction():
    name = request.json.get("name", "").strip()

    if not name:
        return jsonify({"error": "Enter a transaction name"}), 400

    db = connect_db()
    cursor = db.cursor()

    try:
        cursor.execute(
            "INSERT INTO transactions (name) VALUES (%s)",
            (name,)
        )
        db.commit()
        add_log(f"Transaction {name} created")
        return jsonify({"message": "Transaction created"})
    except mysql.connector.IntegrityError:
        return jsonify({"error": "Transaction name already exists"}), 400
    finally:
        cursor.close()
        db.close()


@app.route("/api/resources", methods=["POST"])
def create_resource():
    name = request.json.get("name", "").strip()

    if not name:
        return jsonify({"error": "Enter a resource name"}), 400

    db = connect_db()
    cursor = db.cursor()

    try:
        cursor.execute(
            "INSERT INTO resources (name) VALUES (%s)",
            (name,)
        )
        db.commit()
        add_log(f"Resource {name} created")
        return jsonify({"message": "Resource created"})
    except mysql.connector.IntegrityError:
        return jsonify({"error": "Resource name already exists"}), 400
    finally:
        cursor.close()
        db.close()


@app.route("/api/request", methods=["POST"])
def request_resource():
    transaction_id = request.json.get("transaction_id")
    resource_id = request.json.get("resource_id")

    db = connect_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM transactions WHERE id = %s",
        (transaction_id,)
    )
    transaction = cursor.fetchone()

    cursor.execute(
        "SELECT * FROM resources WHERE id = %s",
        (resource_id,)
    )
    resource = cursor.fetchone()

    if not transaction or not resource:
        cursor.close()
        db.close()
        return jsonify({"error": "Invalid transaction or resource"}), 400

    if transaction["status"] in ("COMMITTED", "ROLLED BACK"):
        cursor.close()
        db.close()
        return jsonify({"error": "This transaction has already finished"}), 400

    if resource["holder_id"] == transaction_id:
        cursor.close()
        db.close()
        return jsonify({"error": "Transaction already holds this resource"}), 400

    if resource["holder_id"] is None:
        cursor.execute(
            "UPDATE resources SET holder_id = %s WHERE id = %s",
            (transaction_id, resource_id)
        )
        cursor.execute(
            "UPDATE transactions SET status = 'ACTIVE' WHERE id = %s",
            (transaction_id,)
        )
        message = f"{transaction['name']} allocated {resource['name']}"
    else:
        cursor.execute("""
            INSERT INTO waiting_requests (transaction_id, resource_id)
            VALUES (%s, %s)
        """, (transaction_id, resource_id))

        cursor.execute(
            "UPDATE transactions SET status = 'WAITING' WHERE id = %s",
            (transaction_id,)
        )
        message = f"{transaction['name']} is waiting for {resource['name']}"

    db.commit()
    cursor.close()
    db.close()

    add_log(message)
    return jsonify({"message": message})


@app.route("/api/finish", methods=["POST"])
def finish_transaction():
    transaction_id = request.json.get("transaction_id")
    action = request.json.get("action")

    if action not in ("COMMITTED", "ROLLED BACK"):
        return jsonify({"error": "Invalid action"}), 400

    db = connect_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM transactions WHERE id = %s",
        (transaction_id,)
    )
    transaction = cursor.fetchone()

    if not transaction:
        cursor.close()
        db.close()
        return jsonify({"error": "Transaction not found"}), 404

    cursor.execute("""
        UPDATE resources SET holder_id = NULL WHERE holder_id = %s
    """, (transaction_id,))

    cursor.execute("""
        DELETE FROM waiting_requests WHERE transaction_id = %s
    """, (transaction_id,))

    cursor.execute(
        "UPDATE transactions SET status = %s WHERE id = %s",
        (action, transaction_id)
    )

    # Give released resources to the earliest waiting transactions
    cursor.execute("""
        SELECT id FROM resources WHERE holder_id IS NULL
    """)
    free_resources = cursor.fetchall()

    for resource in free_resources:
        cursor.execute("""
            SELECT id, transaction_id FROM waiting_requests
            WHERE resource_id = %s
            ORDER BY id LIMIT 1
        """, (resource["id"],))
        waiting = cursor.fetchone()

        if waiting:
            cursor.execute("""
                UPDATE resources SET holder_id = %s WHERE id = %s
            """, (waiting["transaction_id"], resource["id"]))

            cursor.execute("""
                UPDATE transactions SET status = 'ACTIVE' WHERE id = %s
            """, (waiting["transaction_id"],))

            cursor.execute(
                "DELETE FROM waiting_requests WHERE id = %s",
                (waiting["id"],)
            )

    db.commit()
    cursor.close()
    db.close()

    add_log(f"{transaction['name']} {action}")
    return jsonify({"message": f"{transaction['name']} {action}"})


def detect_deadlock():
    db = connect_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT waiting_tx.name AS waiter,
               holder_tx.name AS holder
        FROM waiting_requests w
        JOIN resources r ON w.resource_id = r.id
        JOIN transactions waiting_tx ON w.transaction_id = waiting_tx.id
        JOIN transactions holder_tx ON r.holder_id = holder_tx.id
    """)

    edges = cursor.fetchall()
    cursor.close()
    db.close()

    graph = {}
    for edge in edges:
        graph.setdefault(edge["waiter"], []).append(edge["holder"])

    visited = set()
    path = []
    cycle = []

    def dfs(node):
        if node in path:
            start = path.index(node)
            cycle.extend(path[start:] + [node])
            return True

        if node in visited:
            return False

        visited.add(node)
        path.append(node)

        for neighbour in graph.get(node, []):
            if dfs(neighbour):
                return True

        path.pop()
        return False

    for node in graph:
        if dfs(node):
            break

    return {
        "deadlock": bool(cycle),
        "cycle": cycle,
        "edges": edges
    }


@app.route("/api/detect")
def detect():
    result = detect_deadlock()

    if result["deadlock"]:
        add_log("Deadlock detected: " + " -> ".join(result["cycle"]))
    else:
        add_log("Deadlock detection completed: no deadlock found")

    return jsonify(result)


@app.route("/api/reset", methods=["POST"])
def reset():
    db = connect_db()
    cursor = db.cursor()

    cursor.execute("DELETE FROM waiting_requests")
    cursor.execute("UPDATE resources SET holder_id = NULL")
    cursor.execute("DELETE FROM transactions")
    cursor.execute("DELETE FROM resources")
    cursor.execute("DELETE FROM activity_log")

    db.commit()
    cursor.close()
    db.close()

    return jsonify({"message": "Simulator reset successfully"})
@app.route("/api/accounts", methods=["GET"])
def get_accounts():
    connection = mysql.connector.connect(**DB_CONFIG)
    cursor = connection.cursor(dictionary=True)

    cursor.execute("""
        SELECT account_id, account_number,
               account_holder, balance
        FROM bank_accounts
        ORDER BY account_id
    """)

    accounts = cursor.fetchall()

    cursor.close()
    connection.close()

    return jsonify(accounts)

@app.route("/api/transfer", methods=["POST"])
def transfer_money():
    data = request.get_json()

    sender = data.get("sender")
    receiver = data.get("receiver")
    amount = data.get("amount")

    if not sender or not receiver or sender == receiver:
        return jsonify({"error": "Select two different accounts"}), 400

    try:
        amount = float(amount)
        if amount <= 0:
            return jsonify({"error": "Enter a valid amount"}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount"}), 400

    connection = connect_db()
    cursor = connection.cursor(dictionary=True)

    try:
        connection.start_transaction()

        cursor.execute(
            "SELECT * FROM bank_accounts WHERE account_number = %s FOR UPDATE",
            (sender,)
        )
        sender_account = cursor.fetchone()

        cursor.execute(
            "SELECT * FROM bank_accounts WHERE account_number = %s FOR UPDATE",
            (receiver,)
        )
        receiver_account = cursor.fetchone()

        if not sender_account or not receiver_account:
            connection.rollback()
            return jsonify({"error": "Account not found"}), 404

        if float(sender_account["balance"]) < amount:
            connection.rollback()
            return jsonify({"error": "Insufficient balance"}), 400

        cursor.execute(
            "UPDATE bank_accounts SET balance = balance - %s WHERE account_number = %s",
            (amount, sender)
        )

        cursor.execute(
            "UPDATE bank_accounts SET balance = balance + %s WHERE account_number = %s",
            (amount, receiver)
        )

        connection.commit()

        return jsonify({
            "message": "Transfer successful",
            "amount": amount,
            "sender": sender,
            "receiver": receiver
        })

    except Exception as error:
        connection.rollback()
        return jsonify({"error": str(error)}), 500

    finally:
        cursor.close()
        connection.close()



if __name__ == "__main__":
    initialize_database()
    print("Deadlock Simulator is starting...")
    app.run(debug=True)