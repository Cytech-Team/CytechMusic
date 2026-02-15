// ==========================================
// PAYMENT LOGIC
// ==========================================
const GAS_ENDPOINT = "/api/proxy";

// Hook called by script.js when logged in
// Hook called by script.js when logged in
function onUserLoggedIn(user) {
    const idInput = document.getElementById('userId');
    const inputWrapper = document.querySelector('.user-input-wrapper');
    const inputGroup = document.querySelector('.input-group');

    if (idInput && inputWrapper) {
        idInput.value = user.id;
        idInput.classList.add('authenticated');

        // Remove existing avatar if any (for fresh updates)
        const existingAvatar = document.getElementById('user-input-avatar');
        if (existingAvatar) existingAvatar.remove();

        // Create and add new avatar
        const avatarUrl = user.avatar
            ? `https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png?size=64`
            : `https://cdn.discordapp.com/embed/avatars/${parseInt(user.id) % 5}.png`;

        const avatarImg = document.createElement('img');
        avatarImg.id = "user-input-avatar";
        avatarImg.className = "user-input-avatar";
        avatarImg.src = avatarUrl;
        inputWrapper.appendChild(avatarImg);

        const hint = inputGroup.querySelector('small');
        if (hint) hint.style.display = 'none';

        const label = inputGroup.querySelector('label');
        if (label) {
            const lang = window.currentLang || 'en';
            label.innerHTML = `
                <div style="display: flex; align-items: center; justify-content: space-between; width: 100%;">
                    <span><i class="fab fa-discord" style="color: #5865F2; margin-right: 8px;"></i>${lang === 'th' ? 'บัญชีผู้ใช้' : 'Discord Account'}</span>
                    <span style="font-weight: 800; color: #fff; background: rgba(255,255,255,0.05); padding: 2px 10px; border-radius: 20px; font-size: 0.82rem; border: 1px solid rgba(255,255,255,0.1);">
                        @${user.username}
                    </span>
                </div>`;
        }
    }
}

let selectedPlanId = null;

// Handle Plan Selection
function selectPlan(planId, element) {
    selectedPlanId = planId;

    // Remove active class from all
    document.querySelectorAll('.plan-card').forEach(card => {
        card.classList.remove('selected');
    });

    // Add active class to clicked
    element.classList.add('selected');
}

// Handle Checkout Process
async function initiateCheckout() {
    const userIdInput = document.getElementById('userId');
    const errorMsg = document.getElementById('error-msg');
    const btn = document.getElementById('checkout-btn');
    const btnText = btn.querySelector('.btn-text');
    const spinner = btn.querySelector('.loading-spinner');

    const userId = userIdInput.value.trim();

    // Reset error
    errorMsg.style.display = 'none';
    errorMsg.textContent = '';

    // Validation
    if (!userId) {
        // If empty (and likely not logged in), prompt login
        if (confirm("Please login with Discord to proceed.\nกรุณาล็อกอินด้วย Discord เพื่อดำเนินการต่อ")) {
            login();
        }
        return;
    }
    if (!/^\d{17,20}$/.test(userId)) {
        showError("Invalid User ID format (Must be 17-20 digits) / รูปแบบ User ID ไม่ถูกต้อง");
        return;
    }
    if (!selectedPlanId) {
        showError("Please select a plan / กรุณาเลือกแพ็กเกจ");
        return;
    }



    // Lock UI
    btn.disabled = true;
    btn.style.opacity = '0.7';
    btnText.style.display = 'none';
    spinner.style.display = 'block';

    try {
        const response = await fetch(GAS_ENDPOINT, {
            method: 'POST',
            redirect: "follow",
            headers: { "Content-Type": "text/plain;charset=utf-8" },
            body: JSON.stringify({
                action: "create_checkout",
                user_id: userId,
                plan_id: selectedPlanId
            })
        });

        const data = await response.json();

        if (data.status === "success" && (data.clientSecret || data.url)) { // Fallback check
            // 1. Initialize Stripe
            // ðŸ”´ IMPORTANT: Replace with your actual Stripe Publishable Key (pk_live_...)
            const stripe = Stripe("pk_live_51SwzRzHTgqCiwJLt1ZjpJuQxvYYwTAORAwnj3stctMiZ36oWZQ4ci81Oxki3ceJtjlKUONIlab9XwbUV42Hnk9UT00zfLndnmf");

            // 2. Mount Embedded Checkout
            const clientSecret = data.clientSecret || data.url; // Handle both structures just in case

            const checkout = await stripe.initEmbeddedCheckout({
                clientSecret: clientSecret
            });

            // Hide Button & Show Form
            btn.style.display = 'none';
            checkout.mount('#checkout-embed');

        } else {
            throw new Error(data.message || "Unknown error from server");
        }

    } catch (err) {
        console.error(err);
        showError("Error: " + err.message);

        // Unlock UI
        btn.disabled = false;
        btn.style.opacity = '1';
        btnText.style.display = 'block';
        spinner.style.display = 'none';
    }
}

function showError(msg) {
    const errorMsg = document.getElementById('error-msg');
    errorMsg.textContent = msg;
    errorMsg.style.display = 'block';
}
