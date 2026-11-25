let lastDeadlockCycle = []; 
async function api(url, method = "GET", data = null) {
    const options = { method };

    if (data) {
        options.headers = { "Content-Type": "application/json" };
        options.body = JSON.stringify(data);
    }

    const response = await fetch(url, options);
    const result = await response.json();

    if (!response.ok) {
        throw new Error(result.error || "Something went wrong");
    }

    return result;
}

async function refresh() {
    const data = await api("/api/state");

    const transactions = data.transactions;
    const resources = data.resources;

    document.getElementById("txSelect").innerHTML =
        '<option value="">Select Transaction</option>' +
        transactions.map(t =>
            `<option value="${t.id}">${t.name}</option>`
        ).join("");

    document.getElementById("finishTx").innerHTML =
        '<option value="">Select Transaction</option>' +
        transactions.map(t =>
            `<option value="${t.id}">${t.name}</option>`
        ).join("");

    document.getElementById("resSelect").innerHTML =
        '<option value="">Select Resource</option>' +
        resources.map(r =>
            `<option value="${r.id}">${r.name}</option>`
        ).join("");

    document.getElementById("transactionTable").innerHTML =
        makeTable(["ID", "Name", "Status"],
            transactions.map(t => [t.id, t.name, t.status]));

    document.getElementById("resourceTable").innerHTML =
        makeTable(["ID", "Resource", "Holder"],
            resources.map(r => [r.id, r.name, r.holder || "Free"]));

    document.getElementById("waitingTable").innerHTML =
        makeTable(["Transaction", "Waiting For"],
            data.waiting.map(w =>
                [w.transaction_name, w.resource_name]
            ));

    document.getElementById("logs").innerHTML =
        data.logs.map(log =>
            `<p>${log.message}</p>`
        ).join("");
}

function makeTable(headers, rows) {
    return `<table>
        <tr>${headers.map(h => `<th>${h}</th>`).join("")}</tr>
        ${rows.map(row =>
            `<tr>${row.map(value => `<td>${value ?? ""}</td>`).join("")}</tr>`
        ).join("")}
    </table>`;
}

async function runAction(action) {
    try {
        await action();
        await refresh();
    } catch (error) {
        alert(error.message);
    }
}

document.getElementById("createTransaction").onclick = () =>
    runAction(async () => {
        const name = document.getElementById("tName").value.trim();
        await api("/api/transactions", "POST", { name });
        document.getElementById("tName").value = "";
    });

document.getElementById("createResource").onclick = () =>
    runAction(async () => {
        const name = document.getElementById("rName").value.trim();
        await api("/api/resources", "POST", { name });
        document.getElementById("rName").value = "";
    });

document.getElementById("requestResource").onclick = () =>
    runAction(async () => {
        const transaction_id = document.getElementById("txSelect").value;
        const resource_id = document.getElementById("resSelect").value;

        await api("/api/request", "POST", {
            transaction_id: Number(transaction_id),
            resource_id: Number(resource_id)
        });
    });

async function finish(action) {
    const transaction_id = document.getElementById("finishTx").value;

    await api("/api/finish", "POST", {
        transaction_id: Number(transaction_id),
        action
    });
}

document.getElementById("commit").onclick = () =>
    runAction(() => finish("COMMITTED"));

document.getElementById("rollback").onclick = () =>
    runAction(() => finish("ROLLED BACK"));

document.getElementById("detect").onclick = () =>
    runAction(async () => {
        const result = await api("/api/detect");

        const graph = document.getElementById("graph");

        if (result.deadlock) {
            lastDeadlockCycle = result.cycle;

            document.getElementById("result").innerText =
                "DEADLOCK DETECTED: " + result.cycle.join(" → ");

            graph.innerHTML = `
                <h3>Wait-For Graph</h3>
                <div style="display:flex; align-items:center;
                justify-content:center; flex-wrap:wrap; gap:10px;">
                    ${result.cycle.map((name, i) => `
                        <span style="background:#2563eb;color:white;
                        padding:12px 20px;border-radius:8px;">
                            ${name}
                        </span>
                        ${i < result.cycle.length - 1 ? "→" : ""}
                    `).join("")}
                </div>
                <p>Cycle detected: Deadlock exists.</p>
            `;
        } else {
            lastDeadlockCycle = [];
            document.getElementById("result").innerText =
                "No Deadlock Detected";
            graph.innerHTML = "No waiting cycle found.";
        }
    });
document.getElementById("recover").onclick = () =>
    runAction(async () => {
        if (lastDeadlockCycle.length < 2) {
            throw new Error("Detect a deadlock first.");
        }

        const victimName = lastDeadlockCycle[0];

        const data = await api("/api/state");

        const victim = data.transactions.find(
            t => t.name === victimName
        );

        if (!victim) {
            throw new Error("Victim transaction not found.");
        }

        await api("/api/finish", "POST", {
            transaction_id: victim.id,
            action: "ROLLED BACK"
        });

        lastDeadlockCycle = [];

        document.getElementById("result").innerText =
            "Recovery successful! " + victimName + " rolled back.";

        document.getElementById("graph").innerHTML =
            "Deadlock cycle removed after rollback.";
    });

async function loadBankAccounts() {
    try {
        const response = await fetch("/api/accounts");
        const accounts = await response.json();

        accounts.forEach(account => {
            const balanceElement = document.getElementById(
                "balance" + account.account_number
            );

            if (balanceElement) {
                balanceElement.innerText =
                    "₹" + Number(account.balance).toLocaleString("en-IN", {
                        minimumFractionDigits: 2
                    });
            }
        });
    } catch (error) {
        console.error("Account loading error:", error);
    }
}

document.getElementById("transferButton").onclick = async () => {
    const sender = document.getElementById("bankSender").value;
    const receiver = document.getElementById("bankReceiver").value;
    const amount = document.getElementById("transferAmount").value;
    const message = document.getElementById("transferMessage");

    try {
        const response = await fetch("/api/transfer", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                sender,
                receiver,
                amount
            })
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.error || "Transfer failed");
        }

        message.style.color = "green";
        message.innerText = "Transfer successful! ₹" + amount;

        document.getElementById("transferAmount").value = "";

        await loadBankAccounts();

    } catch (error) {
        message.style.color = "red";
        message.innerText = error.message;
    }
};

loadBankAccounts();
