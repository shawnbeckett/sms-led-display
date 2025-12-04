const API_BASE = "https://bq6tluiuu3.execute-api.us-east-1.amazonaws.com";

// -----------------------------
// Simple screen management
// -----------------------------
let messagesScreen;
let settingsScreen;
let openSettingsBtn;
let backToMessagesBtn;
let saveSettingsBtn;
let screenMuteToggle;

// Track whether settings have unsaved changes
let settingsDirty = false;

// UI-editable settings fields (do not include banned word lists)
const SETTINGS_FIELDS = {
    moderation_mode: { id: "moderation_mode", type: "string" },
    profanity_mode: { id: "profanity_mode", type: "string" },
    max_message_length: { id: "max_message_length", type: "number" },
    scroll_behavior: { id: "scroll_behavior", type: "string" },
    message_lifespan_seconds: { id: "message_lifespan_seconds", type: "number" },
    screen_muted: { id: "screen_muted", type: "boolean" },
};

// Format seconds into m:ss for countdown display
function formatSeconds(seconds) {
    const safe = Math.max(0, Math.floor(seconds));
    const mins = Math.floor(safe / 60);
    const secs = safe % 60;
    return `${mins}:${secs.toString().padStart(2, "0")}`;
}

// Helper: show messages screen, hide settings
function showMessagesScreen() {
    if (!messagesScreen || !settingsScreen) return;

    messagesScreen.classList.add("screen-active");
    messagesScreen.classList.remove("screen-hidden");

    settingsScreen.classList.add("screen-hidden");
    settingsScreen.classList.remove("screen-active");
}

// Helper: show settings screen, hide messages
function showSettingsScreen() {
    if (!messagesScreen || !settingsScreen) return;

    settingsScreen.classList.add("screen-active");
    settingsScreen.classList.remove("screen-hidden");

    messagesScreen.classList.add("screen-hidden");
    messagesScreen.classList.remove("screen-active");
}

// -----------------------------
// Init wiring + polling
// -----------------------------
function initApp() {
    messagesScreen = document.getElementById("messages-screen");
    settingsScreen = document.getElementById("settings-screen");
    openSettingsBtn = document.getElementById("open-settings-btn");
    backToMessagesBtn = document.getElementById("back-to-messages-btn");
    saveSettingsBtn = document.getElementById("save-settings-btn");
    screenMuteToggle = document.getElementById("screen_muted");

    // Wire the Settings button (from messages screen)
    if (openSettingsBtn) {
        openSettingsBtn.addEventListener("click", () => {
            showSettingsScreen();
        });
    }

    // Wire the Back button (from settings screen)
    if (backToMessagesBtn) {
        backToMessagesBtn.addEventListener("click", () => {
            if (settingsDirty) {
                const confirmLeave = window.confirm(
                    "You have unsaved changes. Leave settings without saving?"
                );
                if (!confirmLeave) {
                    // Stay on settings screen
                    return;
                }
            }
            showMessagesScreen();
        });
    }

    // Wire save settings button
    if (saveSettingsBtn) {
        saveSettingsBtn.addEventListener("click", saveSettings);
    }

    // Wire mute toggle (always visible on messages screen)
    if (screenMuteToggle) {
        screenMuteToggle.addEventListener("change", handleScreenMuteToggle);
    }

    // Force default view on load
    showMessagesScreen();

    // Start polling
    setInterval(loadPendingMessages, 2000);
    setInterval(loadApprovedMessages, 2000);

    // Initial fetches
    loadPendingMessages();
    loadApprovedMessages();
    loadSettings();
}

