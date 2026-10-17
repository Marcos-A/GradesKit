// Switch between the tools. The URL hash (#combina / #omple) keeps the
// selected tool when the page is reloaded or shared.

(() => {
  const HASHES = { merge: "#combina", fill: "#omple" };
  const tabs = Array.from(document.querySelectorAll(".tab"));

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
  }

  for (const tab of tabs) {
    tab.addEventListener("click", () => selectTab(tab.dataset.tab));
  }

  const initial = Object.keys(HASHES).find((name) => HASHES[name] === location.hash) || "merge";
  selectTab(initial, false);
})();
