document.addEventListener("DOMContentLoaded", function () {

    const headerPlaceholder = document.getElementById("header-placeholder");
    const footerPlaceholder = document.getElementById("footer-placeholder");

    let headerFile = "header-main.html";

    // Detect if page is login or register
    const currentPage = window.location.pathname.toLowerCase();

    if (currentPage.includes("login") || currentPage.includes("register")) {
        headerFile = "header-auth.html";
    }

    // Load header
    if (headerPlaceholder) {
        fetch(headerFile)
            .then(res => res.text())
            .then(data => {
                headerPlaceholder.innerHTML = data;
            })
            .catch(err => console.error("Header load error:", err));
    }

    // Load footer
    if (footerPlaceholder) {
        fetch("footer.html")
            .then(res => res.text())
            .then(data => {
                footerPlaceholder.innerHTML = data;
            })
            .catch(err => console.error("Footer load error:", err));
    }

    // Forgot Password
    const forgotPassword = document.getElementById("forgotPassword");
    if (forgotPassword) {
        forgotPassword.addEventListener("click", function () {
            let email = prompt("Please enter your email to reset your password:");
            if (email) {
                alert("Password reset instructions sent to: " + email);
            }
        });
    }
});


// ===== LOGOUT MODAL =====
document.addEventListener("click", function(e){

    // open modal
    if(e.target && e.target.id === "logoutBtn"){
        e.preventDefault();
        const modal = document.getElementById("logoutModal");
        if(modal) modal.style.display = "flex";
    }

    // cancel logout
    if(e.target && e.target.id === "cancelLogout"){
        const modal = document.getElementById("logoutModal");
        if(modal) modal.style.display = "none";
    }

    // confirm logout
    if(e.target && e.target.id === "confirmLogout"){
        window.location.href = "login.html";
    }

});
