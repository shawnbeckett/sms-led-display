const API_BASE = "https://bq6tluiuu3.execute-api.us-east-1.amazonaws.com";

// Poll pending messages every 2 seconds
setInterval(loadPendingMessages, 2000);
loadPendingMessages();
loadSettings();

// -----------------------------
// Load pending messages
// -----------------------------
async function loadPendingMessages() {
    try {
        const res = await fetch(`${API_BASE}/messages/pending`);
        const data = await res.json();

        const list = document.getElementById("pending-list");
        list.innerHTML = "";

        if (!data.items || data.items.length === 0) {
            list.innerHTML = `<p class="empty">No pending messages.</p>`;
            return;
        }

        data.items.forEach(msg => {
            console.log("Pending message item:", msg);
        
            const div = document.createElement("div");
            div.className = "message-item";

            // Format timestamp
            const ts = msg.created_at
                ? new Date(msg.created_at).toLocaleString()
                : "No timestamp";

            div.innerHTML = `
                <div class="msg-header">
                    <p><strong>${msg.body || "(empty message)"}</strong></p>
                    <span class="status-badge status-${msg.status}">${msg.status}</span>
                </div>
                <p class="meta">From: ${msg.from_number || "(unknown)"}</p>
                <p class="timestamp">Sent: ${ts}</p>

                <div class="actions-row">
                    <button class="approve-btn" onclick="approveMessage('${msg.pk}')">Approve</button>
                    <button class="reject-btn" onclick="rejectMessage('${msg.pk}')">Reject</button>
                </div>
            `;

            list.appendChild(div);
            initSwipeHandlers(div, msg.pk);
        });

    } catch (err) {
        console.error("Error loading pending messages:", err);
    }
}

// -----------------------------
// Swipe handlers (mobile): right = approve, left = reject
// For now these only log; we'll wire them up to approve/reject next.
// -----------------------------
function initSwipeHandlers(element, pk) {
    let startX = 0;
    let currentX = 0;

    const threshold = 80; // pixels to count as a swipe

    element.addEventListener("touchstart", (e) => {
        if (!e.touches || e.touches.length === 0) return;
        startX = e.touches[0].clientX;
        currentX = startX;

        // reset any previous transform
        element.style.transition = "none";
        element.style.transform = "translateX(0px)";
    });

    element.addEventListener("touchmove", (e) => {
        if (!e.touches || e.touches.length === 0) return;
        currentX = e.touches[0].clientX;
        const deltaX = currentX - startX;

        // move the card slightly with the finger
        element.style.transform = `translateX(${deltaX}px)`;
    });

    element.addEventListener("touchend", (e) => {
        const endX = (e.changedTouches && e.changedTouches[0].clientX) || currentX;
        const deltaX = endX - startX;

        // snap back
        element.style.transition = "transform 0.15s ease-out";
        element.style.transform = "translateX(0px)";

        if (deltaX > threshold) {
            console.log("Swipe APPROVE for", pk, "deltaX:", deltaX);
            // later: approveMessage(pk);
        } else if (deltaX < -threshold) {
            console.log("Swipe REJECT for", pk, "deltaX:", deltaX);
            // later: rejectMessage(pk);
        } else {
            console.log("Swipe too small, ignored for", pk, "deltaX:", deltaX);
        }
    });
}

// -----------------------------
// Approve
// -----------------------------
async function approveMessage(pk) {
    await fetch(`${API_BASE}/messages/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_id: pk })
    });
    loadPendingMessages();
}

// -----------------------------
// Reject
// -----------------------------
async function rejectMessage(pk) {
    await fetch(`${API_BASE}/messages/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_id: pk })
    });
    loadPendingMessages();
}

// -----------------------------
// Load settings
// -----------------------------
async function loadSettings() {
    try {
        const res = await fetch(`${API_BASE}/settings`);
        const data = await res.json();

        document.getElementById("moderation_mode").value = data.moderation_mode;
        document.getElementById("profanity_mode").value = data.profanity_mode;
        document.getElementById("max_message_length").value = data.max_message_length;

        document.getElementById("hard_banned_words").value =
            (data.hard_banned_words || []).join(", ");
        document.getElementById("soft_banned_words").value =
            (data.soft_banned_words || []).join(", ");

    } catch (err) {
        console.error("Settings load error:", err);
    }
}

// -----------------------------
// Save settings
// -----------------------------
document.getElementById("save-settings-btn").addEventListener("click", async () => {
    const payload = {
        moderation_mode: document.getElementById("moderation_mode").value,
        profanity_mode: document.getElementById("profanity_mode").value,
        max_message_length: parseInt(document.getElementById("max_message_length").value),
        hard_banned_words: document
            .getElementById("hard_banned_words").value.split(",").map(w => w.trim()).filter(w => w),
        soft_banned_words: document
            .getElementById("soft_banned_words").value.split(",").map(w => w.trim()).filter(w => w)
    };

    await fetch(`${API_BASE}/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });

    alert("Saved!");
    loadSettings();
});
