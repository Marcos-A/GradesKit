// Switch between the tools. The URL hash (#combina / #omple / #afegeix) keeps the
// selected tool when the page is reloaded or shared; without a hash, the page
// opens on the tool used last in this browser.

(() => {
  const HASHES = { merge: "#combina", fill: "#omple", add: "#afegeix" };
  const TAB_KEY = "gradeskit.tab";
  const tabs = Array.from(document.querySelectorAll(".tab"));

  // Storage can be blocked (private windows); the tab then simply isn't
  // remembered.
  function savedTab() {
    try {
      return localStorage.getItem(TAB_KEY);
    } catch {
      return null;
    }
  }

  function rememberTab(name) {
    try {
      localStorage.setItem(TAB_KEY, name);
    } catch {
      // Not remembered.
    }
  }

  function selectTab(name, updateHash = true) {
    for (const tab of tabs) {
      const isActive = tab.dataset.tab === name;
      tab.classList.toggle("is-active", isActive);
      tab.setAttribute("aria-selected", String(isActive));
      document.getElementById(tab.getAttribute("aria-controls")).hidden = !isActive;
    }
    if (updateHash) {
      history.replaceState(null, "", HASHES[name]);
    }
    rememberTab(name);
  }

  for (const tab of tabs) {
    tab.addEventListener("click", () => selectTab(tab.dataset.tab));
  }

  const fromHash = Object.keys(HASHES).find((name) => HASHES[name] === location.hash);
  const saved = savedTab();
  if (fromHash) {
    selectTab(fromHash, false);
  } else {
    selectTab(saved in HASHES ? saved : "merge", saved in HASHES);
  }
})();
