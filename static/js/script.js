// static/js/script.js

// --- Custom Cursor Logic ---
const crsr = document.querySelector("#cursor");
const blur = document.querySelector("#cursor-blur");

// Check if elements exist before adding listener
if (crsr && blur) {
    document.addEventListener("mousemove", function(dets) {
        // Animate using GSAP for smoother transitions (optional, but nice)
        gsap.to(crsr, {
            duration: 0.2, // Faster update
            x: dets.clientX,
            y: dets.clientY,
            ease: "power1.out" // Smooth easing
        });
        gsap.to(blur, {
            duration: 0.5, // Slightly slower for the blur
            x: dets.clientX - 200, // Center the blur relative to cursor (adjust offset as needed)
            y: dets.clientY - 200,
            ease: "power1.out"
        });
        // Original direct style manipulation (fallback if GSAP not loaded)
        // crsr.style.left = dets.x + "px";
        // crsr.style.top = dets.y + "px";
        // blur.style.left = dets.x - 200 + "px"; // Adjusted offset
        // blur.style.top = dets.y - 200 + "px";
    });
} else {
    console.warn("Cursor elements (#cursor or #cursor-blur) not found.");
}


// --- GSAP Navbar Animation ---
// Ensure GSAP and ScrollTrigger are loaded before this runs
// The check helps prevent errors if GSAP fails to load
if (typeof gsap !== 'undefined' && typeof ScrollTrigger !== 'undefined') {
    gsap.registerPlugin(ScrollTrigger); // Register plugin

    const navHeader = document.querySelector("#nav"); // Target header by ID

    if (navHeader) {
        ScrollTrigger.create({
            trigger: "body", // Trigger based on body scrolling
            start: "top top", // Start when the top of the body hits the top of the viewport
            end: "+=100", // End after scrolling down 100 pixels
            // markers: true, // Uncomment for debugging scroll trigger positions
            onEnter: () => navHeader.classList.add('scrolled'), // Add class when scrolling down
            onLeaveBack: () => navHeader.classList.remove('scrolled') // Remove class when scrolling back up
        });

        // Optional: Smoother GSAP animation instead of class toggle
        // gsap.to("#nav", {
        //     backgroundColor: "rgba(0, 0, 0, 0.85)",
        //     height: "80px", // Target height on scroll
        //     backdropFilter: "blur(5px)", // Animate blur if supported
        //     duration: 0.3, // Animation duration
        //     scrollTrigger: {
        //         trigger: "body",
        //         scroller: "body",
        //         // markers: true,
        //         start: "top -10px", // Start animation slightly after scrolling
        //         end: "top -100px",
        //         scrub: 0.5, // Smooth scrubbing effect
        //     }
        // });

    } else {
         console.warn("Navigation header (#nav) not found for scroll animation.");
    }

} else {
    console.warn("GSAP or ScrollTrigger library not loaded. Animations disabled.");
}


console.log("Trinity PDF Suite Script Loaded");
// Add any other specific JS logic needed for your forms (e.g., dynamic options) here