// -----------------------------
// Mute toggle
// -----------------------------
async function handleScreenMuteToggle() {
    if (!screenMuteToggle) return;
    const isMuted = !!screenMuteToggle.checked;

    try {
        screenMuteToggle.disabled = true;
        await fetch(`${API_BASE}/settings`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ screen_muted: isMuted })
        });
    } catch (err) {
        console.error("Error toggling screen mute:", err);
        // revert toggle on failure
        screenMuteToggle.checked = !isMuted;
        alert("Could not update mute setting. Please try again.");
    } finally {
        screenMuteToggle.disabled = false;
    }
}

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
                    <button class="reject-btn" onclick="rejectMessage('${msg.pk}')">Reject</button>
                    <button class="approve-btn" onclick="approveMessage('${msg.pk}')">Approve</button>
                </div>
            `;

            list.appendChild(div);
        });

    } catch (err) {
        console.error("Error loading pending messages:", err);
    }
}

// -----------------------------
// Load approved (live) messages
// -----------------------------
async function loadApprovedMessages() {
    try {
        const res = await fetch(`${API_BASE}/messages/approved`);
        const data = await res.json();

        const list = document.getElementById("approved-list");
        if (!list) {
            console.warn("No #approved-list element found in HTML");
            return;
        }

        list.innerHTML = "";

        if (!data.items || data.items.length === 0) {
            list.innerHTML = `<p class="empty">No live messages.</p>`;
            return;
        }

        data.items.forEach(msg => {
            const div = document.createElement("div");
            div.className = "message-item";

            const ts = msg.created_at
                ? new Date(msg.created_at).toLocaleString()
                : "No timestamp";

            const expiresRaw = msg.expires_at;
            const expiresAt = expiresRaw ? Number(expiresRaw) : null;
            const nowSec = Date.now() / 1000;
            const remainingSec = expiresAt ? Math.max(0, Math.floor(expiresAt - nowSec)) : null;
            const showCountdown = msg.status === "played" && remainingSec !== null;

            div.innerHTML = `
                <div class="msg-header">
                    <p><strong>${msg.body || "(empty message)"}</strong></p>
                    <span class="status-badge status-${msg.status}">${msg.status}</span>
                </div>
                <p class="meta">From: ${msg.from_number || "(unknown)"}</p>
                <p class="timestamp">Sent: ${ts}</p>
                ${showCountdown ? `<p class="countdown">Expires in ${formatSeconds(remainingSec)}</p>` : ""}

                <div class="actions-row" style="justify-content: flex-end;">
                    <button class="reject-btn" onclick="rejectMessage('${msg.pk}', true)">Remove</button>
                </div>
            `;

            list.appendChild(div);
        });

    } catch (err) {
        console.error("Error loading approved messages:", err);
    }
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
    loadApprovedMessages();
}

// -----------------------------
// Reject
// -----------------------------
async function rejectMessage(pk, fromApproved = false) {
    await fetch(`${API_BASE}/messages/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_id: pk })
    });
    loadPendingMessages();
    if (fromApproved) {
        loadApprovedMessages();
    }
}

// -----------------------------
// Settings helpers
// -----------------------------
function markSettingsDirty() {
    settingsDirty = true;
}

// Attach change listeners to settings fields to mark as dirty
function initSettingsDirtyTracking() {
    const form = document.getElementById("settings-form");
    if (!form) return;

    const inputs = form.querySelectorAll("input, textarea, select");
    inputs.forEach(el => {
        el.addEventListener("change", markSettingsDirty);
        el.addEventListener("input", markSettingsDirty);
    });
}

// -----------------------------
// Load settings
// -----------------------------
async function loadSettings() {
    try {
        const res = await fetch(`${API_BASE}/settings`);
        const data = await res.json();

        Object.entries(SETTINGS_FIELDS).forEach(([key, cfg]) => {
            const el = document.getElementById(cfg.id);
            if (!el) return;

            if (!(key in data)) {
                if (cfg.type === "boolean") {
                    el.checked = false;
                } else {
                    el.value = "";
                }
                return;
            }

            const value = data[key];
            if (cfg.type === "string") {
                el.value = value ?? "";
            } else if (cfg.type === "number") {
                el.value =
                    value !== undefined && value !== null ? Number(value) : "";
            } else if (cfg.type === "boolean") {
                el.checked = Boolean(value);
            }
        });

        // After loading from backend, settings are in sync → not dirty
        settingsDirty = false;

        // Initialise dirty tracking once we have the elements
        initSettingsDirtyTracking();

    } catch (err) {
        console.error("Settings load error:", err);
    }
}

// -----------------------------
// Save settings
// -----------------------------
async function saveSettings() {
    const payload = {};

    for (const [key, cfg] of Object.entries(SETTINGS_FIELDS)) {
        const el = document.getElementById(cfg.id);
        if (!el) continue;

        if (cfg.type === "string") {
            const v = (el.value || "").trim();
            if (v !== "") {
                payload[key] = v;
            }
        } else if (cfg.type === "number") {
            const num = Number(el.value);
            if (!Number.isNaN(num) && Number.isFinite(num)) {
                payload[key] = num;
            }
        } else if (cfg.type === "boolean") {
            payload[key] = !!el.checked;
        }
    }

    await fetch(`${API_BASE}/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });

    alert("Settings saved.");
    // Reload from backend to normalise values and clear dirty flag
    await loadSettings();
    settingsDirty = false;
}

// Kick off once DOM is ready
document.addEventListener("DOMContentLoaded", initApp);
