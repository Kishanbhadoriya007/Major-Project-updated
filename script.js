// portfolio_script.js
document.addEventListener('DOMContentLoaded', () => {
    const mainNav = document.getElementById('main-nav');
    const mobileMenuButton = document.getElementById('mobile-menu-button');
    const mobileMenu = document.getElementById('mobile-menu');
    const navLinks = document.querySelectorAll('.nav-link');

    // --- Navbar Scroll Effect ---
    if (mainNav) {
        window.addEventListener('scroll', () => {
            if (window.scrollY > 50) {
                mainNav.classList.add('bg-slate-900/90', 'shadow-lg', 'py-3', 'backdrop-blur-md'); // Added backdrop blur
                mainNav.classList.remove('py-4');
            } else {
                mainNav.classList.remove('bg-slate-900/90', 'shadow-lg', 'py-3', 'backdrop-blur-md');
                mainNav.classList.add('py-4');
            }
        });
    }

    // --- Mobile Menu Toggle ---
    if (mobileMenuButton && mobileMenu) {
        mobileMenuButton.addEventListener('click', () => {
            mobileMenu.classList.toggle('hidden');
            mobileMenu.classList.toggle('mobile-nav-active');
            const icon = mobileMenuButton.querySelector('i');
            if (mobileMenu.classList.contains('hidden')) {
                icon.classList.remove('fa-times');
                icon.classList.add('fa-bars');
            } else {
                icon.classList.remove('fa-bars');
                icon.classList.add('fa-times');
            }
        });
    }

    // --- Smooth Scrolling & Active Link Highlighting & Close Mobile Menu ---
    navLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            const href = this.getAttribute('href');
            if (href && href.startsWith('#')) {
                e.preventDefault();
                const targetId = href.substring(1);
                const targetElement = document.getElementById(targetId);

                if (targetElement) {
                    targetElement.scrollIntoView({
                        behavior: 'smooth'
                    });
                    if (!link.classList.contains('mobile-nav-link')) {
                       updateActiveLink(this);
                    }
                }
            }
            if (link.classList.contains('mobile-nav-link') && !mobileMenu.classList.contains('hidden')) {
                mobileMenu.classList.add('hidden');
                mobileMenu.classList.remove('mobile-nav-active');
                const icon = mobileMenuButton.querySelector('i');
                icon.classList.remove('fa-times');
                icon.classList.add('fa-bars');
            }
        });
    });

    function updateActiveLink(activeLink) {
        document.querySelectorAll('#main-nav .hidden.md\\:flex a.nav-link').forEach(navLink => {
            navLink.classList.remove('text-sky-400', 'font-semibold');
            navLink.classList.add('text-slate-300');
        });
        if (activeLink && !activeLink.classList.contains('mobile-nav-link')) {
            activeLink.classList.add('text-sky-400', 'font-semibold');
            activeLink.classList.remove('text-slate-300');
        }
    }

    // --- Active Link Highlighting on Scroll using Intersection Observer ---
    const sections = document.querySelectorAll('main section[id]');
    const observerOptions = {
        root: null,
        rootMargin: '0px',
        threshold: 0.5 // Trigger when 50% of the section is visible
    };

    const sectionObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const intersectingLink = document.querySelector(`.nav-link[href="#${entry.target.id}"]`);
                updateActiveLink(intersectingLink);
            }
        });
    }, observerOptions);

    sections.forEach(section => {
        sectionObserver.observe(section);
    });

    // --- GSAP Scroll-Triggered Animations ---
    if (typeof gsap !== 'undefined' && typeof ScrollTrigger !== 'undefined') {
        gsap.registerPlugin(ScrollTrigger);

        // General reveal animation for elements with 'gsap-reveal' class
        // These elements are visible by default and GSAP animates them 'from' an offset state.
        gsap.utils.toArray('.gsap-reveal').forEach((elem) => {
            gsap.from(elem, { // Changed from fromTo to from, assuming default CSS is the 'to' state
                opacity: 0,
                y: 50,
                duration: 0.8,
                ease: 'power3.out',
                scrollTrigger: {
                    trigger: elem,
                    start: 'top 90%', // When the top of the element hits 90% from the top of the viewport
                    toggleActions: 'play none none none',
                    once: true,
                    invalidateOnRefresh: true,
                }
            });
        });

        // Staggered animation for skill items
        // Skill items are visible by default HTML/CSS. GSAP animates them 'from' an offset state.
        gsap.from(".skill-item", {
            scrollTrigger: {
                trigger: "#skills .grid",
                start: "top 90%", // Trigger when the top of the skills grid is 90% from the viewport top
                toggleActions: "play none none none",
                once: true,
                invalidateOnRefresh: true,
            },
            opacity: 0,
            y: 40,
            duration: 0.5,
            stagger: 0.1, // Reduced stagger for potentially faster perceived loading of all items
            ease: "power2.out",
        });

        // Staggered animation for project cards
        // Project cards are visible by default HTML/CSS. GSAP animates them 'from' an offset state.
        gsap.from(".project-card", {
            scrollTrigger: {
                trigger: "#projects .grid",
                start: "top 90%", // Trigger when the top of the projects grid is 90% from the viewport top
                toggleActions: "play none none none",
                once: true,
                invalidateOnRefresh: true,
            },
            opacity: 0,
            y: 50,
            duration: 0.6,
            stagger: 0.15, // Reduced stagger
            ease: "power3.out",
        });

    } else {
        console.warn("GSAP or ScrollTrigger library not loaded. Animations disabled.");
        // Fallback: If GSAP is not loaded, ensure elements that might rely on it are visible.
        // Since we removed initial opacity:0 from CSS, this might not be strictly necessary,
        // but it's a safeguard.
        document.querySelectorAll('.gsap-reveal, .skill-item, .project-card').forEach(el => {
            el.style.opacity = '1'; // Ensure they are visible
            el.style.transform = 'translateY(0)'; // Reset any transform
        });
    }

    // --- Update Footer Year ---
    const yearSpan = document.getElementById('currentYear');
    if (yearSpan) {
        yearSpan.textContent = new Date().getFullYear();
    }

    console.log("Portfolio Script (v3 - Fixes) Loaded & Initialized");
});
