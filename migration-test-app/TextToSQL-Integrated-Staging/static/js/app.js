
document.addEventListener("DOMContentLoaded", () => {
    const root = document.documentElement;
    const themePickers = document.querySelectorAll("#theme-picker");
    const savedTheme = localStorage.getItem("text-to-sql-theme") || "dark";

    function applyTheme(theme) {
        const allowed = ["dark", "light", "read"];
        const selected = allowed.includes(theme) ? theme : "dark";

        root.setAttribute("data-theme", selected);
        localStorage.setItem("text-to-sql-theme", selected);

        themePickers.forEach((picker) => {
            picker.value = selected;
        });
    }

    applyTheme(savedTheme);

    themePickers.forEach((picker) => {
        picker.addEventListener("change", () => applyTheme(picker.value));
    });

    document.querySelectorAll("[data-question]").forEach((button) => {
        button.addEventListener("click", () => {
            const questionBox = document.querySelector("#question");
            if (questionBox) {
                questionBox.value = button.dataset.question;
                questionBox.focus();
            }
        });
    });

    const form = document.querySelector("#question-form");
    const askButton = document.querySelector("#ask-button");

    if (form && askButton) {
        form.addEventListener("submit", () => {
            askButton.disabled = true;
            askButton.textContent = "Generating SQL...";
        });
    }
});
