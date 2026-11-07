
/* ==========================================
   GADBADDU - MAIN JAVASCRIPT
   Short Video Social Platform
========================================== */

"use strict";


/* ==========================================
   1. SPLASH SCREEN
========================================== */

document.addEventListener("DOMContentLoaded", function () {

    const splash = document.querySelector(".splash-screen");

    if (splash) {
        document.body.classList.add("splash-active");

        setTimeout(function () {
            splash.classList.add("splash-hidden");
            document.body.classList.remove("splash-active");

            setTimeout(function () {
                splash.remove();
            }, 500);

        }, 3000);
    }

});


/* ==========================================
   2. VIDEO AUTO PLAY
========================================== */

document.addEventListener("DOMContentLoaded", function () {

    const videos = document.querySelectorAll(".feed-video");

    if (!videos.length) return;

    const videoObserver = new IntersectionObserver(
        function (entries) {

            entries.forEach(function (entry) {

                const video = entry.target;

                if (entry.isIntersecting && entry.intersectionRatio >= 0.65) {

                    videos.forEach(function (otherVideo) {

                        if (otherVideo !== video) {
                            otherVideo.pause();
                        }

                    });

                    video.play().catch(function () {
                        // Browser may require user interaction.
                    });

                } else {
                    video.pause();
                }

            });

        },
        {
            threshold: [0, 0.65, 1]
        }
    );

    videos.forEach(function (video) {

        video.muted = true;
        video.playsInline = true;

        videoObserver.observe(video);

    });

});


/* ==========================================
   3. TAP VIDEO TO PLAY / PAUSE
========================================== */

document.addEventListener("click", function (event) {

    const video = event.target.closest(".feed-video");

    if (!video) return;

    if (event.target.closest("button, a")) return;

    if (video.paused) {

        video.play().catch(function () {});

    } else {

        video.pause();

    }

});


/* ==========================================
   4. MUTE / UNMUTE
========================================== */

document.addEventListener("click", function (event) {

    const button = event.target.closest("[data-mute-toggle]");

    if (!button) return;

    const container = button.closest(".feed-item");
    const video = container
        ? container.querySelector(".feed-video")
        : document.querySelector(".feed-video");

    if (!video) return;

    video.muted = !video.muted;

    button.textContent = video.muted ? "🔇" : "🔊";

});


/* ==========================================
   5. DOUBLE TAP LIKE ANIMATION
========================================== */

const lastTapTime = new WeakMap();

document.addEventListener("click", function (event) {

    const video = event.target.closest(".feed-video");

    if (!video) return;

    const currentTime = Date.now();
    const previousTime = lastTapTime.get(video) || 0;

    if (currentTime - previousTime < 300) {

        const container = video.closest(".feed-item");

        if (container) {

            const heart = document.createElement("div");

            heart.className = "double-tap-heart";
            heart.textContent = "❤️";

            heart.style.position = "absolute";
            heart.style.left = "50%";
            heart.style.top = "45%";
            heart.style.transform = "translate(-50%, -50%)";
            heart.style.fontSize = "75px";
            heart.style.zIndex = "20";
            heart.style.pointerEvents = "none";
            heart.style.animation = "gadbadduHeart 0.7s ease forwards";

            container.appendChild(heart);

            setTimeout(function () {
                heart.remove();
            }, 750);

        }

    }

    lastTapTime.set(video, currentTime);

});


/* ==========================================
   6. SHARE VIDEO
========================================== */

document.addEventListener("click", async function (event) {

    const button = event.target.closest("[data-share]");

    if (!button) return;

    const shareUrl = button.dataset.share || window.location.href;

    const shareData = {
        title: "Gadbaddu",
        text: "Check out this video on Gadbaddu!",
        url: new URL(shareUrl, window.location.origin).href
    };

    try {

        if (navigator.share) {

            await navigator.share(shareData);

        } else if (navigator.clipboard) {

            await navigator.clipboard.writeText(shareData.url);

            button.textContent = "Copied!";

            setTimeout(function () {
                button.textContent = "Share";
            }, 1500);

        } else {

            window.prompt("Copy this link:", shareData.url);

        }

    } catch (error) {

        if (error.name !== "AbortError") {
            console.error("Share failed:", error);
        }

    }

});


/* ==========================================
   7. LOGIN REQUIRED ACTIONS
========================================== */

document.addEventListener("click", function (event) {

    const button = event.target.closest("[data-login-required]");

    if (!button) return;

    event.preventDefault();

    const loginUrl = button.dataset.loginUrl || "/login";

    window.location.href = loginUrl;

});


/* ==========================================
   8. FLASH MESSAGE AUTO HIDE
========================================== */

document.addEventListener("DOMContentLoaded", function () {

    const messages = document.querySelectorAll(".flash-message");

    messages.forEach(function (message) {

        setTimeout(function () {

            message.style.transition = "opacity 0.4s ease";
            message.style.opacity = "0";

            setTimeout(function () {
                message.remove();
            }, 450);

        }, 4000);

    });

});


/* ==========================================
   9. SEARCH FORM
========================================== */

document.addEventListener("submit", function (event) {

    const form = event.target.closest(".explore-search");

    if (!form) return;

    const input = form.querySelector("input[name='q']");

    if (!input || !input.value.trim()) {

        event.preventDefault();

        if (input) input.focus();

    }

});


/* ==========================================
   10. VIDEO PROGRESS BAR
========================================== */

document.addEventListener("DOMContentLoaded", function () {

    const videos = document.querySelectorAll(".feed-video");

    videos.forEach(function (video) {

        video.addEventListener("timeupdate", function () {

            const container = video.closest(".feed-item");

            if (!container || !video.duration) return;

            const progress = container.querySelector(".video-progress");

            if (!progress) return;

            const percentage =
                (video.currentTime / video.duration) * 100;

            progress.style.width = percentage + "%";

        });

    });

});


/* ==========================================
   11. FOLLOW BUTTON FEEDBACK
========================================== */

document.addEventListener("submit", function (event) {

    const form = event.target.closest("[data-follow-form]");

    if (!form) return;

    const button = form.querySelector("button");

    if (button) {

        button.disabled = true;
        button.textContent = "Please wait...";

    }

});


/* ==========================================
   12. DOUBLE TAP HEART ANIMATION CSS
========================================== */

const animationStyle = document.createElement("style");

animationStyle.textContent = `
@keyframes gadbadduHeart {
    0% {
        opacity: 0;
        transform: translate(-50%, -50%) scale(0.3);
    }

    35% {
        opacity: 1;
        transform: translate(-50%, -50%) scale(1.3);
    }

    100% {
        opacity: 0;
        transform: translate(-50%, -50%) scale(1);
    }
}

.splash-hidden {
    opacity: 0;
    visibility: hidden;
    transition: opacity 0.5s ease, visibility 0.5s ease;
}

.splash-screen {
    position: fixed;
    inset: 0;
    z-index: 9999;
}
`;

document.head.appendChild(animationStyle);


/* ==========================================
   GADBADDU INITIALIZED
========================================== */

console.log("Gadbaddu JavaScript Loaded Successfully!");

