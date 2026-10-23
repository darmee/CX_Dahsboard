/*
 * Light and dark mode.
 *
 * Without a choice, the dashboard follows the computer's setting. The switch at the top (sun / moon) picks
 * one instead: it's stored in the browser (localStorage "theme", the same key Django's admin uses, so both
 * agree) and put on the page as <html data-theme="dark">, which dashboard.css reads. base.html applies a
 * stored choice before the page is drawn, so it never flashes the wrong colours.
 * Charts can't read CSS by themselves, so a "themechange" event tells charts.js to redraw them.
 */
const root = document.documentElement;
const computerIsDark = window.matchMedia("(prefers-color-scheme: dark)");

// "light" or "dark": the choice made with the switch, or else the computer's setting
export function currentTheme() {
  return root.dataset.theme || (computerIsDark.matches ? "dark" : "light");
}

// Make the switch work: show the icon for the other mode, and swap modes when pressed.
export function wireThemeToggle(button) {
  const show = () => {
    const now = currentTheme();
    const other = now === "dark" ? "light" : "dark";
    button.dataset.mode = now; // the CSS shows the sun in dark mode and the moon in light mode
    button.setAttribute("aria-label", `Switch to ${other} mode`);
    button.title = `Switch to ${other} mode`;
  };
  button.addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {
      // the browser won't store it (e.g. a private window): the switch still works until the page is closed
    }
    show();
    window.dispatchEvent(new Event("themechange"));
  });
  computerIsDark.addEventListener("change", show);
  show();
}
