const API_URL = "https://fred-otp-backend.onrender.com/api/v1";

// --- 1. AUTHENTICATION (index.html) ---
async function handleAuth(event, isSignUp) {
    event.preventDefault(); // Prevent form from refreshing the page
    
    // Get the values from your input fields (Make sure your inputs have these IDs)
    const username = document.getElementById("username-input").value;
    const password = document.getElementById("password-input").value;
    const endpoint = isSignUp ? "/auth/signup" : "/auth/signin";

    try {
        let res = await fetch(`${API_URL}${endpoint}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: username, password: password })
        });
        let data = await res.json();
        
        if (data.success) {
            // Save the user session securely in the browser and redirect
            localStorage.setItem("fred_user", username);
            window.location.href = "dashboard.html";
        } else {
            alert(data.error || "Authentication failed.");
        }
    } catch (err) {
        alert("Network error connecting to backend.");
    }
}

// --- 2. DASHBOARD DATA BINDING (dashboard.html) ---
let currentUser = localStorage.getItem("fred_user");

async function loadWallet() {
    if (!currentUser) return; // Not on dashboard
    
    try {
        let res = await fetch(`${API_URL}/wallet/${currentUser}`);
        let data = await res.json();
        
        // Update balance on screen
        const balanceElement = document.getElementById("wallet-balance");
        if (balanceElement) balanceElement.innerText = `₦${data.balance_ngn.toFixed(2)}`;
        
        // Update transaction history
        const txElement = document.getElementById("transaction-history");
        if (txElement) {
            let txHTML = "";
            data.transactions.reverse().forEach(tx => {
                let color = tx.type === "CREDIT" ? "#00b894" : "#d63031";
                txHTML += `<div style="color:${color}; font-family:monospace; margin-bottom:5px;">[${tx.type}] ₦${tx.amount} - ${tx.desc}</div>`;
            });
            txElement.innerHTML = txHTML || "<span style='color:gray;'>No transactions yet.</span>";
        }
    } catch (err) {
        console.error("Error loading wallet:", err);
    }
}

// --- 3. WALLET FUNDING FLOW ---
async function fundWallet(amount) {
    if (!currentUser) return;
    try {
        let res = await fetch(`${API_URL}/wallet/fund`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_id: currentUser, amount_ngn: amount })
        });
        let data = await res.json();
        if (data.success) {
            alert(`Successfully funded ₦${amount}!`);
            loadWallet(); // Instantly refresh balance display
        }
    } catch (err) {
        console.error("Funding error:", err);
    }
}

// --- 4. VIRTUAL NUMBER RENTAL & LIVE SMS POLLING ---
let activePhoneNumber = null;
let smsInterval = null;

async function rentNumber(serviceName) {
    if (!currentUser) return;
    
    document.getElementById("active-number-display").innerText = "Requesting number...";
    document.getElementById("sms-inbox-display").innerHTML = "";
    
    try {
        let res = await fetch(`${API_URL}/numbers/rent`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_id: currentUser, service_name: serviceName })
        });
        let data = await res.json();
        
        if (data.success) {
            activePhoneNumber = data.phone_number;
            document.getElementById("active-number-display").innerText = `${serviceName.toUpperCase()}: ${activePhoneNumber}`;
            loadWallet(); // Refresh balance after the rental fee is deducted
            
            // Start checking for SMS codes every 5 seconds
            document.getElementById("sms-inbox-display").innerHTML = "<span style='color:orange;'>Waiting for verification code...</span>";
            if (smsInterval) clearInterval(smsInterval);
            smsInterval = setInterval(checkSMS, 5000);
        } else {
            alert("Error: " + (data.detail || data.error));
            document.getElementById("active-number-display").innerText = "Rental Failed";
        }
    } catch (err) {
        console.error("Rental error:", err);
    }
}

async function checkSMS() {
    if (!activePhoneNumber) return;
    try {
        let res = await fetch(`${API_URL}/sms/inbox/${activePhoneNumber}`);
        let data = await res.json();
        
        if (data.messages && data.messages.length > 0) {
            let msg = data.messages[0]; 
            document.getElementById("sms-inbox-display").innerHTML = `
                <div style="background:#0984e3; padding:15px; border-radius:5px; color:white; text-align:center;">
                    <h2 style="margin:0;">Code: ${msg.code}</h2>
                    <small>${msg.body}</small>
                </div>
            `;
            clearInterval(smsInterval); // Stop polling once the code arrives
        }
    } catch (err) {
        console.error("SMS polling error:", err);
    }
}

// Auto-load wallet when dashboard opens
if (window.location.pathname.includes("dashboard")) {
    if (!currentUser) window.location.href = "index.html"; // Protect route
    window.onload = loadWallet;
}
