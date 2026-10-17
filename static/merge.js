// Quiz merge tool: stage CSV/ZIP uploads and download the merged result.

(() => {
  const mergeForm = document.getElementById("merge-form");
  const fileInput = document.getElementById("file-input");
  const uploadZone = document.getElementById("upload-zone");
  const uploadList = document.getElementById("upload-list");
  const formAlerts = document.getElementById("form-alerts");
  const strategySelect = document.getElementById("strategy");
  const weightedField = document.getElementById("weighted-percent-field");
  const weightedPercentInput = document.getElementById("weighted-percent-input");
  const stagedFiles = [];

  function clearErrorAlert() {
    formAlerts.innerHTML = "";
  }

  function clearStagedFilesWithTransition() {
    // Successful downloads clear the staged list, but with a brief fade so
    // the reset feels intentional instead of abrupt.
    const chips = Array.from(uploadList.querySelectorAll(".upload-chip"));
    if (chips.length === 0) {
      stagedFiles.length = 0;
      renderUploadList();
      return;
    }

    uploadList.classList.add("is-clearing");
    for (const chip of chips) {
      chip.classList.add("is-removing");
    }

    window.setTimeout(() => {
      stagedFiles.length = 0;
      uploadList.classList.remove("is-clearing");
      renderUploadList();
    }, 220);
  }

  function resetRetryState() {
    clearErrorAlert();
    clearStagedFilesWithTransition();
  }

  function syncWeightedField() {
    // Hide the percentage card when it does not apply, but keep its grid
    // slot reserved so the surrounding layout stays stable.
    const isWeighted = strategySelect.value === window.GRADESKIT.strategyWeighted;
    weightedField.classList.toggle("is-hidden", !isWeighted);
    weightedPercentInput.disabled = !isWeighted;
    weightedPercentInput.setAttribute("aria-disabled", String(!isWeighted));
  }

  function normalizeWeightedPercentValue(value, finalize = false) {
    // The field is percentage-oriented in the UI. We accept flexible input
    // while the user types, then normalize it to a clean percentage string.
    let cleaned = value.replace(/\s+/g, "").replace(/\./g, ",");
    const hadPercent = cleaned.includes("%");
    cleaned = cleaned.replace(/[^0-9,%]/g, "");

    const parts = cleaned.replace(/%/g, "").split(",");
    const integerPart = parts[0] || "";
    const decimalPart = parts.slice(1).join("");

    if (!integerPart && !decimalPart) {
      return "";
    }

    let normalized = integerPart;
    if (parts.length > 1) {
      normalized += `,${decimalPart}`;
    }

    if (normalized === ",") {
      return "";
    }

    const numeric = Number(normalized.replace(",", "."));
    if (Number.isNaN(numeric)) {
      return "";
    }

    if (numeric > 100) {
      normalized = "100";
    }

    const shouldAppendPercent = finalize || hadPercent;
    if (normalized.endsWith(",")) {
      return normalized;
    }

    return shouldAppendPercent ? `${normalized}%` : normalized;
  }

  function renderUploadList() {
    if (stagedFiles.length === 0) {
      uploadList.innerHTML = '<span class="upload-placeholder">Encara no s\'ha seleccionat cap fitxer.</span>';
      return;
    }

    uploadList.innerHTML = stagedFiles
      .map((file) => `<span class="upload-chip">${escapeHtml(file.name)}</span>`)
      .join("");
  }

  function addFiles(files) {
    clearErrorAlert();
    // Avoid showing the same file twice if the browser fires repeated
    // change events or the user selects the same file again accidentally.
    for (const file of files) {
      const duplicate = stagedFiles.some((item) => item.name === file.name && item.size === file.size);
      if (!duplicate) {
        stagedFiles.push(file);
      }
    }
    renderUploadList();
  }

  // The visible upload area is a custom control. It delegates to a hidden
  // native file input so the browser still handles file permissions.
  uploadZone.addEventListener("click", () => {
    resetRetryState();
    fileInput.click();
  });
  uploadZone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      resetRetryState();
      fileInput.click();
    }
  });

  // A drop replaces the staged files, like choosing them with a click. The
  // list is cleared at once: the click's fade would run after the new files
  // are added and remove them.
  bindFileDrop(uploadZone, fileInput, formAlerts, (files) => {
    stagedFiles.length = 0;
    addFiles(files);
  });

  fileInput.addEventListener("change", () => {
    addFiles(Array.from(fileInput.files || []));
    fileInput.value = "";
  });

  weightedPercentInput.addEventListener("input", () => {
    weightedPercentInput.value = normalizeWeightedPercentValue(weightedPercentInput.value);
  });

  weightedPercentInput.addEventListener("blur", () => {
    weightedPercentInput.value = normalizeWeightedPercentValue(weightedPercentInput.value, true);
  });

  mergeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    weightedPercentInput.value = normalizeWeightedPercentValue(weightedPercentInput.value, true);

    const formData = new FormData(mergeForm);
    for (const file of stagedFiles) {
      formData.append("csv_files", file, file.name);
    }

    // Submit through fetch so the page can keep its current state, surface
    // validation errors inline, and still trigger a direct file download.
    const response = await fetch("/merge", { method: "POST", body: formData });
    if (!response.ok) {
      showError(formAlerts, await readError(response));
      return;
    }

    await downloadResponse(response, "resultat");
    clearStagedFilesWithTransition();
  });

  strategySelect.addEventListener("change", syncWeightedField);
  syncWeightedField();
  renderUploadList();
})();
