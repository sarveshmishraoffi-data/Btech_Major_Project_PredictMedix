// PredictMedix JavaScript Functionality

document.addEventListener("DOMContentLoaded", () => {
  // Theme Toggle Feature
  const themeToggleBtn = document.getElementById("theme-toggle");
  
  if (themeToggleBtn) {
    themeToggleBtn.addEventListener("click", () => {
      const currentTheme = document.documentElement.getAttribute("data-theme");
      let newTheme = "light";
      
      if (currentTheme === "light") {
        newTheme = "dark";
      }
      
      document.documentElement.setAttribute("data-theme", newTheme);
      localStorage.setItem("theme", newTheme);
    });
  }

  // Handle Flash Message Dismissal with Animation
  const closeButtons = document.querySelectorAll(".flash-close-btn");
  closeButtons.forEach(btn => {
    btn.addEventListener("click", (e) => {
      const alertMessage = e.target.closest(".flash-message");
      if (alertMessage) {
        alertMessage.style.transition = "opacity 0.3s ease, transform 0.3s ease";
        alertMessage.style.opacity = "0";
        alertMessage.style.transform = "translateY(-10px)";
        setTimeout(() => {
          alertMessage.remove();
        }, 300);
      }
    });
  });

  // Password Visibility Toggle for Form Fields
  const togglePasswordVisibility = (toggleBtnId, passwordFieldId) => {
    const toggleBtn = document.getElementById(toggleBtnId);
    const passwordField = document.getElementById(passwordFieldId);
    
    if (toggleBtn && passwordField) {
      toggleBtn.addEventListener("click", () => {
        const isPassword = passwordField.type === "password";
        passwordField.type = isPassword ? "text" : "password";
        
        // Update toggle icon/text
        const eyeIcon = toggleBtn.querySelector("i");
        if (eyeIcon) {
          if (isPassword) {
            eyeIcon.classList.remove("fa-eye");
            eyeIcon.classList.add("fa-eye-slash");
          } else {
            eyeIcon.classList.remove("fa-eye-slash");
            eyeIcon.classList.add("fa-eye");
          }
        }
      });
    }
  };

  togglePasswordVisibility("toggle-password", "password");
  togglePasswordVisibility("toggle-confirm-password", "confirm_password");
  
  // Real-time signup validation checks
  const signupForm = document.querySelector(".signup-form");
  if (signupForm) {
    const password = document.getElementById("password");
    const confirmPassword = document.getElementById("confirm_password");
    const mobile = document.getElementById("mobile");

    signupForm.addEventListener("submit", (e) => {
      let valid = true;

      // Mobile Number validation (must match flask server validation: ^[6-9]\d{9}$)
      const mobileRegex = /^[6-9]\d{9}$/;
      if (mobile && !mobileRegex.test(mobile.value)) {
        alert("Please enter a valid 10-digit Indian mobile number starting with 6-9.");
        valid = false;
      }

      // Password matching validation
      if (password && confirmPassword && password.value !== confirmPassword.value) {
        alert("Passwords do not match!");
        valid = false;
      }

      if (!valid) {
        e.preventDefault();
      }
    });
  }
});
